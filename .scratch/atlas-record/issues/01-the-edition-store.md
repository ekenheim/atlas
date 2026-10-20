# The edition store: a ledger parsed and kept insert-only

Type: task
Status: open
Blocked by: none

## What to build

### The parser

`atlas.record.parse` is pure. It takes an artifact page (HTML bytes) and returns its ledger:
1. Take every `<pre>` in the page.
2. Strip its tags and unescape HTML entities.
3. Strip a leading ```` ```json ```` fence and a trailing ```` ``` ```` fence.
4. Return the first block that `json.loads` to an object with `chokepoints` (a theme ledger) or `board` (the council's).

Never key on `id="ledger"`; two fixtures lack it (`tests/fixtures/artifacts/2026-10-19/MANIFEST.md`).

The theme and council ledgers get typed models. They tolerate missing optional fields (`earliest_evidence`, `consensus`, `council_answers`, `notes`) and keep unknown ones.

### The table

`ledger_edition` is an insert-only table, added by a migration. Each row holds:
- the theme slug (`council` for the council), `as_of` and `edition`;
- the raw page, in the archive (content-addressed);
- the parsed ledger as JSONB, or null with `parse_error`;
- `source`: `drop_box` with the commit SHA, or `manual`;
- `read_at`.

The page's hash is unique, so importing the same bytes again changes nothing. A second edition with the same theme and `as_of` but different bytes is kept and marked `same_as_of_differs`: the task rewrote its edition the same day.

### Import

Two ways in, both audited as `edition.imported`:
- `uv run atlas record import --theme <slug> --file <page.html> [--source manual]`.
- `POST /api/v1/editions`, the same body as a file upload. Ticket 03's pull uses it.

### Reads

- `GET /api/v1/editions?theme=`.
- `GET /api/v1/editions/{id}`: the parsed ledger, the parse error, and a link to the page in the archive.

## Tests

- Parsing each of the eight fixtures gives its theme, `as_of`, edition and the counts in the manifest.
- A page with no ledger is a parse error, not an exception.
- Importing a fixture twice stores one row.
- The routes and the CLI are tested at their seams, on real Postgres.

## Done when

- [ ] The eight fixtures import.
- [ ] Production holds them: once this is released, the lead imports them with `--source manual`.
