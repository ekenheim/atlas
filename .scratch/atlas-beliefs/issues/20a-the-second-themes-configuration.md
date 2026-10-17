# 20a: The second theme's configuration (memory and packaging, the SEC-path seeds)

Type: build
Status: ready-for-agent
Parent: [20](20-the-second-theme.md)

## Why

Ticket 20 needs a second theme Atlas can ingest and a session can research. Six of the seed list's twelve companies (`docs/research/seed-list-memory-packaging.md`, "Recommended seed list") need manual imports or a new adapter; seven are reachable through the `sec` path today. This ticket configures the theme with those seven, so the nightly ingest can fill the archive while the non-SEC paths wait for their own decisions.

## Decisions (the lead's, 2026-10-18; the owner delegated scope)

- **Theme slug `memory-packaging`**, in `configs/themes/ai-infrastructure.yaml` beside `photonics` (one universe file, two themes). Title "Memory and advanced packaging for AI". The description follows photonics' shape: trace AI demand to HBM and NAND, to the bonders, test and inspection tools, OSATs, package substrates and materials; ask who chokes each layer and what would relieve it.
- **Seeds, the SEC path only:** Micron (CIK 723125), SK hynix (CIK 2120882, a foreign private issuer: `sec_forms` F-1, 424B4, 6-K, 20-F), SanDisk (CIK 2023554), ASE Technology (20-F/6-K), Camtek (20-F/6-K), FormFactor, Amkor. Look each CIK up in the seed list's tables (it gives them, read 2026-10-05), never from memory. Comments carry the LEI and listing as the photonics entries do. Bump the universe `version`.
- **Layers are per theme.** The seed list's nine layers (`memory-dram`, `memory-nand`, `controller`, `bond-equipment`, `process-control`, `test`, `osat`, `package-substrate`, `package-materials`) become valid company layers (`atlas.companies.Layer` widened to both themes' names; `package-substrate` stays distinct from photonics' `substrate`). A theme may list its `layers` in the config; validate that a theme's companies use one of its theme's layers when the theme lists them. **The Claim layer taxonomy (`atlas.claims.LAYERS`, `LAYER_TERMS`) and the research bank template stay photonics-only**: the role pipeline and the research bank are photonics' (bulk retention is off; a session's Facts carry steps, not layers). Record this in `docs/decisions.md` ("The second theme: layers per theme, the Claim taxonomy stays photonics'").
- **TradingView symbols** from the seed list's "Unverified" forms (`NASDAQ:MU`, `NASDAQ:SKHY`, `NASDAQ:SNDK`, `NYSE:ASX`, `NASDAQ:CAMT`, `NASDAQ:FORM`, `NASDAQ:AMKR`), commented as unverified; the calendar job confirms them (a symbol its answer leaves out is no error).
- **Out of scope:** Samsung (the NSM's ESEF `html_link`, a separate ticket), Kioxia, BESI, ASMPT, Ibiden, Ajinomoto (manual imports), DART and JPX paths, the home-ops ingest CronJob (the lead's), any Hindsight bank or template change.

## What to build

1. The config entries and theme; `atlas.companies` validation for per-theme layers.
2. Anything that assumes one theme and breaks with two: check the theme map, the dossier, the MCP tools that take a theme (`companies`, `prior_work`, `newest_documents`, `signal_leads`, `upcoming_reports`), `next_issue`, the settle job's benchmark (the call's theme's researched companies only) and the archive-signal scan's theme on leads. Fix only what is wrong for a second theme, each with a test.
3. Tests first: a config test that the universe loads with both themes and refuses a company whose layer is not its theme's; an integration test that `atlas companies seed` creates the seven and `GET /api/v1/themes` lists both themes; and a test for each fix in step 2.

## Acceptance criteria

- [ ] The universe loads with both themes; the seven seeds have CIKs from the seed list, `source_path: sec`, layers of the new theme.
- [ ] A company with a layer outside its theme's list is refused at load, with a message naming both.
- [ ] `GET /api/v1/themes` and `GET /api/v1/themes/{id}/map` work for `memory-packaging` (an empty theme map is fine).
- [ ] Every theme-taking MCP tool and the settle benchmark keep photonics' answers unchanged and answer for the second theme by its own companies.
- [ ] `docs/decisions.md` entry; AGENTS.md's `atlas companies seed` line names both themes.
