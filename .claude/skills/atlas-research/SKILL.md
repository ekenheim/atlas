---
name: atlas-research
description: Research a supply-chain bottleneck question with Atlas's archive, Facts and Memory as tools, as of a date, and write the argument with Beliefs. Use when asked to run an Atlas research session on a theme question.
---

# Atlas research session

You are the researcher. Atlas is the evidence substrate: an archive of filings and call transcripts with the time each became public, a term search over it as of a date, a Fact ledger that only accepts verbatim quotes at archived spans, and Memory (Hindsight) as an index you may consult. Your job is a short, defensible answer to a bottleneck question, every statement resting on Facts you recorded, and a list of what you could not establish.

The tools are one script: `python .claude/skills/atlas-research/atlas_tools.py <command>` (run from the repo root; standard library only; every command prints JSON). Read its `--help` once.

## The question and the session's inputs

Your prompt gives: the **question** (verbatim), the **seed companies** (slugs), the **as-of time** (ISO), the **output folder**, whether **recall** is allowed, and a **call bound**. Start by listing the universe (`companies`): the question may need companies beyond the seeds, and a company's layer tells you where to look. Web search is not available in this session: the archive is the world.

**Open a session first and close it last.** Before the first search: `session open --question "<verbatim>" --as-of <T> --seeds slug,slug --model <your model>` prints the session id; pass it to every `record` as `--session <id>`. When the files below are written: `session close --id <id> --usage usage.json --card card.json --markdown card.md` (`card.json` is the `research_card` object of `investigation.json`, `usage.json` its `usage`). Atlas lists the session with its Facts and card on the sessions page. A session whose prompt names no question starts from `issue next --theme <theme>` (Atlas's frontier: use that Issue's title as the question); closing the session opens Issues for the card's open questions, and `issue open|narrow|complete` keep the frontier as you work.

## The method: the bottleneck test

Work the six steps of the argument, in this order, and record Facts under each (`--step`):

1. `constraint`: what exactly is constrained (which input, product or capacity), in what units, over what period, in the company's own words.
2. `demand_vs_supply`: the evidence that demand exceeds qualified supply (allocation, lead times, sold out, backlog, capacity ramps that lag).
3. `relief`: how fast capacity, a second source or a substitute can relieve it (new fabs, qualification timelines, alternative materials).
4. `control`: who controls the scarce capability (share, number of qualified suppliers, agreements, export permits).
5. `capture`: how the holder captures the economics (pricing, contracts, share of the bill of materials, customer concentration, financing).
6. `invalidation`: what would break the argument (new entrants, inventory, cancellations, substitutes, capacity additions). Look for it as hard as you looked for support; a step you tried to break and could not is worth more than one you did not test.

`context` is for a Fact that frames the question but belongs to no step. Decompose the question into 2 to 5 **parts** (snake_case keys) first and tag each Fact with the part it answers (`--part`); a Fact that answers none is off the question and should not be recorded.

## How to read

