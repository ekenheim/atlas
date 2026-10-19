# Bake-off, robotics, as of 2026-10-19: result

- **Atlas:** the robotics architect Watch run, 0.6.18, Opus 5.5, 56 tool calls on the session (the memo says about 43), 6 min 47 s; watch run `77461189-285a-468d-9468-2998e779eb44`, session `9dd01c2b-25e9-4c06-aa4c-129c6249e9ca`.
- **Serenity arm:** interactive Claude Code with web tools and the `serenity-aleabitoreddit` skill pinned at `a56f706`, the brief `robotics-brief.md`, about 55 tool calls (about 36 on research). The owner's paste is the answer of record.

## What each found

| | Atlas | Serenity arm |
|---|---|---|
| Rare-earth magnets | Lead: Dy/Tb sintered NdFeB, licence-gated; every hop a trade report | Two chokepoints: licence-free Dy/Tb (material) and non-China NdFeB capacity (component). Constraint, relief and capture on primary sources |
| Harmonic reducers | Rejected on trade reports | Rejected on Harmonic Drive's own presentation (orders up, capex down 77%) |
| Roller screws | Lead | Rejected: lead-only |
| The 2027-01-10 hinge | "Unverified" | Read on MOFCOM's page (P2) |
| Primary sources on a robotics step | 0 | 11 |

Atlas reached the magnet stack without the skill. The skill's contribution, by the arm's own account, was where to look (magnets, midstream processing); every step it supported rests on documents it read itself.

## Quotes checked (the lead, 2026-10-19, by downloading each source)

All quoted text found verbatim: P2 (MOFCOM; it does not mention rare earths, as the arm said), P3 (White House), P7 (MP: the quote, 840 t, the $(20.3)m loss, 1,452,639 and 934,583 thousand), P9 (Lynas: 8 t Dy and Tb, 1,996 t), P10 (Lynas: the premiums quote, 19 t, A$1,209.1m), P11 (Harmonic Drive: the demand sentence, 24,128, 74,500, 573). P1 (MOFCOM's licence site) could not be fetched from here; P4 to P6 and P8 were not checked.

## Why Atlas lost: structural, not the model

1. The Watch can record a Fact only from an archived document, and `fetch_page` archives only a universe company's pages. In a greenfield theme nothing is reachable: government notices, ASX and TSE filings, MP's 10-Q (an EDGAR hit, "not ingestable").
2. A defect: leads created during the run are refused as step evidence because they postdate the session's as-of time (the run's own start).
3. With nothing citable, the run wrote up early, at about 43 of its 60 calls.

**Checked in the trace (the lead):** item 2 is confirmed. Three `update_chokepoint` step sets on the magnet chokepoint were refused `created_after_as_of`, and one status set was refused `invalid_payload`. The two Facts the run recorded are STMicroelectronics' CEO on humanoids ("not for tomorrow"; invalidation) and Lumentum's 10-K on rare-earth metals (context); neither supports a robotics step. A third, on STMicroelectronics, was refused `statement_beyond_quote`.

## The Serenity diff (the Watch spec's four categories)

- **Independent:** Atlas reached the rare-earth magnet stack, and set aside harmonic reducers, without any of the skill's content.
- **Convergent:** the magnets are the first chokepoint for both, and reducers are rejected by both.
- **His only:** nothing on a robotics step. The arm's primary evidence was its own reading; the skill ranked where to look.
- **Divergent:** roller screws are a lead on Atlas's board and rejected by the arm as lead-only.

## The rules the arm did not keep

The arm had no as-of bound and no fetch gate. It cites two copies as primary sources: P6 (Musk's call, via Adamas Intelligence's reproduction) and P8 (MP's call, via a Webull-hosted transcript, date unknown). Atlas would hold both as leads. Atlas's rules held; its reach failed.

## Judging

The lead judged this himself, not blind: the owner pasted the answer in, so the systems were named. The quote check above is the guard against grading on a curve.
