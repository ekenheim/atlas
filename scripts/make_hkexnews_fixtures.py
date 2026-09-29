"""Write the HKEXnews fixtures in `tests/fixtures/hkexnews/innolight/`, deterministically.

    uv run python scripts/make_hkexnews_fixtures.py [OUT_DIR]

**Hand-written, not recorded.** HKEXnews' terms forbid automated access (docs/decisions.md,
"HKEXnews"), so nothing here came from HKEXnews. The shapes follow HKEXnews' title-search
JSON as publicly described (the `result` array serialized into a string; `NEWS_ID`,
`TITLE`, `LONG_TEXT`, `STOCK_CODE`, `STOCK_NAME`, `DATE_TIME` as `DD/MM/YYYY HH:MM` Hong
Kong time, `FILE_TYPE`, `FILE_INFO`, `FILE_LINK`), and the seed-list research (Innolight's
stockId 1000311764, stock code 03308, its interim results' path; HKEXnews serving no
robots.txt). The documents are synthetic PDFs, each saying so, not Innolight's documents:
their figures are invented.

- `search.json`: three rows, newest first: interim results (English), an overseas
  regulatory announcement whose PDF declares Chinese, and allotment results (English)
- the three PDFs under the paths the rows link to
- `robots-404.html`: the error page served for `/robots.txt` (status 404)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_pdf_fixtures import document, text_stream

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "hkexnews" / "innolight"
BASE = "https://www1.hkexnews.hk"
SEARCH = f"{BASE}/search/titleSearchServlet.do"
SYNTHETIC = "SYNTHETIC TEST FIXTURE: not an HKEXnews document; every figure is invented."

INTERIM = "/listedco/listconews/sehk/2026/0821/2026082101227.pdf"
OVERSEAS = "/listedco/listconews/sehk/2026/0904/2026090400456.pdf"
ALLOTMENT = "/listedco/listconews/sehk/2026/0729/2026072900123.pdf"

INTERIM_PAGES = [
    [
        SYNTHETIC,
        "Interim results announcement for the six months ended 30 June 2026",
        "The board is pleased to announce the unaudited interim results of the group.",
    ],
    [
        "Business review",
        "Revenue from 800G and 1.6T optical transceivers was the largest part of the",
        "group's sales in the period, and demand from data centre customers exceeded",
        "the capacity that was available to us. We expanded our module lines and",
        "we depend on a small number of suppliers for indium phosphide laser chips.",
    ],
]
OVERSEAS_PAGES = [
    [
        SYNTHETIC,
        "Overseas regulatory announcement (the Chinese text is the only version).",
    ],
]
ALLOTMENT_PAGES = [
    [
        SYNTHETIC,
        "Announcement of final offer price and allotment results",
        "The offer shares were allotted to the investors that are listed in this",
        "announcement, and dealings in the H shares are expected to commence on the",
        "date that was set out in the prospectus.",
    ],
]


def row(news_id: str, title: str, category: str, when: str, link: str, size: str) -> dict[str, str]:
    return {
        "FILE_INFO": size,
        "NEWS_ID": news_id,
        "SHORT_TEXT": category,
        "TOTAL_COUNT": "3",
        "DOD_WEB_PATH": "",
        "STOCK_NAME": "ZJ INNOLIGHT",
        "TITLE": title,
        "FILE_TYPE": "PDF",
        "DATE_TIME": when,
        "LONG_TEXT": category,
        "STOCK_CODE": "03308",
        "FILE_LINK": link,
    }


def search() -> bytes:
    rows = [
        row(
            "11910001",
            "INTERIM RESULTS ANNOUNCEMENT FOR THE SIX MONTHS ENDED 30 JUNE 2026",
            "Announcements and Notices - [Interim Results]",
            "21/08/2026 22:30",
            INTERIM,
            "412KB",
        ),
        row(
            "11920002",
            "OVERSEAS REGULATORY ANNOUNCEMENT",
            "Announcements and Notices - [Overseas Regulatory Announcement - Other]",
            "04/09/2026 19:05",
            OVERSEAS,
            "96KB",
        ),
        row(
            "11890003",
            "ANNOUNCEMENT OF FINAL OFFER PRICE AND ALLOTMENT RESULTS",
            "Announcements and Notices - [Allotment Results]",
            "29/07/2026 23:00",
            ALLOTMENT,
            "1MB",
        ),
    ]
    rows.sort(key=lambda r: r["NEWS_ID"], reverse=True)  # newest first, as the search sorts
    envelope = {
        "result": json.dumps(rows, separators=(",", ":")),
        "hasNextRow": False,
        "rowRange": 100,
        "lang": "E",
    }
    return json.dumps(envelope, separators=(",", ":")).encode()


def pdf(pages: list[list[str]], lang: str) -> bytes:
    return document([text_stream(p) for p in pages], catalog_extra=f" /Lang ({lang})".encode())


ROBOTS_404 = b"<html><head><title>Error</title></head><body>Page not found</body></html>\n"


def fixtures() -> dict[str, bytes]:
    files = {
        "search.json": search(),
        "robots-404.html": ROBOTS_404,
        INTERIM.lstrip("/"): pdf(INTERIM_PAGES, "en-GB"),
        OVERSEAS.lstrip("/"): pdf(OVERSEAS_PAGES, "zh-CN"),
        ALLOTMENT.lstrip("/"): pdf(ALLOTMENT_PAGES, "en-GB"),
    }
    last_modified = "Fri, 04 Sep 2026 11:05:00 GMT"
    pdf_headers = {"Content-Type": "application/pdf", "Last-Modified": last_modified}
    manifest = {
        "note": (
            "Hand-written from HKEXnews' documented response shapes, not recorded"
            " (scripts/make_hkexnews_fixtures.py). The PDFs are synthetic."
        ),
        "responses": [
            {"url": f"{BASE}/robots.txt", "file": "robots-404.html", "status": 404,
             "headers": {"Content-Type": "text/html"}},
            {"url": f"{SEARCH}?stockId=1000311764", "file": "search.json", "ignore_query": True,
             "headers": {"Content-Type": "application/json;charset=UTF-8"}},
            *(
                {"url": f"{BASE}{link}", "file": link.lstrip("/"), "headers": pdf_headers}
                for link in (INTERIM, OVERSEAS, ALLOTMENT)
            ),
        ],
    }  # fmt: skip
    files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    return files


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    for name, data in fixtures().items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"wrote {path} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
