"""Check the Hindsight study readers' findings against the files they cite.

`python .scratch/tools/study_audit.py <workflow output file>`: for every finding, the cited file
must exist and hold the quote verbatim (whitespace folded); a quote over 300 characters or with
an ellipsis breaks the brief. Prints a table per reader and writes the findings, each with its
check, to .scratch/hindsight-study/findings.json.
"""

import json
import pathlib
import sys


def squash(text):
    return " ".join(text.split())


def main():
    raw = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
    data = json.loads(raw[raw.index("{") :]) if not raw.lstrip().startswith("{") else json.loads(raw)
    data = data.get("result", data)
    files = {}
    out = []
    for entry in data["slices"]:
        key, result = entry["key"], entry["result"]
        counts = {"found": 0, "not_found": 0, "no_file": 0, "too_long": 0, "ellipsis": 0}
        importance = {"high": 0, "medium": 0, "low": 0}
        for finding in result["findings"]:
            path = pathlib.Path(finding["source_file"].split(":")[0])
            if path not in files:
                files[path] = squash(path.read_text(encoding="utf-8", errors="replace")) if path.is_file() else None
            quote = squash(finding["quote"])
            if files[path] is None:
                check = "no_file"
            elif quote in files[path]:
                check = "found"
            else:
                check = "not_found"
            counts[check] += 1
            if len(finding["quote"]) > 300:
                counts["too_long"] += 1
            if "…" in finding["quote"] or "..." in finding["quote"]:
                counts["ellipsis"] += 1
            importance[finding["importance"]] += 1
            out.append({"reader": key, "check": check, **finding})
        notes = pathlib.Path(result["notes_file"])
        size = notes.stat().st_size if notes.is_file() else 0
        print(
            f"{key:18} findings {len(result['findings']):3}  {counts}  importance {importance}  "
            f"notes {size:6} bytes  contradictions {len(result.get('contradictions', []))}  "
            f"not_covered {len(result['not_covered'])}"
        )
    for finding in out:
        if finding["check"] != "found":
            print(f"  {finding['check']}: [{finding['reader']}] {finding['topic']} | {finding['source_file']} | {finding['quote'][:140]!r}")
    target = pathlib.Path(".scratch/hindsight-study/findings.json")
    target.write_text(json.dumps({"slices": data["slices"], "checked": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {target} ({len(out)} findings)")


if __name__ == "__main__":
    main()
