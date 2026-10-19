# Experiments ledger

What Atlas has tried, how each attempt was measured, and what came of it, failures and abandoned approaches included. It is an index: each entry links to the record that holds the detail. Numbers come from the linked records. "(session record, not in repo)" marks a fact known only from the lead's working session; treat it as unverified until a repo record carries it.

## Start here

- **Version:** 0.5.3 (tag `v0.5.3`). **Plan under test:** the argument plan (`"plan": "argument"`: Scout, then six Readers, one per argument step, then Skeptic ∥ Financial Analyst, then the Editor; `docs/decisions.md`, "The argument plan"). The default plan, which extracts Claims, is still the API default.
- **Last verdict:** the five-question pilot on 0.4.6 (2026-10-07) failed. Pooled Claim precision was 63%, baseline coverage 22%, machine-reviewed edge precision 57%, and the trust gate failed in 4 of 5 investigations. A researcher's hour found 144 true facts; the cards carried 16 of them (`docs/pilot-report.md`).
- **Since then:** question 1 on 0.5.3's argument plan had 78% Fact precision (133 of 170), 23 saved-work statements, baseline coverage 9 of 10 and 13 minutes of latency. Its trust gate still fails, on 4 of 34 statements (`.scratch/pilot/results.md`, "The argument plan on 0.5.3"). Questions 2 to 5 and the pooled verdict are below.
- **Open questions:**
  - How to stop narrow overstatements the finding judge misses.
  - The feedstock and equipment half of a question: non-seed companies, and web sources that aren't Evidence.
  - Whether Memory (Hindsight) earns its place as a reading index or should become memory over time (pilot-review ticket 13).
  - Retiring the default plan.
- **Where the detail lives:**
  - `docs/implementation-log.md`: per-ticket files, tests and results.
  - `docs/decisions.md`: the rules and why.
  - `.scratch/pilot/results.md`: every pilot run, reviewed.
  - `docs/pilot-report.md`: the 0.4.6 verdict.
  - `docs/research/`: measurements and studies.
  - `.scratch/<effort>/issues/` and each effort's `map.md`: the tickets. The pilot map is `.scratch/atlas-pilot-review/map.md`.
  - `.scratch/live-runs/`: raw run data, **local only, not in git**.

## Ledger

Each entry gives the date, the version or ticket, the hypothesis, the change and how it was measured, the result, the outcome, and links. Outcomes: **kept**, **reverted**, **parked**, **superseded**, **open**.

### Pilot runs: the measured trajectory (question 1 unless noted)

| Date | Version | Shape | Result | Link |
|---|---|---|---|---|
| 2026-09-30 | 0.2.1 | Default plan, first run | 0 Claims and no card. The leads were junk (Swedish locale, dictionary pages). One Investigator spent all 25 documents. The Investigator returned `{"claims": []}` 4 times. | results.md, "Investigation 1" |
| 2026-09-30 | 0.2.3 | After pilot fixes 01–05 | 14 Claims, 10 right; 7 of 8 machine-reviewed edges right; 2 min; 105k tokens | results.md, "re-run" |
| 2026-10-01 | 0.2.5 | After fixes 06–12 | Precision 60% (6 of 10); coverage 20%; 159k tokens; 5.5 min. Does not meet the bar. | results.md, "third run" |
| 2026-10-01 | 0.2.5 | Breadth runs of Q2–5, unreviewed | 10–31 Claims accepted per run. The party check was the biggest loss. Layer tags followed the question rather than the quote. | results.md, "Breadth runs" |
| 2026-10-02 | 0.3.0 | Memory-directed reading (pointers, multi-hop) | 89 Claims, but **no card**: the Editor was cut off at its 4,096-token output cap (fixed in memory-quality 16) | results.md, "fourth and fifth runs" |
| 2026-10-02 | 0.3.1 | Same, with the card fixed | 182 Claims; precision 84.6% strict; coverage 5 of 10; 1.59M tokens; **35 min**. Trust gate fails: 9 of 11 findings say more than their Claims. 28.5% of tokens went to schema repairs. | results.md, same |
| 2026-10-07 | 0.4.6 | **Frozen five-question verdict** | **Fail.** Precision 39–69%; coverage 10–40%; latency 21–26 min; 4.81M tokens; reviewer kappa 0.77–0.86; 364 of 364 quotes verbatim | `docs/pilot-report.md` |
| 2026-10-07 | 0.5.0 | Argument plan, first run | 15 of 27 Reader calls quarantined; 2 Facts. Readers ran serially (session record, not in repo: fixed by three worker containers, a home-ops PR). | log, "The Reader after its first production runs" |
| 2026-10-07 | 0.5.1 | Reader reads MiniMax's flat form | 7 good Facts in ~8 min; 12 of 59 Reader calls still quarantined | same |
| 2026-10-07 | 0.5.2 | Wrapped arguments, several Facts per call, 24 calls | 138 Facts, but 4 of 6 steps `unknown`: one merged statement per step was dropped for one bad clause | log, "The argument's Editor writes several statements per step" |
| 2026-10-07/08 | 0.5.3 | Several statements per step, all source facts in recall | Q1: precision 78%; 23 saved-work statements; coverage 9 of 10; researcher facts 8 on the card + 7 in Facts only (0.4.6: 4); 13 min; 1.58M tokens; trust gate fails on 4 of 34 | results.md, "Question 1 on 0.5.3" |

### Extraction: Claims and the Investigator

- **2026-09-30, pilot-fixes 03.**
  - Hypothesis: the Investigator proposes nothing because the prompt and the predicates can't express a filer's own statements.
  - Measured: a replay of the pilot's extraction across prompt variants, live on MiniMax (25 calls).
  - Result: v2 accepted 3 Claims and v3 with the 13-predicate whitelist accepted 8. The new predicates alone raised v2 from 3 to 4. Cost was about 1.75× the tokens.
  - **Kept**: v3 and the four company-level bottleneck predicates.
  - Links: `docs/research/investigator-yield.md`.
