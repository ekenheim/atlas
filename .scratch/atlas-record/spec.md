# Atlas as the record of the scheduled research

Status: ready-for-agent (tickets 01, 02, 04 to 06); 00, 03 and 07 need the owner's acts.
Approved by the owner on 2026-10-20 ("I approve the project change").

## Why

The three bake-offs of 2026-10-19 (`.scratch/bakeoff/`) put an open Claude session, researching on the open web, against Atlas's Chokepoint Watch on the same themes. The session read several times as many primary documents (15 to the Watch's 3 in aerospace) and named the chokepoints the Watch missed. Its quotes held up: 56 of 57 were verbatim in the bake-offs, and 13 of 13 in the council's two editions, one differing only by a comma. The owner then set up seven weekly or monthly claude.ai scheduled tasks, one per theme, and a council that reads them. Each publishes an artifact with a machine-readable ledger.

These tasks now do the research, so Atlas stops researching. Its job is the part a scheduled task cannot do for itself:
- keep what each edition said, unchanged;
- notice when a later edition rewrites an earlier one;
- check each quote against its source, and archive the source;
- settle the predictions when they fall due.

## What the scheduled tasks produce

| Theme | Artifact | Cadence | ID prefix |
|---|---|---|---|
| Photonics | https://claude.ai/artifact/GnQmgEjsvfpTcxCetkqy2Y | Mon 04:50 | `pho-` |
| Memory and Packaging | https://claude.ai/artifact/88Qn2HQn3JPmLM3sduzFLr | Mon 04:56 | `mem-` |
| Robotics | https://claude.ai/artifact/AqneSyMHifsh29UCGdtsfU | Mon 04:51 | `rob-` |
| Power Equipment | https://claude.ai/artifact/CXazK5byissDyBnExmP86F | Mon 04:45 | `pwr-` |
| Aerospace and Defence | https://claude.ai/artifact/KF3JXhEUiZZuhrkvW9dhob | Mon 04:55 | `aer-` |
| Nuclear Fuel and Reactors | https://claude.ai/artifact/JQ3JqTaBSb5CYZSqXR5bne | weekly | `nuc-` |
| Quantum | https://claude.ai/artifact/L6y14RYdjTSEUgcsr1VGoz | monthly | `qua-` |
| Council | https://claude.ai/artifact/2g6LeHkyCNjSmKu9JBbwUD | Mon 08:57 | `cst-`, `ccx-`, `cou-p` |

All times are Europe/Stockholm. Each artifact is republished in place, so last week's edition is gone unless something keeps it.

The ledger is JSON in a `<pre>` near the foot of the page. The snapshots of 2026-10-19 and what the parser must handle are in `tests/fixtures/artifacts/2026-10-19/MANIFEST.md`.

**A theme ledger has:**
- `theme`, `as_of` and `edition`;
- `chokepoints`, each with id, name, layer, status, verdicts, holders, kill criteria and `first_seen` (and, in the revised prompts, `earliest_evidence` and `consensus`);
- `predictions`, each with id, chokepoint, made, deadline, text, source type, state and the settlement fields;
- `rejected`, `cross_theme_hooks` and `council_answers`;
- `primary_sources`, each with who, doc, date, url and quote.

**The council's ledger has:** `board`, `stacks`, `contradictions`, `predictions`, `assignments`, `assignments_answered` and `subagents`. It cites theme IDs and carries no `primary_sources` of its own.

## How the ledgers reach Atlas

Atlas is reachable only on the LAN. Its one HTTPRoute is on `envoy-internal`, and public DNS has no record for it. A claude.ai task runs in Anthropic's cloud, so it cannot call Atlas. Its Bash tool's egress proxy also refused sites such as sec.gov during the nuclear run. Its connectors are a different path: they run on Anthropic's side, not through the sandbox.