- `search --company <slug> --q "<terms>" --as-of <T>`: BM25 over that company's archived documents available by `T`; each hit is a passage with its Source Version, its offsets and the time it became public. Search every seed for each step with the step's own terms (the question's words first, then the vocabulary the filings use: "allocation", "lead time", "sold out", "qualified", "second source", "export permit"...). Search the non-seed companies whose layer the question names.
- `read --version <id> --start <n> --end <m> --as-of <T>`: the archived parsed text around a hit (a window of 2,000 to 6,000 characters; the tool refuses a version that became public after `T`). Read before you record: a passage's sentence often reads differently in context, and an analyst's question is not the company's statement.
- `recall --q "<question>" --as-of <T>` (only if your prompt allows it): what Memory holds across the theme, each memory with the archived sections it resolves to, filtered to those available by `T`. A memory is derived, never evidence: use it to find sections, then `read` them and record from the archived text.

## How to record a Fact

`record --version <id> --quote "<verbatim>" --step <step> --status <status> --statement "<one sentence>" --as-of <T> --part <key> [--period "..."] [--quantity <value> <unit> <metric>] [--epistemic ...] [--company <slug>] --session <id>`

- The **quote** is the archived text, verbatim, one speaker's words, long enough to carry its meaning (a sentence or two). The tool locates it in the parse (folding typographic quotes, dashes and spaces) and refuses a quote that occurs zero or several times; Atlas then checks the span, the status wording and the period against the document's date. A refusal comes back with its reason: fix the Fact, do not force it.
- The **statement** is one sentence in your words saying what the quote establishes, with the actor, the tense and the certainty the quote has: a plan stays a plan, "could" stays hedged, an analyst's words are the analyst's.
- The **status** is what the quote says: `in_effect` (it is so now), `planned` (management intends it), `in_development` (being built or qualified, not yet in production), `hedged` ("could", "may", risk-factor language), `regulatory` (a permit, licence, export control or rule), `reported_by_third_party` (someone other than the company says it about the company; `--epistemic third_party_report` for an analyst or a customer speaking on a call).
- The **period**, as the quote gives it ("fiscal 2026", "this calendar year", "by year-end"); Atlas resolves relative phrases against the document's date and the company's fiscal calendar. A **quantity** only when the number occurs in the quote.
- The subject is the document's company unless the quote is one company speaking about another (`--company` the one the Fact is about only when the quote names it as the actor).
- One Fact per span. Prefer the few Facts that carry the argument over many that repeat it. Record the counterevidence you find with the same care, under `invalidation` or the step it limits.

## How to judge a statement

Before a statement goes on the card, `judge --statement "<it>" --question "<verbatim>" --facts <id,id>` (its cited Facts only; add `--counter <id,id>` for the counterevidence). Atlas's judge compares it with the quotes. `supported`: keep it. `misstated`: it says more than its quotes (`beyond`, `kinds`, `unverified`); rewrite it yourself to what the quotes say, or drop it, and judge the rewrite. Never put a statement on the card, or in a Belief, that was not judged `supported`. The same `--run` id keeps the session's judge calls in one run.

## When a step is disputed

`relate --fact <id> --counter <id> --question "<verbatim>"` asks what a counterevidence Fact does to a Fact. A step is `disputed` only when a recorded counterevidence Fact is judged `contradicts` a cited Fact. `limits`, `dates` or `qualifies`: the step stays `supported` and the limitation goes into the statement (judge it again). Nothing established: `unknown`.

## Bounds

Stay within the call bound your prompt gives (searches, reads, recalls and records together). Stop reading a step once its Facts answer it or three searches with different terms found nothing new; record that it found nothing. Do not read a document whose `available_at` is after the as-of time, ever.

## The output

Write these files to the output folder (create it; JSON, UTF-8):

1. `investigation.json`:
   ```json
   {"id": "<session id you choose>", "question": "...", "status": "completed", "stop_reason": "answered",
    "created_at": "<ISO now>", "stopped_at": "<ISO now>", "as_of": "<T>", "seeds": ["slug", ...],
    "usage": {"calls": <n>, "searches": <n>, "reads": <n>, "recalls": <n>, "records": <n>, "refused": <n>},
    "tasks": [], "leads": [],
    "question_parts": [{"key": "...", "text": "...", "outcome": "answered|facts_only|unanswered"}],
    "research_card": {
      "steps": [{"step": "constraint", "asks": "<what this step must establish for this question>",
                 "status": "supported|disputed|unknown" ("found|nothing_found|unknown" for invalidation),
                 "statements": [{"statement": "<one point, in words the cited quotes support>",
                                 "facts": [{"fact_id": "...", "company_name": "...", "status": "...", "source_title": "..."}],
                                 "counterevidence": [{"fact_id": "...", "company_name": "...", "status": "...", "source_title": "..."}]}],
                 "facts": [<every Fact of this step as above>], "counterevidence": [<...>],
                 "unchecked": "<what you did not get to>"}],
      "open_questions": ["..."], "unsupported_findings": []}}
   ```
   A statement says only what its cited quotes say: no number, name, date or qualifier the quotes lack, no two dates merged, no plan written as a fact. Several short statements beat one long one. The `status`: `supported` when the step's Facts establish it and no counterevidence is judged `contradicts`, `disputed` only on a judged `contradicts` (above), `unknown` when you could not establish it.
2. `facts.json`: `{"items": [<GET /facts/{id} of every Fact you recorded>]}` (fetch each with `fact <id>`).
3. `beliefs.json`: your conclusions, proposed to Atlas through the tool (`belief propose --statement ... --step ... --as-of <T> --companies slug --session <id> --cite <fact_id> <valence|relation> load_bearing|context`, one `--cite` per citation; `belief cite` adds one, `belief supersede` replaces one) and kept in the file with the IDs Atlas returned. Atlas refuses a Belief without a load-bearing citation of positive valence, and the judgement is not yours to set: you propose it `unproven`, an author judges it. Your conclusions as atomic propositions, each `{"statement": "...", "step": "...", "companies": ["slug"], "judgement": "proven|disproven|unproven|undecidable", "confidence": 0.0-1.0, "as_of": "<T>", "cites": [{"fact_id": "...", "valence": -1.0..1.0, "weight": "load_bearing|context"}], "would_invalidate": "..."}`. One proposition per Belief; a Belief that a single load-bearing negative Fact would falsify should say so.
4. `card.md`: the argument for a reader: the thesis in one sentence, then each step with its status, its statements and the quote behind each (title, date, quote), then the counterevidence, then what remains open. No prose that a quote does not back.
5. `session.md`: what you searched (company, terms, hits), what you read, what was refused and why, and your own assessment of what the archive lacked.

Finish with a message of at most 200 words: Facts recorded by step, the thesis, the steps' statuses, and what you could not establish.