- **2026-09-30, pilot-fixes 01, 09, 10.**
  - Changes: split the document budget across seeds; take the layer from the quote and use one clause; spread the passage budget.
  - **Kept.** Fixes 13–20 were later **superseded** by the memory-directed reading tickets.
  - Links: decisions.md entries of 2026-09-30.
- **2026-10-01, memory-directed reading 02, 08, 09.**
  - Changes: the filer may be the unnamed party; a typographic fold for quote matching; a layer only when the quote names one; a company-level constraint needs no named product.
  - Result: on 0.3.1, 87 of 182 Claims carried no layer, the layer rule working.
  - **Kept.**
- **2026-10-02, pilot-fixes 26.**
  - Problem: 29 of 72 Investigator calls added extra fields, and 28.5% of tokens went to repairs.
  - Change: unknown fields are ignored, not repaired.
  - **Kept.**
- **2026-10-02, pilot-fixes 22.** An analyst's words are not the company's statement. **Kept.**
- **2026-10-07, pilot-fixes 35.**
  - Hypothesis: hedged, conditional or development language becomes positive Claims.
  - Change: `unrealised_refusal` rejects such a Claim as `not_stated_as_fact`.
  - Measured on the 364 labelled 0.4.6 Claims: rejects 24 of 47 wrong, 1 of 228 right, 1 of 89 off-question.
  - **Kept.**
- **2026-10-07, pilot-fixes 39.**
  - Problem: `owns` was read from an investment or a warrant, with the direction reversed.
  - Measured: 0 of 3 wrong-direction Claims refused before the fix, 3 of 3 after; the 10 others still pass.
  - **Kept.**
- **Open after the verdict:**
  - 23: plans and ramps read as fact.
  - 36: reading follows the theme's story, not the question.
  - 38: a Claim can't hold a figure or a regulatory status. The argument plan's Facts answer this one.
  - Tickets in `.scratch/atlas-pilot-fixes/issues/`.

### The Reader and the argument plan (bottleneck-argument effort)

- **2026-10-07, tickets 01–06.**
  - Hypothesis: one agent choosing its own reading, like the researcher's hour, beats fixed passage selection; and a card built as the steps of an argument, holding Facts with quantity, period and status, says what the verdict found missing.
  - Changes:
    - 01: archive term search.
    - 02: Facts (migration 0099).
    - 03: the Reader loop (migration 0100).
    - 04: the finding judge.
    - 05: the argument plan.
    - 06: the scorer, `.scratch/tools/pilot_score.py`.
  - **Kept**, under test. Ticket 06's box stays open: its automatic coverage is not within one hit of the reviewers'.
  - Links: `.scratch/atlas-bottleneck-argument/`; decisions.md, "The reading agent" and "The argument plan".
- **MiniMax answer formats, 0.5.1–0.5.3.**
  - Formats seen: arguments beside `action`, under wrapper keys, or inside `action`; JSON fenced; malformed quantities; unknown steps.
  - Change: normalized in `ReaderAction`'s validator and in the caller's `_json_text`.
  - Measured: re-validating the saved quarantines, 34 of 60 attempts passed before and 58 of 60 after (0.5.2). Session record, not in repo: 66 of 69 after 0.5.3.
  - **Kept.**
- **Several Facts per call and a 24-call bound** (0.5.2). This took Facts from 7 to 138. **Kept.**
- **Several statements per step** (0.5.3, `editor-argument.v2`).
  - Hypothesis: one merged statement per step is dropped whole for one bad clause.
  - Measured: Q1 kept 34 statements and dropped 2; every step stated.
  - **Kept.**
- **The Reader's recall: raw facts (0.5.0) versus observations with every source fact (0.5.3).**
  - 0.5.0 chose raw facts on ticket 40's measurement (below). That measurement missed the source-facts truncation.
  - **Reverted** in 0.5.3.

### Trust gate: grounding and the finding judge

- **2026-10-02, pilot-fixes 21.**
  - Hypothesis: findings add names and figures their Claims lack.
  - Change: a lexical grounding check, with one reground call.
  - **Kept.** It did not stop misstatement of tense or status (verdict: the gate failed in 4 of 5).
- **2026-10-07, pilot-fixes 33.**
  - Problem: the grounding check dropped faithful findings on punctuation and claim labels.
  - Measured: 37 of 37 dropped findings failed before the fix and 2 of 37 after; the 2 left are true failures of the verbatim rule. Kept findings: 0 of 18 failed, before and after.
  - **Kept.**
