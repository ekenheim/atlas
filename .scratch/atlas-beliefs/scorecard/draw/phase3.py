import json, os
BASE = os.path.dirname(os.path.abspath(__file__))
O = json.load(open(os.path.join(BASE, "phase2.json")))
CNT = json.load(open(os.path.join(BASE, "request_count.json")))
OUT = r"C:\Users\ekenh\atlas-wt-backend\.scratch\atlas-beliefs\scorecard"
STOOQ_NOTE = "Stooq was not obtained (its CSV endpoint refused scripted and browser requests); by the lead's decision the closes come from Atlas's own price history after a deploy."
ORDER = ["sandisk", "iren", "etoro", "snap", "poet-technologies"]
PRICE_ORDER = {}


def money(v):
    return "${:,.0f}".format(v)


md = []
md.append("# Controls for the early-call scorecard\n")
md.append("Drawn 2026-10-18 from SEC EDGAR, live, by the rule of Amendment 2 (\"Controls\") and Amendment 1 (\"Control list for the code half\"). "
          "Per case: the SIC is the case's `sic` in its submissions JSON (today's SIC); candidates are every filer the EDGAR company browse lists under that SIC "
          "(`owner=include`, every page), less the case and every `cik:` in `configs/themes/ai-infrastructure.yaml` (Western Digital is not in that file, so it stays); "
          "eligible = its latest 10-K, 10-Q, 20-F or 40-F (amendments included) on or before the first as-of date D, per submissions (`recent` plus `files`), was filed within the 365 days before D (D-365 to D; rule note of 2026-10-18, the lead's decision, replacing 'any periodic report on or before D'); "
          "market value = `dei:EntityPublicFloat` (USD) from companyfacts, the latest 10-K/20-F/40-F (amendments included) filed on or before D, the latest `end` if it reports several; "
          "an eligible candidate with none is excluded and listed, never substituted. The case uses the same measure, else `dei:EntityCommonStockSharesOutstanding` of its first "
          "periodic report after D, as amended by a later amendment of that same cover (both figures recorded), times the close on D from Atlas's price history (`closes.json`, null until filled; phase2 stops on a null). Distance = |ln(candidate / case)|; eligible candidates with a float, sorted by CIK, are shuffled with "
          "`random.Random(20261018).shuffle` (a fresh generator per case) and stably sorted by distance; the first two are the controls. "
          "All values are the reported ones; a float of 0 has an undefined distance and is listed apart, not ranked.\n")
md.append("**Status:** Snap drawn. SanDisk, IREN and POET pending their closes (`closes.json` is a template with null closes; `phase2.py` stops on a null). eToro undrawn: no SEC share count or float.\n")
md.append("**Rule note, 2026-10-18 (the lead):** (1) freshness: a candidate's latest periodic report on or before D must have been filed D-365 to D; its float is still from the latest 10-K/20-F/40-F on or before D; (2) the share count is the first periodic report after D, as amended; (3) closes from Atlas's price history only, no web access; (4) eToro: no controls; (5) floats of 0 and non-USD floats stay excluded and listed, one seeded Random per case.\n")

