"""Serve a transport-level fake over localhost HTTP, for code the test can't hand a transport.

The `atlas` CLI runs as a subprocess and the API builds its own clients from settings, so
integration tests point them at `serve(handler)`'s URL instead. The handler is the same one the
in-process `httpx2.MockTransport` uses; a handler that raises (an unrecorded request) answers
500 and the error is kept in `errors` for the test to re-raise.
"""

import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx2

type Handler = Callable[[httpx2.Request], httpx2.Response]


@dataclass
class Served:
    url: str
    errors: list[BaseException] = field(default_factory=list[BaseException])

    def raise_errors(self) -> None:
        if self.errors:
            raise self.errors[0]


@contextmanager
def serve(handler: Handler) -> Generator[Served]:
    served = Served(url="")

    class _RequestHandler(BaseHTTPRequestHandler):
        def _dispatch(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            request = httpx2.Request(
                self.command,
                f"{served.url}{self.path}",
                headers=[(k, v) for k, v in self.headers.items() if k.lower() != "host"],
                content=body,
            )
            try:
                response = handler(request)
                response.read()
                status, headers, content = response.status_code, response.headers, response.content
            except Exception as error:
                served.errors.append(error)
                status, headers, content = 500, httpx2.Headers(), str(error).encode()
            self.send_response(status)
            for key, value in headers.items():
                if key.lower() not in {"content-length", "transfer-encoding", "connection"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _dispatch

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _RequestHandler)
    served.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield served
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