- **2026-10-07, bottleneck-argument 04: the finding judge.**
  - v1 caught 9 of 9 misstatements but flagged 5 of 9 supported findings.
  - v2 added a materiality rule; one vote still flagged 2–3 of 9.
  - **Two votes, both must say misstated: caught 8 of 9, flagged 1 of 9.**
  - **Kept** (`ATLAS_FINDING_JUDGE_VOTES` 2).
  - On 0.5.3 Q1 it missed all 4 overstatements the reviewers found (a scope widened, "800G" added, a Fact the statement doesn't cite used, fiscal versus calendar year). **Open.**
  - Links: decisions.md, "Findings checked for meaning".

### Memory: Hindsight retain, consolidation, recall, mental models, embeddings

- **2026-09-28: extraction bake-off.**
  - MiniMax-M3 with thinking off against M2.7.
  - Result: M3 found 16 of 17 expected facts against 15, put 4 of 5 quotes verbatim against 0 of 4, and was 2–3× faster.
  - **Kept M3.**
  - Links: `docs/research/extraction-bakeoff.md`.
- **2026-09-30: triage audits.**
  - Measured: 3 misses in 97 skipped sections (about 3%).
  - Changes: windows 6 → 10; exhibit indexes go to the role (`triage-rules-v2`); rubric `triage.v3`.
  - **Kept.** No later audit is recorded measuring the change.
  - Links: decisions.md, "Triage tuning from the first live audits".
- **2026-10-01/02: Memory as the reading index** (memory-directed reading 01, 05–07; memory-quality 07–09, 13).
  - Hypothesis: recall pointers choose what to read.
  - Result on 0.3.1: Claims went from 10 to 182 and companies read from 2 to 6.
  - Then the verdict: pointers sent Investigators to the theme's laser makers whatever the question's layer (pilot-fixes 36).
  - **Superseded in practice** by the Reader, which searches by term and recalls on its own. The code remains for the default plan.
- **2026-10-02: memory-quality 04, 05, 06.**
  - Changes: retain context and entities; a mission with an ignore list and attribution; a `layer` label; one observation scope per theme.
  - Measured on 3 sections (`docs/research/mission-comparison.md`): boilerplate no longer extracted; attribution added; 1 wrong layer label found and fixed.
  - **Kept.**
- **2026-10-02: memory-quality 14, the conformance check.**
  - Before-measure: known-answer recall 0.22 at both 10 and 50 (23 answers).
  - First live behaviours run (2026-10-03): 4 passed, 6 failed. Three of the failures were the check's own bugs; thresholds were set (entity coverage 95%, unverified citations 5%).
  - On 0.4.6: recall at 10 was **0.08** and at 50 **0.12**. The owner ran the verdict anyway.
  - **Kept** as a gate. Links: decisions.md, "The conformance check after its first live run".
- **2026-10-02: memory-quality 15, the reranker and the embedding query prefix.**
  - Measured offline only: every live traced recall failed with a 413, because the reranker batch is limited to 256 and Hindsight sends 300 candidates.
  - Result: MiniLM is not clearly worse than bge or Qwen3-Reranker on 11 answers; the query instruction was neutral (23 pairs better, 26 worse).
  - **Parked**: no change. The chain ends in `rrf`. Ticket 11, the owner's server settings, is ready-for-human.
  - Links: `docs/research/retrieval-options.md`.
- **2026-10-02/03: memory-quality 19, 20, 23: Atlas decides when to consolidate.**
  - Changes: auto-consolidation off; a round budget; the settings pinned in template 1.5.0, among them `consolidation_source_facts_max_tokens` 4096 and 256 per observation.
  - **Kept.**
  - Links: `docs/research/hindsight-bank-settings.md`.
- **2026-10-04/05: pilot-review 21, the consolidation model and batch size.**
  - Measured: blind review of 30 observations per run, comparing luna, MiniMax-M3 and qwen3.8 27B on the 5090, each at batch 8 and 16.
  - Result:
    - Every model is faithful; luna synthesises most.
    - **58–83% of observations rest on one fact**, and almost none spans companies: the setup is the problem, not the model.
    - Batch 16 loses quality: keep 8.
    - qwen3.8-flash on worker4 was too slow and was stopped.
  - Decisions:
    - ChatGPT is out of consolidation: about 4% of the 5 h window per round.
    - The backlog ran on the 5090, then on M3 first with the 5090 as fallback.
    - M3 had been consolidating with thinking on through LiteLLM's `drop_params`, at 14.7k thinking tokens per call; fixed in home-ops #7242.
  - Observations in production are therefore mixed.
  - **Open**: the setup change is not specified; the plan is to re-consolidate on a frontier model later.
- **2026-10-06: pilot-review 22, 23.**
  - Problems: 89 parsed versions never reached Memory and health didn't show it; 82% of Coherent's pointers led to documents before the intake window.
  - Changes: a coverage gap that shows; `atlas memory retire` for sections before the window.
  - **Kept.**
- **2026-10-07: pilot-fixes 40, the recall token cap.**
  - Hypothesis: the 8,192-token pointer cap is the gap.
  - Measured: recall at 10 was 0.08 at both 8,192 and 16,000 tokens. Raw facts only reached 10 of 17 answer sections.
  - Concluded then that "observations crowd out filings"; the Reader switched to raw facts.
  - **Superseded** by the next entry.
- **2026-10-07: source facts truncated.**
  - Cause: `include.source_facts` defaults to 4,096 tokens, so lower-ranked observations lose their sources.
  - Measured on one investigation-style recall: 45 of 113 source facts at the default and 117 of 117 at `max_tokens: -1`. Answer sections reached went from **5 to 9 of 17**.
  - **Kept** (gateway, 0.5.3).
  - Links: decisions.md, "Every observation's source facts in a recall".
- **2026-10-08: consolidation review (read-only).**
  - Hypothesis: the thin cross-company observations are a prompt or model issue.
  - Method: read-only review of the bank's prompt preview, the upstream source of Hindsight 0.10.2 (`consolidator.py`, `prompts.py`, `config.py`) and a 60-observation sample (plus 700 for the cross-company count).
  - Result:
    - `observations_mission` replaces only the default mission line; the nine built-in rules stay in every call.
    - `consolidation_llm_parallelism` 4 cuts batches to 8, 5, 3, 2, 1, 1, 1, 1 (about 20 calls a 100-fact round, mean about 5 facts, not 8).
    - Each call sees one section of one document plus about 5 existing observations, so cross-company observations hardly form: 0 of 60, 0 to 1% of 700, whatever the model.
    - MiniMax-M3 copied a sibling observation's figures into the text without linking its facts in 4 of 30 rewrites; qwen3.8 27B did so 0 times in its sample.
  - Outcome: template **1.6.0** (`consolidation_llm_parallelism: 1`), three docs statements corrected, server-level caps proposed to the owner. Cross-company beliefs are reflect's and the mental models'.
  - Open: re-consolidation and the model choice, measured on a throwaway bank first; the effect of full batches on rounds and quota.
  - Links: decisions.md, "The bank template 1.6.0".
- **Not pursued:**
  - News through TradingView into Memory (memory-quality 17, 18): **wontfix**, because news makes no Claim and no edge.
  - Embedding-model candidates the owner raised on 2026-10-07 (EmbeddingGemma, an arXiv paper, a 3090 to serve them): discussed only (session record, not in repo). **Parked.**
  - Hindsight's audit log (`audit_log_enabled`) in the bank template: deferred, because a template change applies at deploy (session record, not in repo).

### Discovery and the Scout

- **2026-09-30, pilot-fixes 02, 08, 12.**
  - Problem: junk leads (locale, dictionary pages).
  - Changes: `language=en`; lead ranking against the query (v2 and v3 demote the companies' own pages and profile sites); EDGAR full-text search as a second channel.
  - **Kept.**
- **2026-10-01, memory-directed reading 04.** Only specific filing phrases are searched, and a filer needs a kept hit. **Kept.**
- **Verdict (0.4.6):**
  - The Scout kept weak or one-channel leads in all 5 runs. Examples: SEO market-report pages; only SEC hits; one query of ten on the question's subject.
  - **Open**: pilot-fixes 37.
  - Web sources (trade press, TrendForce, USGS) are leads, never Evidence. That is the main gap against the researcher's hour (0.5.3 Q1).

### Skeptic and counterevidence

- **2026-09-30, pilot-fixes 06.**
  - Problem: the Skeptic read nothing (an empty plan).
  - Change: a deterministic fallback to the latest 10-K and 10-Q.
  - Then: 29 accepted items, none a real contradiction (results.md, third run).
- **2026-10-01, memory-directed reading 03, 07.**
  - Changes: split contradiction from bear context; the Skeptic reads where Memory points.
  - Result on 0.3.1: it checked only 2 of 6 companies.
  - **Kept**, with the gap left open (pilot-fixes 25).
- **Argument plan:**
  - The Skeptic is a Reader. On 0.5.3 Q1 its 23 counter-Facts all challenged constraint Facts and mostly supported them.
  - **Open**: counterevidence quality is next-session priority 3.

### Roles: the answer schema in the prompt (8 October)

- **Hypothesis:** MiniMax-M3 through LiteLLM never sees the schema Atlas sends only as `response_format`, so it answers in its own shape; putting the schema in the system message cuts repairs and quarantines.
- **Measured (two live calls, 2026-10-08):** a strict schema `{answer: string}` with the user asking for an extra field and a code fence: the reply was a fenced JSON object with `country`, `capital`, `note` and no `answer` (`response_format` ignored). A forced tool call (`tools` + `tool_choice`): no `tool_calls`, fenced content (ignored too).
- **Result:** the schema goes in the system message ("Answer format", `ANSWER_FORMAT_VERSION` 1, recorded per role call), `response_format` kept, normalizers kept. **Kept**, effect **not yet measured**: compare repairs and quarantines per role call on the next pilot with the 0.5.4 runs (calls with `answer_format_version` 0).
- **Cost:** about 1,620 tokens on each Reader and Skeptic call, about 227,000 input tokens an investigation at 140 Reader calls.

### Relationships review

- **Ticket 09's rule, owner-delegated 2026-10-02.**
  - Rule: every Evidence Claim right means approve; every one wrong means reject.
  - Applied after the verdict: 87 approved, 29 rejected, 100 left.
  - Machine-reviewed edge precision was 57% against a bar of 90%: 43 right, 5 wrong, 23 off-question. **Open.**
  - Links: `docs/pilot-report.md`, "The edges".

### Measurement method

- **Verdict criteria:** pilot-review 02.
- **Archive-search baseline:** BM25; pilot-review 03; memory-directed reading 10 drops near-duplicates.
- **Blind double review:**
  - Two reviewers per chunk; the lead adjudicates.
  - On the default plan's Claims at 0.4.6: kappa 0.77–0.86.
  - On the argument plan's Facts: 0.85 on 0.5.3 Q1.
- **The researcher's hour:** one agent with web search and the archive's term search, under an hour per question; 144 cited facts across the five questions. The same answers are reused for 0.5.3 so the comparison is exact.
- **Lead tools** (in `.scratch/tools/`):
  - `pilot_runs.py` and `pilot_score.py`.
  - `pilot_regression.py`: re-checks the reviewed data. Session record, not in repo: it reports 1 of 228 right refused and 24 of 47 wrong.
  - `argument_review_pack.py` and `finding_judge_eval.py`.
  - `argument_labels.py` and `argument_regression.py`: the standing regression set from the 0.5.3 reviews. The labels (`tests/fixtures/pilot-0.5.3-argument/labels.json`, committed: 853 Fact verdicts, 130 statement verdicts, 50 counter-Facts, no quotes) are built from the local review folders; the script joins them with the local quotes and runs each Fact and statement check that exists (a check not yet in the code is `skipped`). Tested on a synthetic folder in `tests/unit/test_argument_labels.py`; see `docs/evaluation-methodology.md` §10.
- **Not done:**
  - The live gold evaluation (pilot-review 11).
  - The §15 demo (pilot-review 12).
  - The held-out answer key: Serenity's flagged names and dates, which the owner provides.

### CI/CD and infrastructure

- **2026-10-03: the suite once per commit, in parallel.**
  - Change: pytest-xdist with 8 workers and template databases.
  - Result: 1,643 tests in 316 s against 1,807 s serial. A release is one CI run (~8 min) plus the publish.
  - **Kept.**
- **2026-10-06/07: Renovate's first run broke CI.**
  - Cause: 13 branches in 2 minutes. Runners had no resource requests, so 9 runs timed out. 4 failed for real reasons (TypeScript 7, ESLint 10, postgres:18, a Python 3.14 segfault) and were closed.
  - Changes:
    - Staged CI: `static` on GitHub's runners, `suite` on the scale set.
    - Main gated on `ci`; a `changes` job skips tracker-only pushes.
    - The scale set capped at 3 runners of 4 CPU / 8 GiB each.
    - Renovate limited to 3 branches; Python minor and major updates off.
    - Release SBOM, provenance and attestation.
  - **Kept.**
  - Links: log, "CI/CD: staged CI..."; `docs/deployment.md`, "CI".
- **Session record, not in repo:**
  - Renovate's Mend-hosted app stalled for hours; ticking "rebase all" on the Dependency Dashboard woke it.
  - A Windows `git worktree prune` removed WSL-registered worktrees.

### Models and providers

- **MiniMax-M3, thinking off,** is the role and retain model (bake-off above; LiteLLM probe in `docs/research/litellm-dev-probe.md`).
  - Its 5 h window is 8M tokens; 0.5.3 Q4 waited on it.
  - Retains can be routed to a MiniMax extractor by metadata (memory-directed reading 11; `ATLAS_RETAIN_EXTRACTOR`).
- **Consolidation:**
  - ChatGPT (luna) was dropped for quota.
  - qwen3.8 27B on the owner's 5090 consolidated the backlog for a time.
  - Now M3 first, with the 5090 as fallback (pilot-review 21).
  - The 5090 is not Atlas infrastructure: it is the owner's PC, and dedicated hardware is sought.
- **Claude for consolidation:** rejected by the owner on cost (session record, not in repo).
- **A frontier model for the Editor and the judge:** next-session priority 6, not tried.

## 0.5.3 argument plan, questions 2–5

Each question's section in `.scratch/pilot/results.md` has the detail. Facts are judged twice blind; precision counts a wrong status as wrong.

| Question | Precision, 0.4.6 → 0.5.3 | Saved work | Trust gate | Baseline coverage | Researcher's facts on the card | Latency |
|---|---|---|---|---|---|---|
| 1, laser chips | 67% → **78%** | 23 | fails (4 of 34) | 40% → **90%** | 4 → **8** (+7 in Facts) | 13.3 min |
| 2, InP substrates | 58% → **72%** | **0: no card** | — | 20% → 60% in Facts | 5 → 0 (22 in Facts) | 9.7 min |
| 3, module assembly | 69% → **76%** | 19 | fails (6 of 30) | 30% → **60%** | 1 → **7** (+5 in Facts) | 10.7 min |
| 4, DSP and drivers | 39% → **75%** | 19 | fails (2 of 34) | 10% → **70%** | 1 → **6** (+7 in Facts) | 44 min wall (≈25 queued) |
| 5, coherent optics | 66% → 59% (88% true to quote; 29% off-question) | 21 | fails (5 of 32) | 10% → 33% | 5 → **6** (+4 in Facts) | 15.5 min |
| **Pooled** | 63% → **71%** | 82 | fails on 4 of 4 cards (17 of 130) | 22% → **63%** | 16 → **27** of 145 (72 in Facts or on a card) | 10–16 min |

Findings so far:
- **Reading is fixed:** most of the researcher's facts are now among the Facts (Q2: 22 of 32).
- **What still fails:**
  - The trust gate: the judge misses narrow overstatements (ticket 08, an Editor reference leaking into a statement).
  - Status labels: about two-thirds of Q2's wrong Facts.
  - Counterevidence that supports the claim it is attached to.
  - Customer concentration (Q3) and web sources (every question).
- **Defect:** a failed optional Financial Analyst cancels the Editor, so Q2 has no card (`.scratch/atlas-bottleneck-argument/issues/07`).
- **Review method:** one blind reviewer invented fact IDs (correct 8-character prefixes); that chunk was re-reviewed. Checking IDs against the pack is now part of the tally.

**Verdict:** the plan still fails the bar: no question reaches 80% precision, and the trust gate fails on every card. It beats 0.4.6 on every measure, so by the rule agreed with the owner it replaces the default plan. Question 5's card argued the datacom InP story rather than the coherent/DCI question, so the reading follows the theme, not the question. Ranked failures and the detail are in `.scratch/pilot/results.md`, "The argument plan on 0.5.3: pooled against the 0.4.6 verdict".

## 0.5.4 (the Fable round) on questions 1, 2 and 5

| Question | Precision 0.5.3 → 0.5.4 | Saved work | Trust gate | Baseline coverage | Researcher's facts on the card | Tokens in |
|---|---|---|---|---|---|---|
| 1, laser chips | 78% → 78% | 23 → 19 | 4/34 → 3/27 | 90% → 60% | 8 → 7 | 1.50M → 1.91M |
| 2, InP substrates | 72% → **84.5%** | 0 → **18** (the card is back) | – → 4/25 | 60% (Facts) → 70% | 0 → **8** | 1.55M → 1.90M |
| 5, coherent optics | 59% → 64% | 21 → 25 | 5/32 → 4/30 | 33% → **11%** | 6 → 6 | 1.49M → 1.89M (budget hit) |

**Kept:**
- The status refusals and `reader.v3`: precision is up.
- Ticket 07: question 2 has a card.
- The counter-judge: no step is falsely disputed.

**Not yet effective:** the grounding rules and the judge (v3, two votes, rule `any`). The trust-gate failure rate is unchanged at 14%. The checks drop more statements, and the ones that pass still fail about as often.

**Open:**
- The run budget: 0.5.4 needs about 1.9M tokens a question, and question 5 hit 2M.
- Reading that follows the question: question 5 is still 27% off-question, with 11% coverage.
- Periods in code.
- An invalidation step that looks for counterevidence.

Detail: `.scratch/pilot/results.md`, "0.5.4 against 0.5.3".

## 0.5.6 (Fable round 3) on questions 4 and 5

| Question | Precision | True to quote | Off-question | Trust gate | Coverage | Researcher's facts on the card | Tokens in |
|---|---|---|---|---|---|---|---|
| 4, DSP and drivers | 75% → 65% | 88% | 22% | fails 4/29 | 70% | 6 → **9** | 1.93M |
| 5, coherent optics | 64% → 58% | **95%** | 36% | fails 4/28 | 11% → **56%** | 6 → **9** | 1.93M |

**Kept:** one Fact per span (107 and 96 Facts, against 138 and 200), the lease heartbeat (no duplicate Editor), the basis check (4 statements dropped each, against 7–18). Question 5 answers its own question for the first time (coverage 11% → 56%).

**Not solved:** off-question Facts. Precision fell on both questions, and almost entirely through Facts that are true but off-topic (copper AEC DSPs, photodetectors, the datacom EML story on a coherent question). False Facts are at 5–12%. The question-parts planner (round 2) binds the Readers' searches to the question's terms, but the Readers still record what the passages hold.

**Measurement note:** the bar's "precision" counts off-question as wrong. Separating faithfulness (true to the quote) from on-question share would show 0.5.6 at 88–95% faithful and 64–78% on-question. Proposed to the owner (ticket 02 revision).

## 2026-10-12: a frontier model as the finding judge (pilot-review ticket 25)

- **Hypothesis:** the trust gate's 13–14% failure rate is the judge's model, not its prompt (`finding_judge.v4`, unchanged in every run below).
- **Method:** `.scratch/tools/finding_judge_eval.py --argument` on the 130 labelled 0.5.3 argument statements (17 misstated, 113 sound; the reviewers' labels), one vote per statement, the basis check applied as the Editor's task applies it; through LiteLLM with the `atlas-eval` key (home-ops-upgrade #7479, #7481). Stage 1: all 17 misstated plus 30 sound; stage 2: the other 83 sound. Bridge errors (LiteLLM's `chatgpt/` provider: HTTP 500 "Unknown items in responses API response", about 7% of calls) and my own rate-limit collisions were retried until every statement but one had a verdict. Reports: `.scratch/live-runs/20261012-judge-*`.
- **Result (full set):**

| Judge model | Caught of 17 misstated | Flagged of 113 sound | Bases the code check turned |
|---|---|---|---|
| MiniMax-M3 (production) | 5 | 11 | 4 of 47 (stage 1) |
| gpt-5.6-luna (`chatgpt`) | 11 | 26 (1 unjudged) | 0 |
| gpt-6-astra (`frontier-pool`) | 14 | 24 | 0 |

  Stage 1 alone (the same 47 statements for all three): MiniMax 5 and 4 of 30; luna 11 and 4 of 30; astra 14 and 3 of 30. Luna's two runs agree on 39 of 42 shared verdicts.
- **Reading the flags:** a sample of astra's 18 stage-2 flags shows most are the gate's own kinds of overstatement that the blind reviewers let pass (a dropped "probably", "will be" written as "is", two sources of different dates merged without saying so, an inference added to a faithful quote); a few are pedantic because the judge sees the quote without its context (a pronoun's referent). So the "flagged" column overstates false positives, and the regression labels have lenient passes that need a second adjudication before they are used as a target.
- **Not needed:** the `chatgpt/` aliases answered non-streaming calls with the JSON schema and the MiniMax extra body, so the streaming branch (`ATLAS_LLM_ROLE_STREAM_MODELS`) stays in reserve.
- **Decision:** the finding judge moves to luna (the cheap alias; twice MiniMax's catch rate, a different model family from the writer); astra is parked for the judge (three more catches at flagship rate). A frontier Editor is not measured here; the owner's direction the same afternoon moved the writing to Claude sessions (`.scratch/atlas-beliefs/spec.md`). Ships with the per-role override (`ATLAS_LLM_ROLE_MODELS`, branch `ticket/25-per-role-model`, CI green); production needs `chatgpt` on the `atlas` key (home-ops) and a transient classification of the bridge 500 so the caller retries it.

## 2026-10-12: the proof sessions, a Claude session with Atlas's tools against the pipeline

- **Hypothesis:** a strong model researching with Atlas's tools and gates (archive search as of a date, Facts at verbatim spans, recall as a tool) beats the MiniMax role pipeline on the pilot's own measures.
- **Method:** two Opus sessions with the `atlas-research` skill, question 2 as of today and the AXT replay as of 2025-08-31 (pilot-review ticket 26); the pipeline's argument plan on the AXT question the same day; blind double review of every Fact, card review, baseline, researcher's-hour comparison. Detail in `.scratch/pilot/results.md`, "The proof sessions".
- **Result:** Facts 100% and 93% right (pipeline 75% on the same question; the pilot 58 to 84%); 19 of the researcher's 32 facts on the card (pipeline 8); AXT reached from the seeds and the early signal stated in substance; a tenth of the tokens. The trust gate is not better (8% and 29% of statements fail) because no judge was applied to the session's statements; the step statuses err on the cautious side.
- **Kept:** the revision of the method (`.scratch/atlas-beliefs/spec.md`); the skill; the pipeline as bulk mode. **Next:** luna as the judge on the session's statements, a rule for `disputed`, then Beliefs and Issues.

## 2026-10-12: the closing measure, question 2 as a session with the judge loop (Beliefs ticket 09)

- **Hypothesis:** Atlas's judge on a session's statements, before the card, brings the trust gate at or below the pipeline's rate without losing the proof's precision.
- **Method:** the proof's question 2 session repeated on v0.6.1 through the real routes (session, judge, relate, Beliefs, Issues); the same review. Detail: `.scratch/pilot/results.md`, "The closing measure".
- **Result:** trust gate 29% → 9% of statements (pipeline 16%); step statuses 6 of 6 warranted; Beliefs 2, judged proven by the lead; Fact precision 100% → 87% (four statements carrying a context clause or dropping a hedge); the card smaller (12 statements against 35) because judging took about a fifth of the call bound.
- **Kept:** the judge loop and the `disputed` rule. **Next:** the Fact statement held to its quote in the skill; a longer call bound with the judge on; atomic Beliefs (one proposition) in the skill's rule; the tool's `--run` fix (done).

## 2026-10-15: question 2 through the Atlas MCP server only (Beliefs tickets 15 and 11)

- **Hypothesis:** the MCP server can replace the tool script without loss, and ticket 11's skill rules (a Fact's statement held to its quote; one proposition per Belief; a bound of ~150) lift Fact precision to 95% or more with the trust gate at or below 10%.
- **Method:** a headless Opus `claude -p` session with only the Atlas MCP server, on v0.6.3, the closing measure's question, seeds and as-of; the same blind double review. Detail: `.scratch/pilot/results.md`, "The MCP session".
- **Result:** the MCP surface works (120 calls, counted by Atlas, no as-of leak); precision 92% (87% before; 3 context-clause Facts); trust gate 4% (9% before); researcher's facts on the card 15 (11 before); 11 Beliefs, all grounded, 6 compound.
- **Kept:** the MCP server as the tool surface; the skill rules. **Next:** move the rules into code: judge a Fact's statement at `record_fact`, the thesis, and a Belief's statement (with atomicity) before it is proposed.

## 2026-10-15: the speaker beside a transcript quote for the finding judge (atlas-beliefs ticket 25)

- **Hypothesis:** the Editor re-run's thesis and control step were judged misstated because the judge could not see who spoke a transcript quote; sending the paragraph label's name, title and firm beside the quote (as claim metadata, never in the quote's text) removes those flags without making the judge miss real misstatements or flag more supported statements.
- **Method:** `.scratch/tools/finding_judge_eval.py --argument` on the 130 labelled statements (one vote, the judge's model `chatgpt`, `finding_judge.v4` unchanged), once without and once with `--speakers` (each transcript Fact's label read from the running Atlas; the basis check with the speaker's texts as metadata, as production). Ship only if caught does not fall and flagged does not rise by more than one.
- **Result (2026-10-15, the lead):** without the speaker, run 1: caught 10 of 17, flagged 28 of 113; the same, run 2 (the noise): caught 11, flagged 32, 17 verdicts different from run 1; with the speaker (112 of 130 statements carried one): caught 10, flagged 33, 9 verdicts different from run 1 and 14 from run 2. None of the six statements newly flagged in the speaker run was flagged for its speaker (dropped hedges, joined periods, an unquoted year). The rule "flagged rises by at most one" was tighter than the judge's own spread (about ±4 flags and 17 flips between identical runs), so it was judged against the noise band instead: the speaker's change is inside it, and smaller than a rerun's.
- **Kept:** the speaker beside the quote, no prompt change. A finding-judge change is measured against at least two runs of the baseline from now on; a single before/after pair is noise at this sample size.

## 2026-10-15: archive signals, the AXT replay and precision (Beliefs ticket 18) - not yet measured

- **Hypothesis:** a general cue vocabulary scored sentence by sentence (`configs/discovery/signals.yaml`, scorer `signals-v1`, config version 1) ranks the sentence AXT's management said on 2025-07-31 ("the market is just growing too fast to be adequately serviced by just two players") in the top five of all hits over the 12 companies' documents public by 2025-08-31, and at least 12 of the top 20 hits over the last quarter of the archive are real bottleneck cues. The vocabulary is not fitted to AXT (a known winner; the bias is studying only winners): the second measure, across the whole universe, is what guards against it.
- **Method:** `uv run python scripts/signal_replay.py --as-of 2025-08-31T00:00:00Z --top 20 --expect "growing too fast"` against production (read-only, no model call), and the same with `--as-of <now> --since <a quarter ago>` for the precision count, judged by the lead from each hit's sentence and context. Detail: `docs/runbooks.md`, "Archive signals".
- **Result:** not run. The scorer and the replay script exist and were exercised only on hand-written sentences and three synthetic filings (the replay reproduces the nightly job's ranking on them: 4 hits from 3 documents, one repeat dropped); nothing was measured on the production archive, and no weight has been tuned. The lead runs both measures.
- **Kept:** the scorer, the job, the leads and the Scout's step 2, pending the two measures. **Next:** record both results here; if the AXT sentence is outside the top five or fewer than 12 of 20 are real, change the config once per recorded cause (not per sentence) and measure again.

## 2026-10-15: archive signals measured (Beliefs ticket 18)

- **Hypothesis:** a general vocabulary of bottleneck cues, scored sentence by sentence over the archive with no LLM, ranks an early signal like AXT's highly before the market prices it, and its top hits are mostly real cues.
- **Method:** `scripts/signal_replay.py` against production (read-only, the job's own scorer): as of 2025-08-31 over the 12 companies (750 documents); and as of 2026-10-15 over documents public since 2026-07-15, the top 20 judged by the lead.
- **Result:** AXT's 31 July 2025 "the market is just growing too fast to be adequately serviced by just two players" ranks **1st of 293 hits**; "new orders on pretty much a daily basis" 7th; the 1 May "the other players both cannot keep up with capacity" 10th. The last quarter's top 20: **11 real cues of 20** (bar 12): misses are negations scored as cues ("not sold out", "no capacity constraints"), cost pass-through read as pricing power, generic backlog and capacity lines; one call held 8 of the 20. Caveat: "two players" is in the vocabulary because the case studies (AXT among them) named it; the rank comes from general phrases, but a held-out case would test more.
- **Kept:** the scan. **Next:** ticket 27 (negation, pass-through, generic lines, a per-document cap), then both replays again.

## 2026-10-15: archive signals, precision rules (Beliefs ticket 27) - replays not yet run

- **Hypothesis:** four general rules answer the causes of the 9 misses in the quarter's top 20 without moving the AXT sentence out of the top five: a negator that governs a cue cancels it; a price rise that recovers a cost or is set by contract or named in a margin line is not pricing power; "record backlog" and "adding capacity" alone need a figure or a second family; one document's hits past the third come after the other documents' in the ranked read. Scorer `signals-v2`, config version 2. No phrase comes from the early-signal case studies.
- **Method:** (a) unit tests with literal hand-worked scores for each rule, both ways; (b) an offline comparison, not the replay: the old and the new scorer over the 838 parsed texts the two replays cached (`.scratch/live-runs/signal-replay-cache/`; form and source type guessed from the text, so scores of 10-K sections and speakers are approximate) and the diff of what stopped being a hit; (c) the lead's replays against production: `scripts/signal_replay.py --as-of 2025-08-31T00:00:00Z --top 20 --expect "just two players"` and `--as-of 2026-10-15T00:00:00Z --since 2026-07-15T00:00:00Z --top 20`, judged by the lead.
- **Result:** (b) 448 old hits, 414 new. The AXT 31 July sentence is still first at 6.25 and "new orders on pretty much a daily basis" moves from 18th to 15th of the cached archive. Gone from the quarter's old top 20: "they are not sold out", Coherent's "record backlog", Lumentum's gross-margin line, the two STMicroelectronics input-cost lines and the two Ciena price-increase lines (7 of the 9 misses); Fabrinet's "no capacity constraints" (ranks 3 and 4 of the AXT replay) are gone too. Kept as real: "not taking orders" (the phrase carries its own negation). With the cap of 3 the AXT Q2 2026 call keeps its first three hits (the first drops from 5.06 to 4.69 because its "add capacity" is now a generic phrase) and the quarter's next hits take the places of the other five; in the cached quarter those next ones are a mix (Ciena's "demand outstripping supply", Coherent's investing-in-capacity line with its "industry-wide shortage", AXT export-permit sentences, and generic supplier-dependence lines such as "we rely on sole-source suppliers" scoring 2.4 to 2.7, which the old ranking had below 20th). By my count that is 11 to 14 real of the new top 20 depending on how strictly a permit or dependence line is read, so box 2 is not claimed. (c) not run.
- **Kept:** the four rules, pending (c). **Next:** the lead runs (c) and records both here. If precision is under 12, the recorded cause to look at is the generic supplier-dependence lines (few_suppliers: "sole-source", "limited number of suppliers" in a business section) and analyst questions restated by management, not another phrase.


## 2026-10-15: archive signals after ticket 27 (signals-v2)

- **Method:** the same two replays with the ticket-27 scorer (negation scope including a negator inside the cue, pass-through pricing dropped, generic lines below threshold, at most 3 hits of one document in a ranked read); the lead judged the top 20 strictly.
- **Result:** the AXT replay as of 2025-08-31: the 31 July sentence still **1st** (276 hits); the negated hits (Fabrinet's "no capacity constraints") gone; 7 of the top 10 are AXT or Lumentum constraint statements before the price move. The last quarter's top 20: **10 of 20** real cues (11 to 12 if the permit lines count): the negations and pass-through pricing are gone, but the per-document cap let 10-K supplier-dependence boilerplate ("single source or a limited number of suppliers", "we rely on sole-source suppliers") into the top 20, and one Lumentum 10-K sentence appears twice.
- **Kept:** ticket 27 (strictly better on the errors it targeted). **Next:** ticket 27b, supplier-dependence boilerplate in filings down-weighted and an identical sentence counted once per document, then the precision replay again; the bar (12 of 20) is not yet met.

## 2026-10-16: archive signals after ticket 27b (signals-v3)

- **Method:** the same two replays as ticket 27's, with the 27b scorer (supplier-dependence boilerplate in a periodic filing ×0.3 unless it names an input, a figure or a constraint in progress; one identical sentence counted once per document): `scripts/signal_replay.py --as-of 2025-08-31T00:00:00Z --top 20 --expect "just two players"` (`.scratch/live-runs/signal-replay-axt-v3/`) and `--as-of 2026-10-15T00:00:00Z --since 2026-07-15T00:00:00Z --top 20` (`.scratch/live-runs/signal-precision-q-v3/`), read-only against production; the top 20 judged strictly by the lead.
- **Result:** the AXT replay: the 31 July sentence still **1st** (6.25; 268 hits, 39 repeats dropped); AXT and Lumentum constraint statements hold 6 of the top 8. The last quarter's top 20: **12 of 20** real cues by the strict reading (AXT's demand-outpacing-capacity lines ×3, Ciena's "demand outstripping supply", AAOI's demand ahead of capacity to mid-2027 and "sold out", Lumentum's pump lasers "effectively sold out" and its 10-K allocation sentence, now once, MACOM's longer lead times, Coherent's InP capacity for increased demand, Ciena's backlog doubling to $10B covering 2027 ×2); 13 if "InP export permits represent the most significant challenge" counts. The three 10-K boilerplate lines and the repeated Lumentum sentence are gone. Misses: Fabrinet's 10-K supplier-risk language outside Item 1A ("may increase our expenses", "historically experienced supply shortages", "sole-source suppliers are small businesses": Items 1 and 7, so neither the Item 1A factor nor 27b's rule reaches them), AAOI's 10-Q inventory line, Coherent's "doubled our capacity" (expansion, not constraint), two permit history lines.
- **Kept:** ticket 27b; its bar (at least 12 of 20, AXT in the top five) is met, narrowly. **Next, if precision matters more:** generic risk wording ("historically", "may increase our expenses", "presents risks") in any section of a periodic filing, not only Item 1A.

## 2026-10-19: bake-off, robotics, Atlas's Watch against Claude with the Serenity skill

- **Hypothesis:** Atlas's architect Watch run finds robotics chokepoints at least as well as an open Claude Code session that has the Serenity skill and web tools, given the same brief.
- **How measured:** the same demand driver, as-of time and output shape for both (`.scratch/bakeoff/robotics-brief.md`), about 60 tool calls each. The arm's skill was pinned at `a56f706` with its self-update skipped. The lead checked the arm's quotes against the downloaded sources, and Atlas's run against its tool trace. Not blind: the owner pasted the answer in.
- **Result:** the arm won on evidence, 11 primary sources against 0 on any robotics step. Every quote checked was verbatim (P2, P3, P7, P9, P10, P11). Both put rare-earth magnets first and rejected harmonic reducers. Atlas got there without the skill's content, and the arm's primary evidence was its own reading. The cause is Atlas's reach: in a greenfield theme it can archive nothing outside its universe, and it refuses its own in-run leads as step evidence (`created_after_as_of`). Details: `.scratch/bakeoff/robotics-result.md`.
- **Parked → next:** widen `fetch_page` to any public primary page through the fetch gate; ingest an EDGAR hit during the run; fix the in-run as-of refusal. Then a robotics delta run and a power-equipment bake-off, round 2.
