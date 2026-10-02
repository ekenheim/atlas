# 14: The memory conformance check: Hindsight works as advertised, on our settings

**What to build:** Before any benchmark or pilot run, one command says whether Memory behaves as Hindsight's documentation and Atlas's spec promise, with a pass or a fail per behaviour and the evidence for each. The owner asked for this on 2026-10-02: when the system is benchmarked, we know the memory under it works as planned.

Spec: `.scratch/atlas-memory-quality/spec.md` ("Testing Decisions": live effect is measured). Prior art: the live verification (`scripts/live-verify.sh`, `tests/live/verify.py`: parts, capped counting proxies, a throwaway bank always deleted, a rehearsal against the fakes) and `atlas evaluate --live` (a case's sources retained through the real path into a throwaway bank).

Two halves, one report (`.scratch/live-runs/<stamp>-memory-conformance/`, JSON and Markdown; exit 1 when a behaviour fails):

- **Known answers on the live bank (read-only, no LLM call):** `configs/memory/known-answers.yaml` names, per question, the Source Version sections that hold the answer (company slug, document by accession number or URL, section anchor, and the sentence, so a reviewer can check it). The check recalls each question as an investigation would and reports recall at 10 and at 50 for the named sections, per question and overall, against a threshold in the file. The first set is built from the pilot's reviewed results (`.scratch/pilot/results.md`: the facts each review lists under Saved work and Missed evidence), at least 20 answers over the five questions.
- **The known answers follow the research method, not what is easy to find.** The owner asked that the Serenity method guide the work (its analysis: `git show research/serenity-skills-alignment:docs/research/serenity-skills-alignment.md`, findings M1 to M6 and M10; the skill itself is never installed). For each pilot question the answers cover the hops of the chain it asks about (demand, system, module, chip, substrate or feedstock, equipment), and each answer is labelled with the hop and with the part of the bottleneck test it serves: demand against capacity, a second source or qualified substitute, pricing power, share of the bill of materials, a financing or dilution term. The report gives recall per hop and per test part, so a Memory that finds every capacity statement and no second-source statement is seen as such.
- **Behaviours on a throwaway bank (live, capped):** the recorded fixtures of two companies are retained through Atlas's real retain path into `atlas-conformance-<random>` with the research bank's template, then checked, each check naming the documentation sentence or spec decision it tests:
  1. every retained section has facts or is reported empty; none is lost silently (ticket 03);
  2. the filer is one entity across its documents, and a company named in another's document is the same entity (ticket 04);
  3. a call transcript's analyst question is not stored as the company's statement (ticket 04);
  4. facts carry a layer label where the text names a layer, and a recall filtered by it returns only those (ticket 05);
  5. after consolidation an observation exists in the company's scope and one in the theme's scope whose sources lie in both companies' documents (ticket 06);
  6. a recall with `prefer_observations` returns no fact an observation in the same answer was built from; `query_timestamp` moves recency; a larger `max_tokens` returns more (ticket 07);
  7. a pointer placed by its chunk lands on the sentence the fact came from (ticket 08);
  8. the entity lookup returns the other company's section that names the filer (ticket 09);
  9. a reflect cites only memories that resolve to sections, and a refresh of a model reads no other model (ticket 10);
  10. every citation of a recall resolves; none is broken.
- A check whose behaviour is not on the branch yet reports `pending: ticket NN` and does not fail the run; `--strict` makes pending a failure (the release uses it).
- `scripts/memory-conformance.sh [--rehearse] [--only known-answers|behaviours] [--strict]`: the live suite's two locks; hard caps on retain operations and LLM requests enforced by the counting proxies; the bank is always deleted. `--rehearse` runs every check against the fakes and is what CI runs.
- `docs/runbooks.md`: "Memory conformance"; `docs/evaluation-methodology.md` names it as the precondition of a benchmark run.

**From tickets 01 and 02:** ticket 02's listings of observation scopes and entities are hand-written fixtures (`tests/fixtures/hindsight-handwritten/`); ticket 01 recorded both (`observation_scopes/09-list-scopes.json`, `entities/03-list-entities.json`) and their shapes agree. This ticket replaces the hand-written fixtures with the recordings in the fake and deletes the folder. The health read and the probe report (`atlas.retention.health`, `atlas.research.probes`) are there to build on.

**Blocked by:** 01, 02

**Status:** done

- [x] The rehearsal passes in CI: each check either passes against the fake or reports `pending` with its ticket; `--strict` fails while any is pending.
- [x] The known-answers file validates at load (every section it names is checked to exist when run against an Atlas; an unknown one is an error, not a miss), holds at least 20 answers, and each quotes its sentence.
- [x] The report lists, per check, the promise tested, the evidence (IDs, counts) and the verdict.
- [x] The caps abort a run that exceeds them; the throwaway bank is deleted on success, failure and interrupt.
- [x] Runbook entry; the methodology's precondition; `AGENTS.md` line.
