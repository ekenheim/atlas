"""A stand-in Atlas over HTTP for the shell scripts' tests (ticket 29b): `agent/run.sh` and
`agent/scorecard-run.sh`, which talk to Atlas with node, not with this process.

Run as a subprocess (the test process opens no socket)::

    python tests/fakes/atlas_http.py CONFIG.json POSTS.jsonl

It prints `port N` on its first line and serves, from the JSON config:

- `GET /api/v1/companies` -> `{"items": config.companies}`
- `GET /api/v1/sessions?limit=&offset=` -> a page of `config.sessions` (newest first as given)
  with its `total`; `config.sessions_status` (default 200) is the status it answers with
- `GET /api/v1/watch-runs?theme=&limit=` -> `{"items": ...}`: the newest `config.watch_runs` of the
  theme (`{"theme", "run_date", ...}`, newest first as given); `config.watch_runs_status` (default
  200) is the status it answers with (the Watch's mode and since date, ticket W2)
- `POST /api/v1/sessions` -> appends the request body as one line to POSTS.jsonl and answers
  `config.post_status` (default 201) with `{"id": config.post_id, "isolated": config.post_isolated}`

Every request, first, is appended to `POSTS.jsonl.requests` as `METHOD path`, so a test can say
that nothing was asked.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CONFIG = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
POSTS = Path(sys.argv[2])


def note(method: str, path: str) -> None:
    with POSTS.with_name(POSTS.name + ".requests").open("a", encoding="utf-8") as handle:
        handle.write(f"{method} {path}\n")


class Handler(BaseHTTPRequestHandler):
    def send(self, status: int, body: object) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        note("GET", self.path)
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/api/v1/companies":
            self.send(200, {"items": CONFIG.get("companies", [])})
        elif url.path == "/api/v1/sessions":
            sessions = CONFIG.get("sessions", [])
            limit = int(query.get("limit", ["50"])[0])
            offset = int(query.get("offset", ["0"])[0])
            self.send(
                CONFIG.get("sessions_status", 200),
                {
                    "items": sessions[offset : offset + limit],
                    "total": len(sessions),
                    "limit": limit,
                    "offset": offset,
                },
            )
        elif url.path == "/api/v1/watch-runs":
            theme = query.get("theme", [None])[0]
            limit = int(query.get("limit", ["50"])[0])
            runs = [
                each
                for each in CONFIG.get("watch_runs", [])
                if theme is None or each.get("theme") == theme
            ]
            self.send(CONFIG.get("watch_runs_status", 200), {"items": runs[:limit]})
        else:
            self.send(404, {"error": {"code": "not_found"}})

    def do_POST(self) -> None:
        note("POST", self.path)
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        if urlparse(self.path).path != "/api/v1/sessions":
            self.send(404, {"error": {"code": "not_found"}})
            return
        with POSTS.open("a", encoding="utf-8") as handle:
            handle.write(body.replace("\n", " ") + "\n")
        status = CONFIG.get("post_status", 201)
        if status != 201:
            self.send(status, {"error": {"code": "refused", "message": "no"}})
            return
        self.send(
            201,
            {
                "id": CONFIG.get("post_id", "s-opened"),
                "isolated": CONFIG.get("post_isolated", True),
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        return


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
print(f"port {server.server_address[1]}", flush=True)
server.serve_forever()
