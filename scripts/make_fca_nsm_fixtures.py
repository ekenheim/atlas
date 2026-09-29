"""Write the FCA NSM fixtures in `tests/fixtures/fca-nsm/iqe/`, deterministically.

    uv run python scripts/make_fca_nsm_fixtures.py [OUT_DIR]

**Hand-written, not recorded.** The shapes follow what the NSM served on 2026-09-29 to a
handful of requests made to learn them (docs/decisions.md, "FCA National Storage
Mechanism"): the search API's Elasticsearch-style answer (`hits.total.value`,
`hits.hits[]._source` with the field names below), `download_link` paths under
`/artefacts/` (`NSM/RNS/<id>.html` for an RNS announcement; `NSM/Portal/NI-…/NI-….pdf` is the
shape of a directly uploaded PDF, seen for another issuer), HTML served as
`text/html;charset=UTF-8` with `Last-Modified`, and 403 for `/robots.txt` on both hosts.
Every identifier, time and document here is invented; the documents are synthetic and say
so, and their figures are not IQE's.

- `search.json`: four rows, newest first by `submitted_date`: IQE's interim results (RNS,
  HTML), IQE's total voting rights (RNS, HTML), a Form 8.3 disclosed by another company
  that names IQE as related issuer (skipped by the adapter), and IQE's annual report
  (direct upload, PDF, a `submitted_date` with nanoseconds)
- the two HTML announcements and the PDF under the paths the rows link to
- `robots-403-data.xml`, `robots-403-api.json`: the bodies served for `/robots.txt`
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_pdf_fixtures import document, text_stream

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "fca-nsm" / "iqe"
API = "https://api.data.fca.org.uk"
DATA = "https://data.fca.org.uk"
SEARCH = f"{API}/search?index=nsm-search"
ARTEFACTS = f"{DATA}/artefacts/"
SYNTHETIC = "SYNTHETIC TEST FIXTURE: not an NSM document; every figure is invented."
IQE_LEI = "213800Y33WHD3ESJJP16"
OTHER_LEI = "213800LBQA1Y9L22JB70"

INTERIM = "NSM/RNS/5a1f0c3e-0000-4000-8000-000000000001.html"
VOTING = "NSM/RNS/5a1f0c3e-0000-4000-8000-000000000002.html"
FORM_83 = "NSM/RNS/5a1f0c3e-0000-4000-8000-000000000003.html"
ANNUAL = "NSM/Portal/NI-000900001/NI-000900001.pdf"


def announcement(title: str, paragraphs: list[str]) -> bytes:
    body = "\n".join(f"<p>{p}</p>" for p in paragraphs)
    return (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        f"<title>{title}</title></head>\n<body>\n<p><b>{SYNTHETIC}</b></p>\n"
        f"<h1>{title}</h1>\n{body}\n</body></html>\n"
    ).encode()


INTERIM_HTML = announcement(
    "IQE plc: H1 2026 Interim Results",
    [
        "IQE plc, the supplier of compound semiconductor wafer products and advanced material"
        " solutions, announces its unaudited interim results for the six months ended"
        " 30 June 2026.",
        "Revenue from indium phosphide epitaxial wafers for data centre lasers grew in the"
        " period, and photonics was the largest part of the group's sales.",
        "The board expects demand for 800G and 1.6T optical transceivers to exceed the"
        " epitaxy capacity that is available to the industry in the second half.",
    ],
)
VOTING_HTML = announcement(
    "IQE plc: Total Voting Rights",
    [
        "In conformity with the Disclosure Guidance and Transparency Rules, the company"
        " notifies the market that its issued share capital consists of ordinary shares of"
        " one penny each, each with one voting right.",
    ],
)
ANNUAL_PAGES = [
    [
        SYNTHETIC,
        "IQE plc",
        "Annual Report and Accounts 2025",
    ],
    [
        "Chair's statement",
        "Revenue from photonics wafers grew in the year, led by indium phosphide epitaxy",
        "for the lasers in data centre optical transceivers. We supply epitaxial wafers",
        "to laser makers, and our largest customer accounted for a large share of revenue.",
    ],
]


def row(
    seq: str,
    link: str,
    lei: str,
    company: str,
    headline: str,
    category: str,
    type_code: str,
    group: str,
    source: str,
    published: str,
    submitted: str,
    related: list[dict[str, str]],
) -> dict[str, object]:
    return {
        "submitted_date": submitted,
        "tag_esef": "",
        "classifications_code": "",
        "document_date": submitted,
        "source": source,
        "type": category,
        "related_org": related,
        "lei_remediation_flag": "N",
        "document_format": "Plain text",
        "category_group": group,
        "classifications": "",
        "lei": lei,
        "download_link": link,
        "disclosure_id": seq,
        "latest_flag": "Y",
        "hist_seq": "1",
        "publication_date": published,
        "seq_id": seq,
        "company": company,
        "last_updated_date": published,
        "headline": headline,
        "type_code": type_code,
    }


def search() -> bytes:
    iqe = "IQE PLC"
    rows = [
        row(
            "5a1f0c3e-0000-4000-8000-000000000001", INTERIM, IQE_LEI, iqe,
            "IQE plc: H1 2026 Interim Results", "Half-year Financial Report", "IR",
            "Financial Results", "RNS", "2026-09-07T06:00:06Z", "2026-09-07T06:12:29Z", [],
        ),
        row(
            "5a1f0c3e-0000-4000-8000-000000000002", VOTING, IQE_LEI, iqe,
            "IQE plc: Total Voting Rights", "Total Voting Rights", "TVR", "Holdings", "RNS",
            "2026-09-01T15:00:00Z", "2026-09-01T15:12:19Z", [],
        ),
        row(
            "5a1f0c3e-0000-4000-8000-000000000003", FORM_83, OTHER_LEI, "BARCLAYS PLC",
            "Form 8.3 IQE PLC", "Form 8.3", "RET", "Mergers and acquisitions", "RNS",
            "2026-06-10T13:55:44Z", "2026-06-10T14:06:25Z",
            [{"lei": IQE_LEI, "company": iqe}],
        ),
        row(
            "5a1f0c3e-0000-4000-8000-000000000004", ANNUAL, IQE_LEI, iqe,
            "IQE plc: Annual Report and Accounts 2025", "Annual Financial Report", "ACS",
            "Financial Results", "Direct upload", "2026-05-29T14:30:00Z",
            "2026-05-29T14:41:07.123456789Z", [],
        ),
    ]  # fmt: skip
    answer = {
        "took": 7,
        "timed_out": False,
        "_shards": {"failed": 0.0, "skipped": 0.0, "successful": 4.0, "total": 4.0},
        "hits": {
            "total": {"relation": "eq", "value": len(rows)},
            "hits": [
                {"_index": "fca-nsm-searchdata", "_id": r["seq_id"], "_source": r} for r in rows
            ],
        },
    }
    return (json.dumps(answer, indent=1) + "\n").encode()


ROBOTS_403_DATA = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b"<Error><Code>AccessDenied</Code><Message>Access Denied</Message></Error>\n"
)
ROBOTS_403_API = b'{"message":"Forbidden"}\n'


def fixtures() -> dict[str, bytes]:
    files = {
        "search.json": search(),
        "robots-403-data.xml": ROBOTS_403_DATA,
        "robots-403-api.json": ROBOTS_403_API,
        INTERIM: INTERIM_HTML,
        VOTING: VOTING_HTML,
        ANNUAL: document([text_stream(p) for p in ANNUAL_PAGES], catalog_extra=b" /Lang (en-GB)"),
    }
    html = {"Content-Type": "text/html;charset=UTF-8"}
    manifest = {
        "note": (
            "Hand-written in the shapes the FCA NSM served on 2026-09-29, not recorded"
            " (scripts/make_fca_nsm_fixtures.py). Identifiers, times and documents are"
            " synthetic."
        ),
        "responses": [
            {"url": f"{API}/robots.txt", "file": "robots-403-api.json", "status": 403,
             "headers": {"Content-Type": "application/json"}},
            {"url": f"{DATA}/robots.txt", "file": "robots-403-data.xml", "status": 403,
             "headers": {"Content-Type": "application/xml"}},
            {"url": SEARCH, "file": "search.json",
             "headers": {"Content-Type": "application/json"}},
            {"url": ARTEFACTS + INTERIM, "file": INTERIM,
             "headers": html | {"Last-Modified": "Mon, 07 Sep 2026 06:12:57 GMT"}},
            {"url": ARTEFACTS + VOTING, "file": VOTING,
             "headers": html | {"Last-Modified": "Tue, 01 Sep 2026 15:12:40 GMT"}},
            {"url": ARTEFACTS + ANNUAL, "file": ANNUAL,
             "headers": {"Content-Type": "application/pdf",
                         "Last-Modified": "Fri, 29 May 2026 14:41:30 GMT"}},
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
