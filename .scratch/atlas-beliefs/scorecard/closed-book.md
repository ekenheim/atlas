# Closed-book arm: result (ticket 29, Amendment 2)

Run on 2026-10-18 after Amendment 2 was on main (`d154bde`) and before any code reading or session:
- **Model:** `claude-opus-5-5`, through `claude -p` with no tools, no MCP server and no setting sources, a replaced system prompt, from an empty directory outside any repository.
- **Prompt:** Amendment 2's, verbatim.
- **Samples:** three per case and date, 30 in all, each in a fresh process, shuffled with seed 20261018. Cost $1.56; no errors.
- **Where the data is:** the raw answers and both coders' files are in `.scratch/live-runs/20261018-closed-book/` (gitignored, local), and the script is in the scratchpad (`closed_book.py`).

Two independent Opus coders (A and B) coded every sample against the row components. The calibration probe on a control filer waits for the control draw.

| Case | As-of | Modal code | Coders agree | Anachronism flag (rule: an answer citing an event after the as-of date) |
|---|---|---|---|---|
| SanDisk | 2025-02-28 | **not stated** | yes | **yes**, all three (the April 2025 price increase, named as after the date) |
| SanDisk | 2025-05-31 | **hedged** | yes | no |
| SanDisk | 2025-08-31 | **hedged** | adjudicated | **yes** (the early-September 2025 price increase, named as after the date) |
| IREN | 2025-03-31 | **stated** | yes | unsure (A: the timing of a B200 purchase; B: no) |
| IREN | 2025-05-31 | **stated** | yes | **yes**, sample 3 (50 EH/s reached in June 2025) |
| AXT (calibration) | 2025-08-31 | hedged | yes | **yes** (InP capacity doubling "around or after late 2025") |
| eToro | 2025-09-30 | none or excess | yes | unsure (the timing of the buyback) |
| Snap | 2025-08-31 | none or excess | yes | **yes** (paid Memories storage, about September 2025) |
| POET | 2025-11-30 | none or excess (a constraint faced, not held) | yes | no |
| Raspberry Pi | 2025-10-31 | stated (squeezed buyer) | yes | **yes**, all three (the December 2025 price increases) |

**Adjudication (the lead):**
- **SanDisk 2025-08-31, sample 1** (A: hedged, B: stated) is coded hedged. Both components are asserted: (ii) "deliberately reduced wafer starts" and "supply discipline", and (i) supply "tight, or demand to exceed supply, going into 2026". But the answer states uncertainty about the core claim ("less sure about the exact wording or timing ... undersupplied market"), which the rule codes as hedged. The modal code is therefore hedged.
- **Anachronism.** Coder A recorded post-date events that the answer named but excluded ("falls just after your cutoff, so I've left it out") as not used. The rule says *citing*, and naming the event shows the model knows it, so each one is a flag.

**What it means, by the rules fixed before it ran:**
- IREN is closed-book "stated" at both dates. Its session hits do not discriminate, as pre-registered.
- SanDisk carries anachronism flags (2025-02-28 and 2025-08-31). By Amendment 2 that case's session hits do not discriminate either.
- So both positive cases' session hits are non-discriminating. The decision rests on the miss classes, the FPs and the code arm, the outcome Amendment 2 pre-registered as probable.
- The negatives are closed-book "none or excess". They measure discipline (the model knows these names did not run), not leakage.
- **Observation, not a rule:** without tools the model did not state SanDisk's chosen undersupply as of 2025-02-28 and only hedged it as of 2025-05-31, although it knows what followed. That is the case where the archive's reading could show most, and the anachronism rule removes it from the discriminating count. The rule stands as written. The report will show the SanDisk codes beside its session hits.
