# Map: Atlas as the record of the scheduled research

Label: wayfinder:map

## Destination

Every Monday, Atlas holds that week's eight editions (seven themes and the council) unchanged. For each edition, its pages show:
- what changed since the last edition;
- what was rewritten;
- which quotes the sources bear out;
- which predictions are due, met or missed.

The research pipeline is retired. The spec is `spec.md`.

## Notes

- **Approved:** the owner, 2026-10-20 ("I approve the project change"). The decision and its evidence are in `docs/adr/0004-the-scheduled-tasks-research-atlas-keeps-the-record.md` and `docs/decisions.md` (2026-10-20).
- **Who decides:** as before, the lead plans and decides. The owner's own acts are:
  - merging home-ops PRs;
  - creating repositories, tokens and claude.ai tasks;
  - opening any external route;
  - fetch policy beyond the existing override (the spec's open question 1);
  - every financial bet.
- **Atlas is LAN-only.** Its one route is `envoy-internal`, and there is no public DNS record. On 2026-10-20 the lead had told the owner that Atlas was open to the internet without authentication; that was wrong. Authentication matters only if an external route is opened (ticket 08).
- **The in-cluster token test stays off.** No artifact test runs with the in-cluster `claude setup-token` token unless the owner says "run the artifact test". The permission classifier refused it as credential exploration on 2026-10-20.
- **Editions are lost if not kept.** Each artifact is republished in place every week. Until the collector runs (ticket 03), the lead snapshots the eight artifacts by hand after each Monday's council and commits them under `tests/fixtures/artifacts/<as_of>/` or imports them. The first such Monday is 2026-10-26.
- **Owner-side items still open from 2026-10-19:**
  - Remove Gmail from all tasks.
  - Remove GitHub from the seven research tasks. It stays on the collector only.
  - Paste the "Additional rules", "Council questions" and "early candidate" blocks into the photonics, memory, robotics and power prompts.
  - Remove the Serenity skill from the account's scope.
- **Release order:**
  1. Ticket 00 (the freeze; home-ops only).
  2. Tickets 01, 02, 04 and 05 in one release, with 03's pull as soon as the spike answers.
  3. Ticket 06.
  4. Ticket 07, after two Mondays.

## Decisions so far

<!-- one line per closed ticket -->
- The pivot, 2026-10-20: the scheduled tasks research, and Atlas keeps the record (ADR 0004). The scorecard (ticket 29a) is retired, and the prospective record replaces it.

## Not yet specified

- A monthly "what did we miss" check against Serenity's published calls, run in a supervised session and never in a scheduled task. Parked until the record has a month of editions.
- Whether a theme task should read its own previous edition from the drop box rather than from the artifact list. Proposed to the owner only if the rewrite check shows drift.
