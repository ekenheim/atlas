# 11: Re-parse already-ingested Source Versions with the current parser

**What to build:** Fix 04's parser `text-v3` applies to new versions only; production's pilot filings keep their `text-v2` parse, and the re-run lost a true Lumentum `capacity_constrained` quote to a page-break artifact (`quote_mismatch`). Build the re-parse that fix 04's decision entry designs (`docs/decisions.md`, "Page artifacts and parser version `text-v3` (pilot fix 04)", the numbered design at the end), as a separate parse record, never an overwrite:
1. An insert-only `source_parse` table keyed by (Source Version, parser version): content hash, parsed object URI, status, language, page anchors. The `source_version` parse columns stay the parse the version was recorded with. Migration `0046` (down_revision `0045`).
2. A `reparse` job (not pausable; no LLM) that reads the archived raw bytes (never refetches), parses with the current parser, archives the text and inserts the row; idempotent and audited. `uv run atlas ledger reparse [--company slug] [--parser-version text-v3]` enqueues it for the versions whose recorded parse is older; `GET /api/v1/source-versions/{id}` lists the version's parses.
3. **Readers choose the parse explicitly.** The Investigator's extraction reads the current parse (the `source_parse` row for the current parser version when it exists, else the recorded one) and each Claim, Assertion and Evidence span records which parse it quotes (`parser_version` on the Assertion; a span is only ever checked against the parse it was made on). Existing Assertions stay bound to the recorded parse. The source viewer shows the parse an Assertion belongs to.
4. **Memory and triage stay on the recorded parse in this ticket** (retaining the new parse is a `reprocess` under the Codex budget: design it in the decision entry, don't build it). Say clearly in the decision entry which readers use which parse after this ticket.
Keep the change additive: nothing that reads the recorded parse today may change behaviour when no `source_parse` row exists.

**Blocked by:** None

**Status:** ready-for-agent

- [ ] Integration tests at the CLI and API seams: a `text-v2` version re-parsed to `text-v3` gets a `source_parse` row with a different content hash, the recorded parse is unchanged, running it again inserts nothing, and the audit trail records it.
- [ ] An extraction on a re-parsed version quotes the new parse and its Assertion records `text-v3`; an older Assertion's span still verifies against `text-v2`.
- [ ] Decision entry and runbook section; `docs/data-model.md` §2.4 updated.
