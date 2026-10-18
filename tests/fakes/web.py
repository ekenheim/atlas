"""The fixture web for the tests of `atlas sources fetch` (W3).

`WEB` holds the hand-written pages (`tests/fixtures/web/<company slug>/manifest.json`, replayed
in process through `ATLAS_EXCHANGE_FIXTURES_DIR`) and `WEB_SITES` the synthetic site register
that onboards their hosts (the production register holds none of them). The pages there carry
fixed dates, which are all old; a page's own date counts for `available_at` only within a week
before the fetch, so `recent_web` copies the fixtures and adds pages dated relative to a moment
the test chooses.
"""

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).parents[2]
WEB = REPO / "tests" / "fixtures" / "web"
WEB_SITES = WEB / "sites.yaml"
IR = "https://ir.example-issuer.test"

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
{head}</head>
<body><main><h1>{title}</h1><p>{body}</p></main></body>
</html>
"""


def recent_web(tmp_path: Path, now: datetime) -> Path:
    """A copy of `WEB` with these pages added to Lumentum's, dated relative to `now`:

    - `recent-meta.html`: `article:published_time` one day before `now`;
    - `recent-jsonld.html`: a NewsArticle's `datePublished` two days before;
    - `week-old-meta.html`: `article:published_time` eight days before (too old to believe);
    - `organization-only.html`: only an Organization's `datePublished`, a day before;
    - `time-only.html`: only a `<time datetime>` of the day before;
    - `claims-the-future.html`: `article:published_time` a day after `now`.
    """
    root = tmp_path / "web"
    shutil.copytree(WEB, root)
    shutil.copytree(REPO / "tests" / "fixtures" / "pdf", tmp_path / "pdf")  # the deck's file
    day = timedelta(days=1)
    pages = {
        "recent-meta": (
            "Recent press release",
            f'<meta property="article:published_time" content="{(now - day).isoformat()}">',
        ),
        "recent-jsonld": (
            "Recent news article",
            '<script type="application/ld+json">'
            + json.dumps({"@type": "NewsArticle", "datePublished": (now - 2 * day).isoformat()})
            + "</script>",
        ),
        "week-old-meta": (
            "Press release of last week",
            f'<meta property="article:published_time" content="{(now - 8 * day).isoformat()}">',
        ),
        "organization-only": (
            "About the company",
            '<script type="application/ld+json">'
            + json.dumps({"@type": "Organization", "datePublished": (now - day).isoformat()})
            + "</script>",
        ),
        "time-only": (
            "Events",
            "",
        ),
        "claims-the-future": (
            "Embargoed",
            f'<meta property="article:published_time" content="{(now + day).isoformat()}">',
        ),
    }
    manifest_path = root / "lumentum" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, (title, head) in pages.items():
        body = "Demand for our indium phosphide lasers exceeded our capacity in the quarter."
        if name == "time-only":
            body += f' Posted <time datetime="{(now - day).isoformat()}">yesterday</time>.'
        file = f"ir/news/{name}.html"
        (root / "lumentum" / file).write_text(
            _PAGE.format(title=title, head=head + "\n" if head else "", body=body),
            encoding="utf-8",
        )
        manifest["responses"].append(
            {
                "url": f"{IR}/news/{name}.html",
                "file": file,
                "status": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
            }
        )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return root