**The design: a drop box on GitHub.**
1. A collector task (claude.ai, Mondays after the council, about 10:00) reads the eight artifacts.
2. It commits each page and its extracted ledger to a private repository through the GitHub connector, as `<theme>/<as_of>.html` and `<theme>/<as_of>.json`.
3. Atlas pulls the repository, outbound only, with a read-only fine-grained token.

Git's history is a second copy that a later edition cannot rewrite. Ticket 03 is the spike, and it confirms that the connector can write a file.

**Fallback (the owner's call, since it opens a hole):** an external route for one import endpoint, behind a bearer token.

**Never:** the owner's main PC as a relay, or the in-cluster `claude setup-token` test, unless the owner says "run the artifact test".

## What Atlas keeps and checks

**The edition.** Each pulled edition is stored insert-only: theme, `as_of`, edition number, the raw page, the parsed ledger, the commit it came from, and when Atlas read it. The same bytes again change nothing. A ledger that does not parse is recorded with its error.

**The rewrite check.** Each edition is compared with the theme's previous one, and every difference is recorded insert-only:
- a past prediction's text, deadline or range changed;
- a prediction removed;
- a chokepoint gone without `status: killed`;
- an ID reused for something else;
- `first_seen` or `earliest_evidence` moved later;
- a settled prediction un-settled.

Missing optional fields are no finding: four theme prompts predate `earliest_evidence`.

**The quotes.**
- Every primary source's URL is fetched once through the fetch gate and archived like any Source Version.
- The quote is then located in the parsed text with the typographic fold, which `atlas.mcp.locate` already uses.
- Each (URL, quote) pair has one result: `verified`, `not_found` (the page was read and the quote is not in it), or `unreachable` (gate block, robots, error), with the reason.
- The result records the document's tier. A verified quote in a Motley Fool or Investing.com transcript is verified against a third party's transcript, not the company's own words.
- The council's items are checked through the theme ledgers they cite.

**The predictions.** Each prediction becomes a record with its deadline:
- open, met, missed or lapsed;
- settled by the next edition's settlement fields, which are themselves quote-checked;
- shown on a due list.

Holders that resolve to a listed symbol may get price checkpoints through the existing calls job; holders that do not resolve are left unpriced, and that is no error.

**The pages.** Dark and terse, leading with the assessment:
- **Today:** the council's board, what changed since last week, rewrites found, quotes not verified, and predictions due.
- **A theme:** its chokepoints over editions, each with its quotes and their checks, and its predictions.
- **A chokepoint:** its history across editions.

Records sit one click deeper.

## What is retired

The research pipeline goes:
- investigations, Claims, Relationships and their review;
- the roles on MiniMax;
- triage, retention into Hindsight, consolidation and mental models;
- replay and evaluation;
- the Scout, Researcher, Skeptic, Scorecard and Watch agents and their CronJobs;
- the scorecard (ticket 29a).

The scorecard needs as-of research, and a scheduled task researches only the present. **The prospective record replaces it:** dated predictions that cannot be rewritten, settled against what happened.

**Order of retirement:**
1. Frozen first, by configuration (ticket 00).
2. Deleted from the code only after two Mondays on the new path, and after a backup of Postgres and the archive bucket (ticket 07, its own ADR).

The source ledger, the archive, the fetch gate and site register, parsing, the audit chain, calls and settlement, and the pages' shell stay.

## Non-goals

- Atlas does not research, rank or write theses.
- No trading, sizing or price targets.
- Nothing is published outside the owner's private pages.
- No change to the scheduled tasks' prompts beyond what ticket 03 needs (the collector), and anything the rewrite check shows to be necessary, proposed to the owner.

## Open questions for the owner

1. **The fetch gate's throughput** (ticket 04). The cited hosts are mostly not in the site register: Motley Fool, Investing.com, MHI, Micron, USGS, DOE, Urenco, ASX and others, at about 130 sources a week. Should a verify-only fetch of a cited URL be allowed when the site's terms are silent or permit personal use, under the existing override? Forbidden sites would stay forbidden and read `unreachable: forbidden`.
2. **The drop-box repository and its read-only token** (ticket 03): both are the owner's to create.
