import os
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phase3.py")
s = open(p, encoding="utf8").read()


def cut(s, start_marker, end_marker, new):
    a = s.index(start_marker)
    b = s.index(end_marker, a)
    return s[:a] + new + s[b:]


s = cut(s, "STOOQ_NOTE = (", "ORDER =",
        'STOOQ_NOTE = "Stooq was not obtained (its CSV endpoint refused scripted and browser requests); by the lead\'s decision the closes come from Atlas\'s own price history after a deploy."\n')
s = s.replace('"eligible = a 10-K, 10-Q, 20-F or 40-F (amendments included) filed on or before the first as-of date D, per submissions (`recent` plus `files`); "',
              '"eligible = its latest 10-K, 10-Q, 20-F or 40-F (amendments included) on or before the first as-of date D, per submissions (`recent` plus `files`), was filed within the 365 days before D (D-365 to D; rule note of 2026-10-18, the lead\'s decision, replacing \'any periodic report on or before D\'); "')
s = s.replace('"periodic filing after D times the Stooq close on D.',
              '"periodic report after D, as amended by a later amendment of that same cover (both figures recorded), times the close on D from Atlas\'s price history (`closes.json`, null until filled; phase2 stops on a null).')
s = cut(s, 'md.append("**Status:', "md.append(\"**Open questions", "")
s = cut(s, 'md.append("**Open questions', "for slug in ORDER:",
        '''md.append("**Status:** Snap drawn. SanDisk, IREN and POET pending their closes (`closes.json` is a template with null closes; `phase2.py` stops on a null). eToro undrawn: no SEC share count or float.\\n")
md.append("**Rule note, 2026-10-18 (the lead):** (1) freshness: a candidate's latest periodic report on or before D must have been filed D-365 to D; its float is still from the latest 10-K/20-F/40-F on or before D; (2) the share count is the first periodic report after D, as amended; (3) closes from Atlas's price history only, no web access; (4) eToro: no controls; (5) floats of 0 and non-USD floats stay excluded and listed, one seeded Random per case.\\n")

''')
s = s.replace('''md.append("- Candidates found by the browse: %d (less the case: %d, less the universe: %d) = %d. No periodic report on or before D: %d. Eligible: %d."
              % (c["browse_total"], len(c["excluded_case"]), len(c["excluded_universe"]), c["candidates_after_exclusions"], c["ineligible_no_periodic"], c["eligible"]))''',
              '''md.append("- Candidates found by the browse: %d (less the case: %d, less the universe: %d) = %d. No periodic report on or before D: %d. Latest periodic report filed before %s (older than 365 days): %d. Eligible: %d."
              % (c["browse_total"], len(c["excluded_case"]), len(c["excluded_universe"]), c["candidates_after_exclusions"], c["ineligible_no_periodic"], c["fresh_cutoff"], c["stale_latest_periodic_before_cutoff"], c["eligible"]))''')
s = cut(s, '        if cv.get("shares_rows"):', '    if not c["drawn"]:',
        '''        if cv.get("shares_original"):
            o_ = cv["shares_original"]
            am_ = cv.get("shares_amended")
            md.append("  - Shares, first periodic report after D: %s (`dei:EntityCommonStockSharesOutstanding`, %s filed %s, as of %s, accession %s)." % ("{:,}".format(o_["val"]), o_["form"], o_["filed"], o_["end"], o_["accn"]))
            if am_:
                md.append("  - Amended: %s (%s filed %s, same cover date, accession %s). Used: the amended figure, %s. Both recorded." % ("{:,}".format(am_["val"]), am_["form"], am_["filed"], am_["accn"], "{:,}".format(cv["shares_used"])))
            md.append("  - Times the close on %s from Atlas's price history: **pending** (`closes.json`)." % c["D"])
        else:
            md.append("  - Undrawn: no SEC share count or float (companyfacts for this CIK has only the taxonomies %s; no shares outstanding in any periodic report after D)." % cv.get("facts_taxonomies"))
''')
s = s.replace('''        md.append("- **Not drawn:** %s." % c["not_drawn_reason"])
        md.append("- Ready to draw once the close is given: %d eligible candidates with a positive float, listed in `controls.json` (`eligible_floats`)." % len(c["eligible_floats"]))''',
              '''        md.append("- **%s:** %s." % ("Pending" if c.get("pending") else "Not drawn", c["not_drawn_reason"]))
        if c.get("pending"):
            md.append("- Ready to draw once the close is in: %d eligible candidates with a positive float, in `controls.json` (`eligible_floats`)." % len(c["eligible_floats"]))''')
s = cut(s, '    md.append("\\n**Flag:**', "    rc = [x for x", "")
s = s.replace("Stooq: 0 by script; 2 scripted requests and 2 Chrome page loads, all refused or challenged, no data.",
              "Stooq: 2 scripted requests and 2 Chrome page loads earlier, all refused, no data; no web access since, and the 2026-10-18 rerun used the cache only.")
s = s.replace('"stooq_note": STOOQ_NOTE', '"stooq_note": STOOQ_NOTE, "rule_note_2026_10_18": "freshness 365 days; shares as amended; closes from Atlas price history; eToro undrawn; zero and non-USD floats excluded and listed"')
open(p, "w", encoding="utf8").write(s)
print("patched")
