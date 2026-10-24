"""Diagnostician draft (round 3): simulation of the judge's basis-unverified drops on the saved cards."""
import json, re, sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "backend"))
from atlas.investigations.grounding import date_texts, phrase_occurs  # noqa
from atlas.claims.predicates import fold  # noqa

ROOT = ROOT_DIR / ".scratch" / "live-runs"
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
STOP = set("""says said states stated reports reported notes noted according in its the on a an at their to that also separately earlier by then later
call conference filing transcript release earnings results quarter fiscal calendar year half first second third fourth annual filed with of and for
ceo cfo cto coo president chairman executive officer chief vp s inc corp corporation holdings ltd plc co company
q1 q2 q3 q4 h1 h2 fy cy 10-k 10-q 8-k 20-f 6-k k q""".split())


def tokens(text):
    t = fold(text).lower()
    t = re.sub(r"[’']s\b", " ", t)
    return [w for w in re.findall(r"[a-z0-9][a-z0-9\-\.]*", t) if w]


def exempt(clause, allowed_text):
    allowed = set(tokens(allowed_text)) | STOP
    toks = tokens(clause)
    if not toks:
        return True
    for w in toks:
        if w in allowed:
            continue
        if re.fullmatch(rf"({MONTHS})\.?", w):
            continue
        if re.fullmatch(r"(19|20)\d\d", w) or re.fullmatch(r"\d{1,2}(st|nd|rd|th)?", w) or re.fullmatch(r"(fy|cy|q[1-4])?\d{2,4}", w):
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", w):
            continue
        return False
    return True


def main():
    totals = Counter()
    for run, ns in (("0.5.4", (1, 2, 5)), ("0.5.5", (1, 2, 3))):
        for n in ns:
            inv = json.load(open(ROOT / f"pilot-{run}-arg/inv-{n}/investigation.json", encoding="utf-8"))
            card = inv["research_card"]
            facts = {}
            for s in card["steps"]:
                for f in s["facts"] + s["counterevidence"]:
                    facts[f["fact_id"]] = f
                for st in s["statements"]:
                    for f in st["facts"] + st["counterevidence"]:
                        facts[f["fact_id"]] = f
            judged = card.get("judged") or []
            # statement -> step from the editor's accepted output (role-calls)
            rc = json.load(open(ROOT / f"pilot-{run}-arg/inv-{n}/role-calls.json", encoding="utf-8"))
            step_of = {}
            for x in rc["role_calls"]:
                if x["role"] == "editor" and x.get("output") and isinstance(x["output"], dict) and "steps" in x["output"]:
                    for s in x["output"]["steps"]:
                        for st in s.get("statements", []):
                            step_of[st.get("statement", "")] = s.get("step")
            by_finding = {}
            for j in judged:
                by_finding.setdefault(j["finding"], []).append(j)
            kept_now = sum(len(s["statements"]) for s in card["steps"])
            first_sent_back_bu = 0
            first_sent_back_bu_rescued = 0
            dropped = 0
            dropped_rescued = 0
            steps_rescued = Counter()
            for key, js in by_finding.items():
                a1 = [j for j in js if j["attempt"] == 1]
                a2 = [j for j in js if j["attempt"] == 2]
                allowed = ""
                for cid in js[0]["claim_ids"]:
                    f = facts.get(cid)
                    if f:
                        allowed += " " + f["company_name"] + " " + (f.get("source_title") or "")
                        if f.get("evidence_available_at"):
                            allowed += " " + " ".join(date_texts(datetime.fromisoformat(f["evidence_available_at"].replace("Z", "+00:00")).date()))

                def vote_ok(j):
                    # the vote's own verdict was supported iff the reason is a basis-unverified rewrite or verdict supported
                    own_supported = j["verdict"] == "supported" or j["reason"].startswith("basis unverified")
                    if not own_supported:
                        return False
                    lims = set(j.get("limitations") or [])
                    for c in j.get("unverified") or []:
                        if c in lims or any(c.strip() in l for l in lims):
                            continue  # a limitation clause: never judged (iii)
                        if exempt(c, allowed):
                            continue
                        return False
                    return True

                if a1:
                    decided1 = [j for j in a1 if j.get("decided")]
                    d1 = decided1[0] if decided1 else a1[0]
                    if d1["outcome"] == "sent_back" and d1["reason"].startswith("basis unverified"):
                        first_sent_back_bu += 1
                        if all(vote_ok(j) for j in a1):
                            first_sent_back_bu_rescued += 1
                            steps_rescued[step_of.get(d1["statement"], "?")] += 1
                if a2:
                    decided2 = [j for j in a2 if j.get("decided")]
                    d2 = decided2[0] if decided2 else a2[0]
                    if d2["outcome"] == "dropped":
                        dropped += 1
                        if all(vote_ok(j) for j in a2):
                            dropped_rescued += 1
            print(f"{run} Q{n}: kept {kept_now}; first-attempt sent back for basis-unverified {first_sent_back_bu}, of which both votes clean under the exemption {first_sent_back_bu_rescued} (steps {dict(steps_rescued)}); dropped after rewrite {dropped}, of which rescued {dropped_rescued}")
            totals.update({"kept": kept_now, "sent_back_bu": first_sent_back_bu, "sent_back_rescued": first_sent_back_bu_rescued, "dropped": dropped, "dropped_rescued": dropped_rescued})
            # which steps have 0 statements and why
            for s in card["steps"]:
                if not s["statements"] and s["status"] in ("unknown",):
                    drafted = [st for st, sk in step_of.items() if sk == s["step"]]
                    print(f"    step {s['step']} unknown: editor drafted {len(drafted)} statements; facts {len(s['facts'])}")
    print("TOTAL", dict(totals))
    # The unverified clauses still not exempt (to see what remains)
    rest = Counter()
    for run, ns in (("0.5.5", (1, 2, 3)),):
        for n in ns:
            inv = json.load(open(ROOT / f"pilot-{run}-arg/inv-{n}/investigation.json", encoding="utf-8"))
            card = inv["research_card"]
            facts = {}
            for s in card["steps"]:
                for f in s["facts"] + s["counterevidence"]:
                    facts[f["fact_id"]] = f
            for j in card.get("judged") or []:
                if not j["reason"].startswith("basis unverified"):
                    continue
                allowed = ""
                for cid in j["claim_ids"]:
                    f = facts.get(cid)
                    if f:
                        allowed += " " + f["company_name"] + " " + (f.get("source_title") or "")
                        if f.get("evidence_available_at"):
                            allowed += " " + " ".join(date_texts(datetime.fromisoformat(f["evidence_available_at"].replace("Z", "+00:00")).date()))
                lims = set(j.get("limitations") or [])
                for c in j.get("unverified") or []:
                    if c in lims:
                        rest["limitation"] += 1
                    elif exempt(c, allowed):
                        rest["exempt_source_date"] += 1
                    else:
                        rest["other"] += 1
                        if rest["other"] <= 20:
                            print("   other:", c[:110], "| allowed:", allowed[:90])
    print("0.5.5 unverified clauses:", dict(rest))


main()