for slug in ORDER:
    c = O[slug]
    md.append("\n## %s\n" % slug)
    md.append("- SIC **%s**, %s. CIK %s; first as-of date %s." % (c["sic"], c["sic_description"], c["cik"], c["D"]))
    md.append("- Candidates found by the browse: %d (less the case: %d, less the universe: %d) = %d. No periodic report on or before D: %d. Latest periodic report filed before %s (older than 365 days): %d. Eligible: %d."
              % (c["browse_total"], len(c["excluded_case"]), len(c["excluded_universe"]), c["candidates_after_exclusions"], c["ineligible_no_periodic"], c["fresh_cutoff"], c["stale_latest_periodic_before_cutoff"], c["eligible"]))
    if c["excluded_universe"]:
        md.append("- Universe companies excluded: " + ", ".join("%s (%s)" % (u["name"], u["cik"]) for u in c["excluded_universe"]) + ".")
    nofl = c["no_public_float"]
    md.append("- Excluded for no public float: %d of %d eligible (%d with a float, of which %d reported 0 and are not ranked)."
              % (len(nofl), c["eligible"], c["eligible_with_float"], len(c["float_reported_as_zero"])))
    md.append("\n<details><summary>No public float (%d)</summary>\n" % len(nofl))
    for n in nofl:
        md.append("- %s (%s): %s" % (n["name"], n["cik"], n["reason"]))
    md.append("\n</details>\n")
    if c["float_reported_as_zero"]:
        md.append("<details><summary>Float reported as 0 (%d)</summary>\n" % len(c["float_reported_as_zero"]))
        for n in c["float_reported_as_zero"]:
            md.append("- %s (%s), filed %s" % (n["name"], n["cik"], n["filed"]))
        md.append("\n</details>\n")
    cv = c["case_value"]
    if cv.get("measure") == "EntityPublicFloat":
        md.append("- Case market value: **%s**, `dei:EntityPublicFloat`, 10-K filed %s (period end %s), accession %s. Source: %s"
                  % (money(cv["value"]), cv["filed"], cv["end"], cv["accn"], cv["source"]))
    else:
        md.append("- Case market value: **not obtained.** No `EntityPublicFloat` in a 10-K/20-F/40-F filed on or before D (%s)." % cv.get("float_absent_reason"))
        if cv.get("shares_original"):
            o_ = cv["shares_original"]
            am_ = cv.get("shares_amended")
            md.append("  - Shares, first periodic report after D: %s (`dei:EntityCommonStockSharesOutstanding`, %s filed %s, as of %s, accession %s)." % ("{:,}".format(o_["val"]), o_["form"], o_["filed"], o_["end"], o_["accn"]))
            if am_:
                md.append("  - Amended: %s (%s filed %s, same cover date, accession %s). Used: the amended figure, %s. Both recorded." % ("{:,}".format(am_["val"]), am_["form"], am_["filed"], am_["accn"], "{:,}".format(cv["shares_used"])))
            md.append("  - Times the close on %s from Atlas's price history: **pending** (`closes.json`)." % c["D"])
        else:
            md.append("  - Undrawn: no SEC share count or float (companyfacts for this CIK has only the taxonomies %s; no shares outstanding in any periodic report after D)." % cv.get("facts_taxonomies"))
    if not c["drawn"]:
        md.append("- **%s:** %s." % ("Pending" if c.get("pending") else "Not drawn", c["not_drawn_reason"]))
        if c.get("pending"):
            md.append("- Ready to draw once the close is in: %d eligible candidates with a positive float, in `controls.json` (`eligible_floats`)." % len(c["eligible_floats"]))
        continue
    md.append("- Nearest by distance: " + "; ".join("%s %s (%s) d=%.4f" % (r["name"], money(r["float"]), r["float_filed"], r["distance"]) for r in c["ranking_top10"][:5]) + ".")
    if len({round(x["distance"], 12) for x in c["ranking_top10"][:2]}) == 1:
        md.append("- The first two are tied on distance (equal floats); the shuffle's order decides which is first. The tie is inside the controls, so both are drawn.")
    md.append("\n### The two controls\n")
    for i, k in enumerate(c["controls"], 1):
        md.append("**%d. %s** (CIK %s)" % (i, k["name"], k["cik"]))
        md.append("- Ticker: %s; exchange: %s." % (k["ticker_today"], k["exchange_today"]))
        md.append("- Forms filed 2024-2025: %s." % (", ".join(k["forms_filed_2024_2025"]) or "none"))
        f = k["float"]
        md.append("- Float: %s, period end %s, %s filed %s (accession %s). Distance %.4f." % (money(f["value"]), f["end"], f["form"], f["filed"], f["accn"], k["distance"]))
        md.append("- Filed in 2026: %s (periodic report in 2026: %s; latest filing %s)." % ("yes" if k["filed_in_2026"] else "no", "yes" if k["periodic_filed_2026"] else "no", k["latest_filing_date"]))
    rc = [x for x in c["reading_check_top6"] if not x["same_filing"]]
    md.append("- Reading check: the float comes from the filing that submissions lists as the latest annual report on or before D for all of the top six: %s." % ("no, differs for " + ", ".join(x["name"] for x in rc) if rc else "yes"))

md.append("\nSEC requests made: %d (cache: scratchpad `controls\\cache`; a rerun makes none). Stooq: 2 scripted requests and 2 Chrome page loads earlier, all refused, no data; no web access since, and the 2026-10-18 rerun used the cache only. Drawn 2026-10-18." % CNT["sec"])
open(os.path.join(OUT, "controls.md"), "w", encoding="utf8").write("\n".join(md) + "\n")

J = {"drawn_on": "2026-10-18", "seed": 20261018, "request_counts": {"sec": CNT["sec"], "stooq_scripted": 2, "stooq_browser_page_loads": 2, "stooq_rows_obtained": 0},
     "stooq_note": STOOQ_NOTE, "rule_note_2026_10_18": "freshness 365 days; shares as amended; closes from Atlas price history; eToro undrawn; zero and non-USD floats excluded and listed", "cases": O}
json.dump(J, open(os.path.join(OUT, "controls.json"), "w", encoding="utf8"), indent=1)
print("written")
