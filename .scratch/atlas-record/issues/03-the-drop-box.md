# The drop box: a collector task writes, Atlas pulls

Type: research (spike), then task
Status: ready-for-human
Blocked by: none

## Why

Atlas is reachable only on the LAN: its one HTTPRoute is on `envoy-internal`, and public DNS has no record for it. A claude.ai task therefore cannot call Atlas. The task sandbox's egress proxy also refused ordinary sites.

Connectors run outside the sandbox, so a private GitHub repository can serve as a drop box: the task writes to it through the GitHub connector, and Atlas reads from it outbound. See the spec, "How the ledgers reach Atlas".

## The spike (the lead, with two acts by the owner)

1. **The owner** creates:
   - a private repository, suggested name `ekenheim/atlas-ledgers` (not `atlas`, so that repo's CI and fixtures stay clean);
   - a fine-grained token with read-only Contents access to that repository alone, stored as a Secret in the `development` namespace.
2. **The lead** writes the collector task's prompt (done: `../collector-prompt.md`). The task:
   1. reads the eight artifacts (URLs in the spec) with the Artifact tool;
   2. commits each page as `<theme>/<as_of>.html`;
   3. commits each page's ledger, extracted as in ticket 01, as `<theme>/<as_of>.json`;
   4. commits `runs/<date>.md`, listing each artifact's URL, version, size, `as_of` and edition, and any artifact it could not read, with the reason;
   5. never edits a file already in the repository;
   6. then stops.
3. **The owner** creates the task in claude.ai with only the GitHub connector attached, scheduled for Mondays 10:00 Stockholm, and runs it once by hand.
4. **Find out and record the answer here:**
   - Did the connector write the files?
   - Through which tool: `create_or_update_file`, `push_files`, or a commit through Bash if the task's repository is cloned?
   - Are the pages byte-identical to an `Artifact read` with `path: index.html`?

If the connector cannot write, the fallback goes to the owner as a decision: an external route for `POST /api/v1/editions` alone, behind a bearer token (ticket 08).

## Then the pull

Build a `pull_editions` job. It makes no LLM call and is not pausable.
- It lists the repository's commits since the last one it read, through the GitHub REST API. The token comes from `ATLAS_LEDGER_REPO_TOKEN`, the repository from `ATLAS_LEDGER_REPO`.
- It imports each new `.html` file through ticket 01's path, with `source: drop_box` and the commit SHA.
- `atlas worker` enqueues it daily from `ATLAS_LEDGER_PULL_AT`: 10:30 Stockholm, given as UTC. Empty means never.
- A theme missing for the week is recorded as `edition_missing`, not as an error.

## Until the collector runs

After each Monday's council, starting 2026-10-26, the lead snapshots the eight artifacts by hand (`Artifact read` with `path: index.html` for each URL) and imports them with `--source manual`. A week missed is an edition lost.

## Done when

- [ ] The spike's answer is recorded here.
- [ ] The collector has run on a Monday, and Atlas has pulled its commit on production.
