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
| 2, InP substrates | 58% → **73%** | **0: no card** | — | 20% → 60% in Facts | 5 → 0 (22 in Facts) | 9.7 min |
| 3, module assembly | 69% → **76%** | 19 | fails (6 of 30) | 30% → **60%** | 1 → **7** (+5 in Facts) | 10.7 min |
| 4, DSP and drivers | 39% → **75%** | 19 | fails (2 of 34) | 10% → **70%** | 1 → **6** (+7 in Facts) | 44 min wall (≈25 queued) |
| 5, coherent optics | 66% → 59% (88% true to quote; 29% off-question) | 21 | fails (5 of 32) | 10% → 33% | 5 → **6** (+4 in Facts) | 15.5 min |
| **Pooled** | 63% → **72%** | 82 | fails on 4 of 4 cards (17 of 130) | 22% → **63%** | 16 → **27** of 145 (72 in Facts or on a card) | 10–16 min |

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
