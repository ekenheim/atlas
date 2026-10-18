import json, math, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sec import *
import importlib.util

# reuse helpers without running main
src = open(os.path.join(BASE, "phase1.py")).read().replace("\nmain()\n", "\n")
ns = {"__file__": os.path.join(BASE, "phase1.py")}
exec(compile(src, "phase1_lib", "exec"), ns)
float_entry = ns["float_entry"]
latest_annual_before = ns["latest_annual_before"]
PERIODIC, ANNUAL, CASES = ns["PERIODIC"], ns["ANNUAL"], ns["CASES"]

P1 = json.load(open(os.path.join(BASE, "phase1.json")))
import datetime
ALLOW_PENDING = "--allow-pending" in sys.argv
CLOSES = json.load(open(os.path.join(BASE, "closes.json")))
FRESH_DAYS = 365


def fresh_cutoff(D):
    return (datetime.date.fromisoformat(D) - datetime.timedelta(days=FRESH_DAYS)).isoformat()
TICKERS = fetch_json("https://www.sec.gov/files/company_tickers_exchange.json")
tmap = {}
for row in TICKERS["data"]:
    d = dict(zip(TICKERS["fields"], row))
    tmap.setdefault(d["cik"], []).append(d)


def case_value(slug, cik, D):
    cf = fetch_json("https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json" % cik)
    e, why = float_entry(cf, D)
    out = {"measure": None}
    if e is not None:
        out.update(measure="EntityPublicFloat", value=e["val"], end=e["end"], filed=e["filed"], form=e["form"], accn=e["accn"],
                   source="https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json" % cik)
        return out
    out["float_absent_reason"] = why
    out["facts_taxonomies"] = sorted(cf["facts"].keys())
    # shares outstanding in the first periodic filed after D
    d = cf["facts"].get("dei", {}).get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
    c = [x for x in d if x.get("form") in PERIODIC and x["filed"] > D]
    out["shares_candidates"] = sorted(c, key=lambda x: (x["filed"], x["end"]))[:6]
    if not c:
        out["undrawn_reason"] = "undrawn: no SEC share count or float"
        return out
    first = min(x["filed"] for x in c)
    rows = [x for x in c if x["filed"] == first]
    out["shares_rows"] = rows
    if len(rows) != 1:
        out["undrawn_reason"] = "several share rows on the first filing"
        return out
    r0 = rows[0]
    amends = [x for x in d if x.get("form") == r0["form"] + "/A" and x["end"] == r0["end"] and x["filed"] > r0["filed"]]
    am = max(amends, key=lambda x: x["filed"]) if amends else None
    out["shares_original"] = {"val": r0["val"], "form": r0["form"], "filed": r0["filed"], "end": r0["end"], "accn": r0["accn"]}
    out["shares_amended"] = {"val": am["val"], "form": am["form"], "filed": am["filed"], "end": am["end"], "accn": am["accn"]} if am else None
    sh = am["val"] if am else r0["val"]
    out["shares_used"] = sh
    cl = CLOSES.get(slug)
    if cl is None or cl.get("close") is None:
        if not ALLOW_PENDING:
            sys.exit("STOP: closes.json has a null close for %s (%s). Fill it from Atlas's price history and rerun." % (slug, D))
        out["measure"] = "EntityCommonStockSharesOutstanding x close"
        out["undrawn_reason"] = "pending: close from Atlas price history"
        out["pending"] = True
        return out
    out.update(measure="EntityCommonStockSharesOutstanding x close", shares=sh, close=cl)
    out["value"] = sh * cl["close"]
    if am:
        out["value_with_original_shares"] = r0["val"] * cl["close"]
    return out


def filings_all(sub, since):
    forms = []
    r = sub["filings"]["recent"]
    forms += list(zip(r["form"], r["filingDate"], r["accessionNumber"]))
    for f in sub["filings"].get("files", []):
        if f["filingTo"] >= since:
            j = fetch_json("https://data.sec.gov/submissions/" + f["name"])
            forms += list(zip(j["form"], j["filingDate"], j["accessionNumber"]))
    return forms


