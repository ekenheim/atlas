import json, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sec import *

PERIODIC = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"}
ANNUAL = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
CASES = [
    ("sandisk", "0002023554", "2025-02-28"),
    ("iren", "0001878848", "2025-03-31"),
    ("etoro", "0001493318", "2025-09-30"),
    ("snap", "0001564408", "2025-08-31"),
    ("poet-technologies", "0001437424", "2025-11-30"),
]
YAML = r"C:\Users\ekenh\atlas-wt-backend\configs\themes\ai-infrastructure.yaml"
UNIVERSE = set()
for m in re.finditer(r'^\s*-?\s*cik:\s*"?(\d+)"?', open(YAML, encoding="utf8").read(), re.M):
    UNIVERSE.add(int(m.group(1)))
WD_IN_FILE = 106040 in UNIVERSE


def browse(sic):
    out = {}
    start = 0
    while True:
        url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC=%s&owner=include&count=100&start=%d" % (sic, start)
        html = fetch(url).decode("utf8", "replace")
        rows = re.findall(r'CIK=(\d{10})[^"]*">\d{10}</a></td>\s*<td scope="row">(.*?)</td>', html, re.S)
        new = 0
        for c, n in rows:
            n = re.sub(r"\s+", " ", re.sub(r"<.*?>", "", n)).strip()
            n = n.replace("&amp;", "&")
            if int(c) not in out:
                out[int(c)] = n
                new += 1
        if not rows or new == 0:
            break
        start += 100
    return out


def chunks(sub):
    """yield (list of (form, date, accn)) newest chunk first"""
    r = sub["filings"]["recent"]
    yield list(zip(r["form"], r["filingDate"], r["accessionNumber"]))
    files = sorted(sub["filings"].get("files", []), key=lambda f: f["filingTo"], reverse=True)
    for f in files:
        yield ("file", f)


def filings_chunks(sub, D):
    r = sub["filings"]["recent"]
    yield list(zip(r["form"], r["filingDate"], r["accessionNumber"]))
    files = sorted(sub["filings"].get("files", []), key=lambda f: f["filingTo"], reverse=True)
    for f in files:
        if f["filingFrom"] > D:
            continue
        j = fetch_json("https://data.sec.gov/submissions/" + f["name"])
        yield list(zip(j["form"], j["filingDate"], j["accessionNumber"]))


def periodic_before(sub, D):
    """Return first periodic filing (form, date) on or before D, searching newest first; and variants seen."""
    variants = None
    for ch in filings_chunks(sub, D):
        c = [x for x in ch if x[1] <= D and x[0] in PERIODIC]
        if c:
            return max(c, key=lambda x: x[1]), variants
        for x in ch:
            if x[1] <= D and re.match(r"^(10-K|10-Q|20-F|40-F)", x[0]) and variants is None:
                variants = x
    return None, variants


def latest_annual_before(sub, D):
    for ch in filings_chunks(sub, D):
        c = [x for x in ch if x[1] <= D and x[0] in ANNUAL]
        if c:
            return max(c, key=lambda x: x[1])
    return None


def float_entry(cf, D):
    """A: among annual-form EntityPublicFloat USD facts filed <= D, the latest filed, then latest end."""
    if cf is None:
        return None, "no companyfacts"
    d = cf.get("facts", {}).get("dei", {}).get("EntityPublicFloat")
    if not d:
        return None, "no EntityPublicFloat"
    units = d["units"]
    if "USD" not in units:
        return None, "non-USD units: " + ",".join(units)
    c = [e for e in units["USD"] if e.get("form") in ANNUAL and e["filed"] <= D]
    if not c:
        return None, "no float in an annual report filed on or before D"
    return max(c, key=lambda e: (e["filed"], e["end"])), None


def main():
    results = {}
    for slug, cik, D in CASES:
        sub = fetch_json("https://data.sec.gov/submissions/CIK%s.json" % cik)
        sic = sub["sic"]
        cands = browse(sic)
        excl_case = [c for c in cands if c == int(cik)]
        excl_univ = [c for c in cands if c in UNIVERSE and c != int(cik)]
        rest = sorted(c for c in cands if c != int(cik) and c not in UNIVERSE)
        print(slug, "sic", sic, "browse", len(cands), "excluded case", len(excl_case), "universe", len(excl_univ), "remaining", len(rest), flush=True)
        recs = []
        for i, c in enumerate(rest):
            s = fetch_json("https://data.sec.gov/submissions/CIK%s.json" % cik10(c))
            rec = {"cik": cik10(c), "name": cands[c], "sec_name": s["name"] if s else None}
            if s is None:
                rec.update(eligible=False, reason="no submissions")
                recs.append(rec)
                continue
            p = periodic_before(s, D)
            if p[0] is not None:
                rec["latest_periodic_before_D"] = {"form": p[0][0], "date": p[0][1]}
            else:
                rec.update(eligible=False, reason="no periodic report on or before D")
                if p[1]:
                    rec["variant_form"] = list(p[1][:2])
                recs.append(rec)
                continue
            rec["eligible"] = True
            cf = fetch_json("https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json" % cik10(c))
            e, why = float_entry(cf, D)
            if e is None:
                rec.update(float=None, no_float_reason=why)
            else:
                rec["float"] = {"value": e["val"], "end": e["end"], "filed": e["filed"], "form": e["form"], "accn": e["accn"]}
            recs.append(rec)
            if (i + 1) % 50 == 0:
                print("  ", i + 1, "/", len(rest), COUNTS, flush=True)
        results[slug] = {"sic": sic, "sic_description": sub["sicDescription"], "D": D, "cik": cik,
                         "browse_total": len(cands), "excluded_case": [cik10(c) for c in excl_case],
                         "excluded_universe": [{"cik": cik10(c), "name": cands[c]} for c in excl_univ],
                         "candidates": recs}
        json.dump(results, open(os.path.join(BASE, "phase1.json"), "w"), indent=1)
    print("done", COUNTS, "WD in file:", WD_IN_FILE, "universe size", len(UNIVERSE))


main()
