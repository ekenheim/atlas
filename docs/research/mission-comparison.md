# The extraction mission, old against new (memory-quality ticket 05)

Run by the lead on 2026-10-02 with `spikes/hindsight/mission_compare_05.py`. **Live:** a local Hindsight 0.10.2 (the spike's Compose), MiniMax-M3 with thinking off through the owner's LiteLLM, `dry-run-extract` (nothing stored; the throwaway bank was deleted). **6 LLM requests** (cap 12), counted and matching the bank's request log. The raw result is in `.scratch/live-runs/20261002-mission-compare/mission-compare-05.json` (not in git).

Three recorded sections, each cut to one chunk: a 10-K risk-factor Item (Lumentum, `part-i-item-1a`), an 8-K press-release exhibit (Lumentum, `chunk-001`), and a call transcript part (the synthetic TradingView fixture, `chunk-001`). Old: template 1.1.0's `retain_mission`, no labels. New: template 1.2.0's `retain_mission` and its `layer` label group.

| Section | Facts, old | Facts, new | New facts with a layer label | Labels |
|---|---|---|---|---|
| 10-K Item 1A | 4 | 3 | 1 | `substrate` |
| 8-K exhibit | 4 | 1 | 1 | `chip-laser`, `module` |
| Transcript part | 3 | 3 | 2 | `chip-laser`, `module` |

## What changed

- **Boilerplate is no longer extracted.** On the press release the old mission turned the forward-looking-statement disclaimer and the list of metrics the company guides on into facts; the new one keeps only the company's description of what it makes. This is the ignore list working.
- **Attribution.** Transcript facts now name who spoke as the company's ("Chief Executive Officer (the company)"), and the answer to an analyst's question is marked as a response.
- **The risk Item** loses one fact by merging two statements about sole sources and long-term agreements into one; nothing material is lost.
- **Layer labels are right where the text names a layer:** "Indium phosphide laser capacity was the constraint on shipments of 1.6T transceivers" is labelled `chip-laser` and `module`.
- **One label was wrong:** a fact about China's export controls on rare earths and critical minerals was labelled `substrate`. The label group's description now says that a raw material, metal or mineral, or its supply, prices or export controls, is no layer (template 1.4.0, before its first release, so the version is not bumped again).

## What this does not show

- The observations mission: it acts at consolidation, which `dry-run-extract` does not run. The conformance check's observation behaviour (check 5) tests it live after the release.
- Three sections, one chunk each, one model run each: extraction is not deterministic, so the counts are indicative, not a rate.
- Whether the tightened label description fixes the mislabel: not re-run (a re-run is 3 requests; it is folded into the conformance check's layer behaviour, check 4, on the release).