def describe(rec, slug, D, case_val):
    cik = rec["cik"]
    sub = fetch_json("https://data.sec.gov/submissions/CIK%s.json" % cik)
    allf = filings_all(sub, "2024-01-01")
    f2425 = sorted({f for f, d, a in allf if "2024-01-01" <= d <= "2025-12-31"})
    f2026 = sorted({f for f, d, a in allf if d >= "2026-01-01"})
    per2026 = sorted({f for f, d, a in allf if d >= "2026-01-01" and f in PERIODIC})
    last = max((d for f, d, a in allf), default=None)
    t = tmap.get(int(cik))
    return {
        "name": rec["name"], "cik": cik, "sec_name": sub["name"],
        "ticker_today": t[0]["ticker"] if t else "not listed today",
        "exchange_today": t[0]["exchange"] if t else "not listed today",
        "submissions_tickers": sub.get("tickers"), "submissions_exchanges": sub.get("exchanges"),
        "forms_filed_2024_2025": f2425,
        "filed_in_2026": bool(f2026), "forms_filed_2026": f2026, "periodic_filed_2026": bool(per2026),
        "latest_filing_date": last,
        "float": rec["float"],
        "distance": rec["distance"],
        "market_value": rec["float"]["value"],
    }


def main():
    out = {}
    for slug, cik, D in CASES:
        r = P1[slug]
        recs = r["candidates"]
        cut = fresh_cutoff(D)
        has_periodic = [x for x in recs if x["eligible"]]
        stale = [x for x in has_periodic if x["latest_periodic_before_D"]["date"] < cut]
        elig = [x for x in has_periodic if x["latest_periodic_before_D"]["date"] >= cut]
        withf = [x for x in elig if x.get("float")]
        nof = [x for x in elig if not x.get("float")]
        cv = case_value(slug, cik, D)
        entry = {"slug": slug, "cik": cik, "D": D, "sic": r["sic"], "sic_description": r["sic_description"],
                 "browse_total": r["browse_total"], "excluded_case": r["excluded_case"], "excluded_universe": r["excluded_universe"],
                 "candidates_after_exclusions": len(recs), "ineligible_no_periodic": len([x for x in recs if not x["eligible"]]),
                 "periodic_on_or_before_D": len(has_periodic), "stale_latest_periodic_before_cutoff": len(stale), "fresh_cutoff": cut, "eligible": len(elig), "eligible_with_float": len(withf),
                 "no_public_float": [{"name": x["name"], "cik": x["cik"], "reason": x.get("no_float_reason")} for x in nof],
                 "case_value": cv}
        entry["float_reported_as_zero"] = [{"name": x["name"], "cik": x["cik"], "filed": x["float"]["filed"]} for x in withf if x["float"]["value"] <= 0]
        entry["eligible_floats"] = sorted(({"cik": x["cik"], "name": x["name"], "float": x["float"]["value"], "end": x["float"]["end"], "filed": x["float"]["filed"], "form": x["float"]["form"]} for x in withf if x["float"]["value"] > 0), key=lambda z: z["cik"])
        entry["shuffle_order_ciks"] = None
        if cv.get("value") is None or len(withf) < 2:
            entry["drawn"] = False
            entry["pending"] = bool(cv.get("pending"))
            entry["not_drawn_reason"] = cv.get("undrawn_reason") if cv.get("value") is None else "fewer than two eligible candidates with a float"
            out[slug] = entry
            continue
        # zero floats make ln undefined
        pos = [x for x in withf if x["float"]["value"] > 0]
        entry["eligible_with_positive_float"] = len(pos)
        pos.sort(key=lambda x: x["cik"])
        random.Random(20261018).shuffle(pos)
        entry["shuffle_order_ciks"] = [x["cik"] for x in pos]
        for x in pos:
            x["distance"] = abs(math.log(x["float"]["value"] / cv["value"]))
        ranked = sorted(pos, key=lambda x: x["distance"])  # stable
        entry["ranking_top10"] = [{"name": x["name"], "cik": x["cik"], "float": x["float"]["value"], "float_end": x["float"]["end"], "float_filed": x["float"]["filed"], "distance": x["distance"]} for x in ranked[:10]]
        entry["controls"] = [describe(x, slug, D, cv) for x in ranked[:2]]
        # alternative reading B check on the top 6: latest annual filing per submissions must carry the float
        alt = []
        for x in ranked[:6]:
            sub = fetch_json("https://data.sec.gov/submissions/CIK%s.json" % x["cik"])
            la = latest_annual_before(sub, D)
            alt.append({"cik": x["cik"], "name": x["name"], "latest_annual_per_submissions": list(la) if la else None,
                        "float_accn": x["float"]["accn"], "same_filing": bool(la and la[2] == x["float"]["accn"])})
        entry["reading_check_top6"] = alt
        entry["drawn"] = True
        out[slug] = entry
    json.dump(out, open(os.path.join(BASE, "phase2.json"), "w"), indent=1)
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk in ("drawn", "not_drawn_reason", "eligible", "eligible_with_float")} for k, v in out.items()}, indent=1))
    print(COUNTS)


main()
