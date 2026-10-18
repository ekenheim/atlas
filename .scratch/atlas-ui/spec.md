# Atlas UI: build spec (rounds 1 and 2)

This is the brief I build from. The reader is one owner, an independent investor who decides alone. Atlas does the research; he reads its assessment, checks its evidence and decides. Every page opens with Atlas's answer. Everything else sits one click deeper in a single Records fold. The fold is closed by default and renders nothing until it is opened.

Scope: `frontend/` only (Next.js 16 static export, React 19, strict TypeScript, hand-written `app/globals.css`). Neither round includes backend work. The backend items in §9 go to the lead as tickets.

---

## 1. Decisions

### 1.1 Where I yield to the director

| # | Director's point | What I build |
|---|---|---|
| Y1 | Whether a step argues for or against the thesis is structure, not state | The argument strip has four "for" cells (Constraint, Demand, Control, Capture), a divider, a small `Against` label, then two cells (Relief, Invalidation). All fills are neutral. The evidence groups For / Against / Context share one `--line` rule. `--warn` never means "against". |
| Y2 | One meaning per glyph | The bar always shows the step's **strongest proven** Belief. The thesis line names the weakest step in words: `Weakest step: Control · 60%`. |
| Y3 | The Belief vocabulary must cover the backend enum | `lib/status.ts` maps `proven`, `disproven`, `unproven`, `undecidable` and `superseded`. Flags and notices are modifiers (`Flagged`, `Confirmed`). There is no "Contested", because the backend has no such state. A unit test fails on any `schema.ts` enum value that has no mapping. |
| Y4 | An unchecked published thesis is a defect, and it is shown | `Not checked since correction` in `--warn` on the Today card, the Theme thesis line and the Hypothesis kicker. The gate fix goes to the lead (B1). |
| Y5 | No nav item without its page | `/record`, `/decide` and `/system` ship in round 1 as real read-only pages. The theme page's calls get a home on `/record` in the same round. |
| Y6 | Evidence dates are absolute | Three helpers: `activity()` (relative within 7 days), `evidenceDay()` (always absolute) and `due()` (`18 Nov · in 31 d`). |
| Y7 | Theme cards keep a fixed order | Cards follow theme config order, with starting themes last. Activity shows as a count of unseen dots, never as reordering. |
| Y8 | Text in evidence stays selectable | The row-as-link overlay goes only on list rows (step, Belief, issue, session, Today's change rows). It never covers a `<Quote>`, a headline or a statement in an evidence block. |
| Y9 | A reliable last-visit mark | When Today mounts, it reads the previous mark into memory (the mark drives the dots). It writes `now` on `visibilitychange → hidden`, or after 10 s visible. All of it is wrapped in try/catch. |
| Y10 | The leak guard checks rendered text | The main guard is an e2e regex over `main` with Records closed. A secondary source scan stays in the unit tests. |
| Y11 | No ticks on the bar | Plain track and fill, with the number beside it in tabular figures. |

The director's "missing" items are all in scope:
- Freshness markers (§5.3).
- Disproven and superseded first in "since you last looked" (§5.1).
- The thesis check state on Today (§5.1).
- Gate failure codes in plain words (§4, item 1).
- The expected range on Due rows (§3.5, `DueList`).
- A stated loading strategy (§5.1).
- A closed-by-default assertion on the Records fold (§7).
- An accessible argument strip (§3.5).

### 1.2 Where I hold (the director accepted each)

- **Decide lists only what waits on the owner:** gate blocks, open proposed updates and Beliefs to judge. Edge exceptions, Candidates and identity mappings are the lead's delegated work, so they appear as counts. An edge becomes an item only when it blocks a gate.
- **The confidence bar is continuous**, not five buckets. Production has seven values between 0.50 and 0.85, and buckets would erase the differences.
- **The judgement word stays beside the bar.** Agents now propose Beliefs and some are superseded, so lists mix judgements. Only words other than the default take colour.
- **Themes is a page of cards**, not a dropdown.
- **One site on every device.** A phone gets the same page in the same order, with Records closed. There is no separate phone product.
- **The global `th[scope="row"]` nowrap rule stays** for its roughly 25 key-value uses. `.th-wrap` goes on prediction measures, and Issues becomes a list.
- **No server-side "seen" mark.** Each device keeps its own mark, with a 7-day fallback.
- **No thesis parser.** The colon rule is only a fallback. The real fix is for drafting to emit the proposition separately (B4).

### 1.3 Decisions that orientation forced (neither side had pinned these down)

1. **There is no Issue page.** Rows that "link to the Issue" need one. Round 1 adds a minimal `app/issue/page.tsx` (`/issue?id=`), built from:
   - `GET /api/v1/issues/{id}`
   - `/edges`
   - `/produced`

   It shows the title, step, companies and status, the parent and sub-questions, and what the Issue produced (Facts and Beliefs) as rows. The producing session goes under Records.
2. **Hypotheses come in two kinds, and both stay supported.**
   - **Belief-backed** (`content.steps` present): six step rows, `What it rests on`, `What would falsify it`.
   - **Investigation-backed** (legacy, `findings` present): the `Findings` list sits above the fold where the step rows would be, followed by `Contradictions` and `Falsifiers` (both list names kept). There is no argument strip. On Today and Theme its card shows the thesis and the check word, and the strip is replaced by `n findings`.
3. **The nav must be a client component**, because `aria-current` needs the current path. `app/layout.tsx` stays a server component and renders `components/site-nav.tsx` (`"use client"`, `usePathname`).
4. **The Records fold** is `components/records-fold.tsx`:
   - A `<details className="reader-records">` whose `<summary>` reads `Records`, or `Records · 457 relationships, 104 candidates` when the counts are known.
   - Its children render only after the first `toggle` to open, and stay mounted afterwards.
   - It is closed by default and never opens on its own. A `#records` hash may open it, for deep links from System.
5. **The e2e literal `Proven 80%` is kept.** `<Status>` renders the word, then a space text node. `<Confidence>` renders an `aria-hidden` bar with no text, then the number. The row's text therefore reads exactly `Proven 80%`, and the specs that assert it are unchanged.
6. **Change-feed link names are kept** (`proven 85%: <statement>`, `Coherent: <step>`). Only their styling changes, so the theme and hypothesis specs that click them are unchanged.
7. **The gate banner keeps its accessible names:** region `Lifecycle and publication`, list `Failed checks`, button `Publish version N`, region `Owner review`. The banner moves to the top of the Hypothesis page when a decision is pending, so the specs no longer need to scroll to it.
8. **Isolated sessions** (`SessionSummary.isolated`, the scorecard's held-out runs) are excluded from the Agents line and the Agents counts. They appear later on Record, under the scorecard.

---

## 2. Navigation

`components/site-nav.tsx`, inside `<nav aria-label="Site">`, as one row:

```
Today   Themes   Record   Decide ●2                       System
```

| Item | Route | Current when the path starts with |
|---|---|---|
| Today | `/` | `/` exactly |
| Themes | `/themes/` | `/themes`, `/theme`, `/hypothesis`, `/belief`, `/company` |
| Record | `/record/` | `/record` |
| Decide | `/decide/` | `/decide` |
| System | `/system/` | everything else (`/memory`, `/issues`, `/issue`, `/relationships`, `/relationship`, `/exceptions`, `/workbench`, `/investigation`, `/sessions`, `/session`, `/beliefs`, `/hypotheses`, `/companies`, `/source`, `/version`) |

Behaviour:
- **No underlines.** The current item gets `aria-current="page"` and a 2px `--accent` bar under its label.
- **System** is pushed right with `margin-left: auto` and set in `--muted`.
- **The Decide badge** is a 6px `--warn` dot plus the count, shown only when the count is above 0.
  - It counts only Beliefs to judge and open proposed updates (two list calls). `/decide` itself also counts gate blocks, which take one `publish-gate` call per draft.
  - The count is cached for the tab in `sessionStorage` under try/catch, and dropped after any successful action.
  - A failed fetch shows no badge, never an error. The label is always present, so the nav never reshuffles.
- **Phone (< 40rem):** the same five items in one row at 0.9rem, about 44px tall (110px today). They need no wrapping at 390px.
- **Breadcrumb:** Hypothesis, Belief and Company pages carry one quiet crumb, the theme title, linking to `/theme?id=`.

---

## 3. Visual system

### 3.1 Tokens (added to `:root`; existing tokens kept)

```css
--text-2: #aab2bf;        /* secondary text: Atlas's statement of a Fact, meta that matters */
--raise-hover: #222733;   /* row hover/focus surface */
--quote-face: ui-serif, "Iowan Old Style", Georgia, serif;   /* the document's words; nothing downloaded */
--s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px; --s7: 48px;
--frame: 72rem;  --measure: 52rem;
```

Each colour has one meaning:

| Token | Means | Never |
|---|---|---|
| `--accent` | navigable (links, nav bar, focus ring) | state |
| `--ok` | verified, met, checked | "for the thesis" |
| `--warn` | needs attention: unproven, not yet checked, a decision pending, the Decide badge | "against the thesis" |
| `--gap` | wrong: disproven, flagged, overreaches, missed | decoration |
| `--muted` / `--text-2` | neutral, default | — |

### 3.2 Type scale (16px base, `system-ui`)

Body line-height is 1.5; heading line-height is 1.25.

| Size | Use |
|---|---|
| 0.75rem uppercase, 0.06em tracking, `--muted` | `.reader-label` section labels |
| 0.8rem | meta, captions, stat labels, status words |
| 0.85rem tabular | numbers, confidence figures, table meta columns |
| 0.9rem | secondary lines, nav on phone |
| 1rem | body, row titles |
| 1.0625rem `--quote-face` | verbatim quotes |
| 1.25rem | card thesis (Today, Themes) |
| 1.35rem | theme thesis |
| 1.75rem | page h1 |
| 1.5rem tabular | stat-strip values |

### 3.3 Layout

- **One frame:** `main { max-width: var(--frame) }`, with a 16px side gutter on a phone.
- **`.measure { max-width: var(--measure) }`** caps prose, quotes and headlines.
- **The `.reader` 52rem column is retired**, so every page shares one left edge.
- **Rows and strips** span the full frame.
- **Two-column and three-column bands** (Changed | Due; Falsifiers | Questions | Due) appear at ≥ 64rem and stack below that.

### 3.4 Global rule changes in `globals.css`

- `.ident, time { font-family: monospace }` (lines 138–139) becomes `.ident` only, so dates stop reading as code.
- Add `.th-wrap { white-space: normal; width: auto }` for row headers that hold prose (prediction measures).
- Nav links, `.reader-row` titles and change rows are not underlined. Underlines stay only on `p a` (links inside prose).
- Table meta and number columns are 0.85rem, `white-space: nowrap`, `font-variant-numeric: tabular-nums`, with numbers right-aligned. This applies on System pages.
- `details` gets a 120ms opacity fade on open, and none under `prefers-reduced-motion`.

### 3.5 Components (new in `frontend/components/` unless noted)

| Component | What it is |
|---|---|
| `site-nav.tsx` | §2. |
| `records-fold.tsx` | §1.3, item 4. |
| `status.tsx` → `<Status kind value modifiers? />` | A 6px dot plus a word at 0.8rem, coloured from `lib/status.ts`. Outlined pills survive only for actionable items on Decide. |
| `confidence.tsx` → `<Confidence value />` | A 56×4px track (`--line`) with a fill (`--text-2`), `aria-hidden`, followed by the number at 0.85rem tabular. Its accessible text is the number. |
| `quote.tsx` → `<Quote>` | The evidence block, in four lines. (1) Atlas's statement of the Fact: sans, 0.95rem, `--text-2`. (2) The verbatim quote: `--quote-face`, 1.0625rem, `--text`, typographic quote marks, a 2px `--line` left rule; selectable, with no overlay. (3) The caption: `Company · document · evidenceDay`, 0.8rem `--muted`, with an optional small `load-bearing` tag. (4) `Open in source →`: 0.9rem, `--accent`, a target at least 24px tall, linking through `routes.span`. Quotes over 600 characters are clamped, with a `Whole quote` toggle. |
| `argument-strip.tsx` → `<ArgumentStrip steps compact? />` | A `<ul aria-label="Argument">`: four for-cells, a divider, an `Against` label, then two against-cells. Each `<li>` holds the step label, the proven count and a mini `<Confidence>` for the strongest Belief. Its accessible name reads like `Relief, against the thesis: 3 proven, strongest 75%`. An empty step has a dashed border and an em dash, and its name reads `Control: nothing proven`. On a phone the cells sit in two rows: four, then two. |
| `step-rows.tsx` → `<StepRows>` | Each of the six steps is a `<section aria-labelledby>` named by the step (the e2e regions `Constraint`, `Relief`, … are kept). Inside is a `<details>` whose summary holds the step name, `n proven`, the strongest Belief's statement (body colour, 2-line clamp), `<Status>` + `<Confidence>`, the freshness marker (§5.3) and `+N more`. The body lists the step's Beliefs as `<li aria-label={statement}>` rows, each a row-link to `/belief`. A flagged or disproven Belief shows its status word first, in `--gap`. Against-steps carry `Against the thesis` in their summary. |
| `stat-strip.tsx` | The Memory page's `.mem-figures`, generalised to `.stat-strip`: 3–5 cells, each with a label, a 1.5rem value and a sub-line. Used on Record, Decide and System. |
| `due-list.tsx` → `<DueList calls predictions leads? limit=4 />` | Grouped rows such as `18 Nov · in 31 d · first checkpoint · 22 calls` and `30 Nov · in 43 d · 4 predictions · AXT Q3 revenue $66–70M`. A predictions row carries the first prediction's measure clause and expected range. Calls are grouped by `next_due.due_on` and predictions by `deadline`. Earnings rows (`tradingview_calendar` leads) render only when any exist. |
| `components/ui.tsx` `<Timestamp>` (changed) | Takes `mode: "activity" \| "evidence" \| "due" \| "exact"`. The default is `evidence`, so every existing use, System pages included, stops showing ISO strings in round 1. `exact` (ISO to the minute) is used only inside Records. |

### 3.6 Row-as-link

```css
.reader-row { position: relative; }
.reader-row > .row-title a::after { content: ""; position: absolute; inset: 0; }
.reader-row .row-secondary a { position: relative; z-index: 1; }   /* company links etc. */
.reader-row:hover, .reader-row:focus-within { background: var(--raise-hover); }
.reader-row:focus-within { outline: 2px solid var(--accent); outline-offset: -2px; }
```

The link's accessible name stays the statement, so `getByRole("link", { name })` keeps working. Rule Y8 limits this pattern to list rows.

---

## 4. Libraries (`frontend/lib/`)

1. **`status.ts`**: one vocabulary per object, each value with a `tone` (`ok | warn | gap | muted`).
   - **Belief judgement:**
     - `proven` → Proven (muted)
     - `unproven` → Unproven (warn)
     - `disproven` → Disproven (gap)
     - `undecidable` → Undecidable (warn)
     - status `superseded` → Superseded (muted, meta struck through)
     - modifiers: `open_flags > 0` → `Flagged` (gap); `open_notices > 0` → `Confirmed` (ok)
   - **Hypothesis lifecycle:** every backend status maps to Draft (muted), Published (ok), Needs decision (warn) or Retired (muted).
   - **Thesis check:**
     - `supported` → Checked (ok)
     - `misstated` → Overreaches (gap)
     - `null` or unjudged on a version whose kind is a correction → Not checked since correction (warn)
     - any other `null` → Not yet checked (warn)
   - **Gate failure codes, in plain words** (used on the Hypothesis banner and on Decide):
     - `relationship_not_approved` → `n links not yet approved`
     - `belief_not_proven` → `n Beliefs not proven`
     - `belief_flagged` → `n Beliefs flagged`
     - `thesis_misstated` → `Thesis overreaches its quotes`
     - missing falsifier → `No falsifier`
     - missing unresolved question → `No open question`
     - `thesis_unchecked` (once B1 lands) → `Thesis not checked`
     - any unknown code → `Blocked: needs review`, with a console warning
   - **Call:** `open` → Open; `settled` → Checkpointed; `unpriced` → Not priced, with the reason `no_symbol` → `no price symbol` or `tradingview_disabled` → `price source off`.
   - **Prediction:** Open, Met (ok), Missed (gap), Late (warn), Lapsed (muted).
   - **Unit test** `unit/status.test.ts`: every value of every relevant enum in `lib/api/schema.ts` (Judgement, Hypothesis status, CallState, PredictionState, gate failure codes, the thesis-judged values) has a mapping. A new backend value fails CI.
2. **`format.ts`**:
   - `activity(iso)`: `today`, `yesterday` or `N d ago` within 7 days; otherwise the `evidenceDay` form.
   - `evidenceDay(iso)`: `14 Jan 2026`. Evidence dates always show the year. Activity and due rows show it only outside the current year.
   - `due(iso)`: `18 Nov · in 31 d`, or `overdue 2 d` in warn.
   - `day()` in `lib/beliefs` and `shortDate()` in `lib/calls` are replaced by these.
3. **`argument.ts`**:
   - `argumentOf(beliefs)` returns, per step: the proven count, the strongest proven Belief, the Beliefs sorted by confidence (disproven and flagged first), whether the step is for or against the thesis, and the latest examination.
   - `weakestStep(steps)` looks at the four for-steps, ranks empty steps first and then the lowest strongest-confidence, and returns `{ step, confidence | null }`.
4. **`thesis.ts`**:
   - `proposition(statement)` returns `content.thesis_proposition` when present (B4).
   - Otherwise it returns the text before the first colon, if that colon falls within 160 characters.
   - Otherwise it returns the whole statement and lets the layout clamp it. It never cuts at the first sentence, which can split a proposition as badly as a colon can.
   - `rest(statement)` returns what follows the colon, or nothing.
   - Unit-tested on the production v2 thesis and an 80-word worst case.
5. **`seen.ts`**: `readMark(): Date | null` and `startMarking()` (Y9), both in try/catch. The window starts at the mark, or 7 days ago when there is none.
6. **`api/client.ts`** gains:
   - `hypotheses()`, memoised per page session and shared by Today and Theme until B3 lands. The memo is cleared after a successful publish, correction or proposed-update action.
   - `predictions(state?)` (`GET /api/v1/predictions`).
   - `allCalls(state?)` (`GET /api/v1/calls` without a theme).
   - `issue(id)`, `issueEdges(id)`, `issueProduced(id)`.
   - `exceptionsTotal()`, `candidatesTotal()` and `identityPendingTotal()` (totals only).

---

## 5. Pages

### 5.1 Today (`/`, `app/page.tsx` rewritten)

**Job.** What Atlas believes per theme and how sure it is; what changed; what is due; whether Atlas is working. It is also the phone glance.

**Layout, top to bottom:**
1. A visually hidden `<h1>Today</h1>`.
2. **Decision banner**, only when the Decide count is above 0: one row, `1 decision waits on you →`, linking to `/decide`.
3. **One card per theme**, in fixed config order with starting themes last, each an `<article aria-labelledby>`:
   - **Line 1:** the theme title (a link to `/theme?id=`) on the left. On the right: the `<Status>` lifecycle word (`Published 18 Oct` / `Draft` / `Starting`), the thesis-check word, and a count of unseen items (`● 3 new`).
   - **Line 2:** `proposition(thesis)` at 1.25rem, 2-line clamp, linking to the Hypothesis.
   - **Line 3:** `Weakest step: Control · 60%` (0.9rem, `--text-2`).
   - **Line 4:** `<ArgumentStrip compact />`, or `n findings` for a legacy Hypothesis.
   - **Line 5, two columns:**
     - Left, `Since last visit` (or `This week` when there is no mark): at most 3 rows from `/themes/{id}/changes` inside the window. Disproven, superseded and flagged changes come first, then the newest. Unseen rows carry a dot. Then `+N more`, linking to the theme's Changed list.
     - Right, `Due`: `<DueList limit={3} />`.
   - **Starting theme** (no active Beliefs): line 2 onwards is replaced by one line, `Starting · 0 of 7 companies have documents · 4 layers without a company`.
4. **Agents line:** `This week: Scout 3 runs · 7 Facts · Skeptic 4 runs · 3 found nothing new →`, linking to `/sessions`.
   - It counts non-isolated sessions from the last 7 days, by kind. Facts come from `facts`; a zero-yield run is one with `facts == 0`.
   - `Beliefs examined` is added once B2 lands.
5. **Record line:** `22 calls open · first checkpoint 18 Nov · 4 predictions due 30 Nov →`, linking to `/record`.

**Removed from `/`:** the theme descriptions (now in each theme's Records) and the investigation list (on `/workbench`, which already lists them).

**Data.** All loads run in parallel, and a failure degrades only its own slot:
- `GET /themes`
- `hypotheses()` (memoised)
- `GET /beliefs?status=active`
- `GET /themes/{id}/changes` (one call per theme)
- `GET /calls?state=open`
- `GET /predictions?state=open`
- `GET /sessions`
- the Decide badge's two sources (§2)
- `GET /leads?origin=tradingview_calendar&event_from=<today>` (the earnings row is omitted when this is empty)

The archive-signal leads are never loaded.

**States:**
- **Loading:** card skeletons at their final height (three grey bars plus the strip outline). No "Loading…" text and no layout shift.
- **A slot fails:** `Changes unavailable` or `Due unavailable` in that column; the rest of the card stays.
- **No themes:** `No theme yet`.
- **No thesis** (a theme with Beliefs but no Hypothesis): line 2 reads `No thesis yet · n proven Beliefs`, and the strip still shows.

### 5.2 Themes (`/themes/`)

- **Above the fold:** the same cards as Today, without the banner, the Agents line and the Record line. Each card gets one extra meta line: `12 companies · 11 with documents · 0 layers empty`.
- **Data:** `GET /themes`, `hypotheses()`, `GET /beliefs?status=active`.
- **States:** a theme whose Beliefs fail to load still shows its title and counts.

### 5.3 Theme (`/theme?id=`, `app/theme/page.tsx`)

**Job.** What Atlas thinks about this theme and how sure it is; what changed; what is due; the drill to a Belief and its quote.

**Layout:**
1. Crumb `Themes`; `<h1>` with the theme title.
2. **Thesis block:**
   - The published Hypothesis's proposition at 1.35rem, linking to it.
   - The status line: `Published 18 Oct · v2 · Not checked since correction (warn) · Weakest step: Control · 60%`.
   - `3 drafts` as a quiet link to `#records`.
   - With no published version, the latest draft shows, marked `Draft`.
3. **`What Atlas believes`** (the region and its h2 are kept): `<StepRows>` for the six steps. Each step is collapsed to its strongest Belief plus `+N more`.
   - **Freshness on each step row:** `examined 12 d ago` from the newest `last_examined_at`, or `never re-examined` when there is none.
   - **Freshness on each Belief row:** `as of 17 Oct`.
4. **Two columns at ≥ 64rem:**
   - **`Changed`** (h2): the list `Changes, newest first` (name kept). At most 7 rows, with disproven, superseded and flagged changes first inside the window, unseen dots, then `All N` to expand in place.
   - **`Due`** (h2): `<DueList>` for this theme, then `All 22 calls →`, linking to `/record?theme=`.
5. **`Companies`** (h2), the layer matrix: a `<table aria-label="Companies by layer">` with one row per layer.
   - Each row holds a `th` (the layer name) and a `td` with the company links. Each company has a coverage dot, filled when it has documents and hollow when it has none, with an `aria-label` such as "Lumentum, documents in the archive".
   - An empty layer reads `no company`, in `--warn`.
6. **`<RecordsFold>`**, rendered only when opened:
   - The theme description.
   - Hypotheses (the `Hypotheses` list kept, with all versions and drafts).
   - The per-layer tables (`Chip / laser companies` and the rest, kept as they are).
   - Relationships (`EdgeList`, all of them).
   - Candidates (count and table).
   - `Memory's open gaps (not evidence)`, the former Bottlenecks text.
   - Universe details (company count, sources, config version).

**Starting theme (memory-packaging):** one status block replaces items 2–4:
- `Starting · 0 of 7 companies have documents in the archive · 4 layers without a company (Controller, Bond equipment, Package substrate, Package materials)`.
- Then `Research begins when documents arrive.`
- Then the layer matrix, then Records.
- There are no six "Nothing believed yet" sections and no empty Changed or Due.

The step sections appear once any Belief exists. The e2e's `Nothing believed yet.` in an empty step region still holds for themes that have some Beliefs.

**Data:**
- `GET /themes/{id}/map` (beliefs, layers, relationships, candidates, bottlenecks; loaded once)
- `hypotheses()`
- `GET /themes/{id}/changes`
- `GET /calls?theme=`
- `GET /predictions?state=open`, filtered by theme
- the calendar leads, shown only if there are any

**States:**
- **Loading:** a skeleton of the thesis block and the strip.
- **Error:** `Could not load the theme`.
- **A step with more than 30 Beliefs:** it expands to 7 plus `Show all N`.

### 5.4 Hypothesis (`/hypothesis?id=&version=`)

**Job.** The bet: read the thesis in one line, see where each step stands, see what would kill it and when it is tested, and publish when asked.

**Layout (Belief-backed):**
1. Crumb (the theme).
2. **Kicker:** `Photonics · Published 18 Oct · v2 correction · <check word>`. `v2 correction` is a quiet link to `#records`, which opens the fold at the version picker.
3. **`<h1>`:** `proposition(thesis_statement)`.
4. **The rest of the thesis** plus `content.mechanism`: one `--text-2` paragraph, 3-line clamp, with `More`.
5. `Weakest step: … · NN%`.
6. **Gate banner**, shown only when the latest version is unpublished and either the gate has failures or the version is ready to publish:
   - The region `Lifecycle and publication`.
   - The failures in plain words, as the list `Failed checks`.
   - The edges that need approval, as the region `Owner review` with `Approve` and `Reject`.
   - The button `Publish version N`.
   - For Belief failures, `Override and publish` with a required reason.
7. **Six step rows:** `<StepRows>` over `content.steps`. Each summary shows the step statement (first sentence, 2-line clamp), `5 Beliefs`, the bar for the strongest, and `changed since drafting` (warn) when a Belief's judgement or status differs from the version's record.
   - Expanding a step shows its `statements` and its Beliefs. Each statement has a ✓ glyph with the accessible name `checked against its quotes`, or `set aside` for those under `unsupported_findings`.
   - Each Belief expands to its `<Quote>`s, fetched with `GET /beliefs/{id}` on first expand.
8. **Three-column band at ≥ 64rem:**
   - **`Would falsify it`:** the list name `What would falsify it` is kept.
   - **`Open questions`:** the version's unresolved questions; below them, the `Open Issues` h2 (kept) and a 7-row list.
   - **`Due`:** predictions such as `30 Nov · in 43 d · AXT Q3 revenue · $66–70M`. The measure shows to its first clause; the full measure is in `title` and an expand. The call checkpoint date sits beside them.
9. **`<RecordsFold>`:**
   - The version picker (the `<select>` labelled `Version`, options unchanged).
   - The `Changes between versions` region.
   - Scenarios (the tables, names unchanged).
   - Research Snapshots.
   - Gate details.
   - History and transitions.
   - Export (the `JSON` and `Markdown` links).
   - `What it rests on`: the full Belief list with citations. The region, its per-step sub-regions and the `Control beliefs` lists are kept.
   - The `Against it` region.
   - The predictions table with its settlement controls (measures use `.th-wrap`).

**Legacy (investigation-backed):**
- Items 1–6 are the same.
- Item 7 is the `Findings` list. Each finding's citations are `<Quote>`s that expand on demand.
- `Contradictions` follows.
- The band holds `Falsifiers` (list name kept), open questions and Due.

**Data:**
- `GET /hypotheses/{id}`
- `/publish-gate`
- `/predictions`
- `GET /calls?theme=`, filtered to `origin=hypothesis`
- `GET /beliefs/{id}`, on expand
- `/diff`, `/scenarios` and `GET /snapshots?hypothesis_id=`, only when Records opens

**States:**
- **Loading:** a headline skeleton.
- **Error:** `Could not load this Hypothesis`.
- **No published version:** kicker `Draft`, with the gate banner.
- **`thesis_judged` null:** the warn word from §4, item 1.

### 5.5 Belief (`/belief?id=`)

**Job.** The claim, how sure Atlas is, and the quote in its document, one click away.

**Layout:**
1. Crumb; `<h1>` with the statement.
2. **Verdict line:** `<Status>` + `<Confidence>` (text `Proven 60%`), then `· judged 18 Oct · Control · as of 17 Oct`.
   - If the Belief is unproven or flagged, the word is in warn or gap, followed by one line giving the open flag's reason in plain words.
   - The `Needs a second look` region is kept for flagged Beliefs.
3. **`Evidence for it`** (h2, region name kept): `<Quote>`s. The company moves into each caption, so the h3 company headers go.
4. **`Evidence against it`** (h2, region kept), only when it has entries. Otherwise one muted line: `Nothing against it found yet`.
5. **`Context`** (h2), for negative relations that are not load-bearing. No valence numbers appear.
6. `It replaces`: superseded Beliefs as plain rows.
7. **`<RecordsFold>`:**
   - The judgement reason.
   - `Judgement history` (list name kept).
   - Flags and notices.
   - Examinations.
   - The producing session.
   - The `Proven`/`Unproven` judge form, until Decide carries it in round 2.

A group with more than 7 citations shows 7 plus `+N`.

**Data:** `GET /beliefs/{id}`.

### 5.6 Source viewer (`/version?id=&assertion=`)

- **Highlight note:** `Quoted passage · 10-Q · filed 14 May 2025`. It replaces `the span of the … Assertion, characters N–M`, including on the Fact path, where the note read `the span of the fact Assertion`.
- **The character range** moves into the `Provenance` region, as a row `Characters 152,535–152,734`.
- Everything else is unchanged.

### 5.7 Record (`/record/`, new; minimal in round 1)

**Job.** Whether Atlas is working: the prospective record, and later the scorecard.

**Round 1:**
- **`<StatStrip>`:**
  - Calls open: 22.
  - Checkpoints recorded: 0.
  - Ahead of benchmark at +3 m: `— until 18 Jan`.
  - Predictions open · met · missed: 4 · 0 · 0.
- **While no checkpoint exists, one sentence:** `First checkpoint 18 Nov: 22 calls priced against their theme's companies.`
- **`Calls`** (h2), per theme (`?theme=` filters): the existing `CallsPanel` table, restyled.
  - Until a call has checkpoints, it has one cell: `first checkpoint 18 Nov`. After that, the `+1 m`, `+3 m` and `+6 m` cells show the change relative to the benchmark, in tabular figures, with ↑ or ↓.
  - Unpriced calls show `not priced: no price symbol` or `not priced: price source off`.
- **`Predictions`** (h2): rows of `deadline · measure (first clause) · expected range · <Status>`, each linking to its Hypothesis. Measures wrap.

**Round 2:**
- A hit line per horizon: `+1 m: 14 of 22 ahead of the benchmark`.
- Settled and lapsed filters.
- The scorecard section, rendered only when its route answers.

**Data:** `GET /calls?state=` (and `?theme=`), `GET /predictions?state=`.

**Empty:** `No calls yet: a call is made when a Belief is judged proven or a thesis is published.`

### 5.8 Decide (`/decide/`, new; read-only in round 1)

**Job.** Everything that waits on the owner, in one counted queue.

**Round 1:**
1. `<h1>Decide</h1>`.
2. `<StatStrip>` with one cell: `Waiting on you`.
3. Rows in this priority order, each a row-link to the object's page, where the existing controls live:
   1. **Hypothesis versions at the gate:** the latest unpublished version of each Hypothesis, with its `publish-gate` failures in plain words.
   2. **Open proposed updates** (`GET /proposed-updates?state=open`).
   3. **Beliefs to judge:** active and unproven or undecidable, flagged (`?flagged=true`), or with `open_notices > 0`.
4. **Empty state** (the expected state today): `Nothing waits on you.`
5. **`With the lead`** (counts only, each linking into System):
   - `136 links in the exceptions queue · none blocks a publish`
   - `104 candidates`
   - `0 identity reviews`

**Round 2:**
- Inline actions:
  - Publish, or Override with a reason.
  - Accept or Dismiss, with a reason.
  - Judge Proven at a confidence, or Unproven, with a reason.
- While posting, the button is disabled. On success, the row leaves the queue with a polite live-region message. Errors show inline in the row.
- Belief rows carry their load-bearing `<Quote>` inline.

**Data:**
- `hypotheses()`, then `/publish-gate` for each unpublished latest version
- `GET /proposed-updates?state=open`
- `GET /beliefs?judgement=unproven&status=active`
- `?judgement=undecidable&status=active`
- `?flagged=true`
- `?status=active`, filtered by `open_notices`
- the totals of `/relationships/exceptions`, `/candidates?state=lead` and `/identity-mappings?review_state=pending`

**Partial failure:** `Could not check publish gates`, with the rest still shown.

### 5.9 System (`/system/`, new)

An index page. Each row carries one state line, built from existing reads:
- `Memory · clean · 69% in memory` (`/memory/health`)
- `Agents · 12 runs this week`
- `Issues · 43 open`
- `Relationships · 457`
- `Exceptions · 136`
- `Workbench · 35 runs`
- `All Beliefs`
- `Hypotheses`
- `Companies`

Each state line is fetched separately. If one fails, its row shows the name alone.

The link names match the old nav labels (`Memory`, `Issues`, `Relationships`, `Exceptions queue`, `Research workbench`, `Beliefs`, `Hypotheses`, `Companies`, `Sessions`), so the e2e second clicks need no other change.

### 5.10 Issues (`/issues`) and Issue (`/issue?id=`, new)

**Issues:**
- The intro sentence goes. The filters stay, and so does the `Next action` region.
- The table becomes `<ul aria-label="Research frontier, next action first">`. Each `<li>` is a row-link to `/issue?id=`, with the title wrapping in body colour.
- **Meta line:** `step · companies · blocked | N open sub-questions · activity(created)`. The `Session` link sits above the overlay.
- **Parent:** `under <parent title>`, clamped to 1 line.
- Over 25 rows, the page shows 25 plus `Show all`.

**Issue:**
- `<h1>` with the title; `<Status>`; step and companies.
- `Sub-questions` and `Under`, as rows.
- `What it produced`: Facts as `<Quote>`s, Beliefs as rows.
- Records: the producing session, the created and closed times, the actor.

### 5.11 Round 2 pages

**Sessions → Agents (`/sessions`; the h1 stays `Sessions` until the rename lands):**
- A strip per agent for the last 7 days, at the top.
- Rows as outcome sentences, such as `Skeptic · examined 1 Belief: nothing new · 2 d ago`. The question is line 2, and repeated questions collapse (`×5`).
- The `Research sessions, newest first` table moves to Records.
- **`/session?id=`:** the card first, then Facts as `<Quote>`s; the `Facts recorded in the session` table is kept, in Records. Model, usage, cost, tool counts, exact times and the actor all go under Records.

**Company (`/company?id=`):**
- Kicker `Substrate · Photonics`; `<h1>` with the company.
- `What Atlas believes` (region kept), grouped as `Holds the position (14)`, `Depends on it (1)` and `Supplies (n)`. Rows look like `<StepRows>` rows, with no meta repeated on every row.
- `On this company`: its calls and predictions.
- The next reporting date, when known.
- Latest documents (5 plus `All`).
- **Records:**
  - `What Atlas found` (h2 kept): edges with their trust labels.
  - The `Identity` and `Listings (securities)` tables, kept.
  - The `Relationships out` and `Relationships in` tables, kept.
  - Financials.
  - Fetch-gate blocks.
  - Investigations.

**Phone pass at 390×844:**
- Status and the bar lead each row.
- The strip shows as 4 + 2.
- Clamps are checked.
- The break-ui worst cases: an 80-word thesis, 30 Beliefs in one step, a theme with no companies, a 120-character measure, a 3-word theme title, an unbroken 60-character company name.

**Sweep:** the System pages (Workbench, Investigation, Relationships, Exceptions, Beliefs, Hypotheses, Companies, Source) move onto the date helpers, status words, row-links and `.th-wrap`. Their intro paragraphs go, or shrink to one muted line. Memory changes only in its tokens.

---

## 6. Removed or demoted

- **Home:** the theme descriptions (moved to each theme's Records), the 35 investigations (on `/workbench`), and the `Research` heading and label.
- **Nav:** Research, Beliefs, Hypotheses, Companies, Sessions, Issues, Memory, Relationships, Exceptions queue and Research workbench are no longer top-level items. Every route stays, reached through System or by drilling down.
- **Theme page, above the fold:**
  - the theme description
  - the drafts' theses (now a count)
  - every Belief in full (now the strongest per step plus `+N`)
  - `Universe config version N`
  - the seven-column layer tables with `Source path` and `Identity reviews`
  - Relationships and Candidates
  - the Bottlenecks text
  - the inline Calls table (now Due lines, plus `/record`)
- **Hypothesis page, above the fold:** the `Unchecked` pill (now the kicker word), the version select, the dump of every Belief's citations, the `checked against its quotes` suffixes (now a glyph), and the Predictions table (now Due lines).
- **Belief page:** the judgement-reason paragraph, the numeric valence captions, and the jumps to h3 company headers.
- **Source viewer:** the Assertion and characters note.
- **Everywhere:**
  - underlined statement links
  - monospace dates
  - microsecond and ISO timestamps outside Records
  - intro paragraphs that describe the system
  - the eight status vocabularies
- **Never in UI copy above Records:**
  - agent ids (`atlas-…`)
  - job or role names
  - model names
  - `Hindsight` and `mental model`
  - source paths and config versions
  - valence numbers and character offsets
  - times of day

---

## 7. e2e changes (old → new)

**Shared:**
- `e2e/helpers.ts` gains:
  - `openSystem(page, name)`: clicks Site → `System`, then the named link.
  - `openRecords(page)`: clicks the `summary` with text `Records`, then expects `details.reader-records` to have `open`.
  - `expectRecordsClosed(page)`.
  - `expectNoLeaks(page)`.
  - `expectNoOverflow(page)`, at 1440 and 390.
- Viewport presets for `test.use`.

**Nav clicks** move to `openSystem`, with the same link names:
- assertions:43
- beliefs:17
- hypothesis-dossier:47 (`Hypotheses`)
- issues:16
- memory:17
- pdf-viewer:11
- reader:63, and the second company test
- relationships:35 (`Relationships`) and :118 (`Exceptions queue`)
- sessions:17
- source-viewer:48
- workbench:25 (`Research workbench`)

theme-explorer:24 (`Themes`) stays a direct nav click.

**reader.spec:**
- The "research index" test moves to the workbench page: `goto("/workbench/")`, find the question in the investigations table, and open it.
- The `ul.nav-reader` and `Operations` assertions are replaced by a nav test: five links, `Today, Themes, Record, Decide, System`, with `aria-current="page"` on `Today` at `/`, on `Themes` at `/theme?id=` and on `System` at `/memory/`.
- The phone overflow test targets `/` and waits for the first theme card.
- The company test calls `openRecords` before `What Atlas found` and the `Identity` table. The `.reader-quote` link `Source` becomes `Open in source`.

**theme-explorer.spec:**
- :28–38: the `Themes and their coverage` table becomes the theme card. Assert the `article` named by the theme, its card meta and its link.
- :43/:47: the h2 order becomes `What Atlas believes`, `Changed`, `Due`, `Companies`.
- :50–56: the step regions are unchanged. `Proven 80%`, `Unproven` and `1 flag` stay literal, but the test must click the step's summary to expand it first.
- :58–59: the change link is unchanged.
- :62–95: the h3 list, the `Chip / laser companies` table and the edge tables come after `expectRecordsClosed` and then `openRecords`.
- :99: `Lumentum` is clicked in the `Companies by layer` matrix.
- :102–125, the company page: Records opens before `Identity`, `Listings (securities)` and `Relationships out`.

**hypothesis-dossier.spec:**
- :50–62: `Hypotheses, newest first` is reached through `openSystem("Hypotheses")`. The date-cell regex `/^\d{4}-\d\d-\d\dT/` becomes the `evidenceDay` regex `/^\d{1,2} \w{3}( \d{4})?$/`.
- :66 and :204: the h1 is `proposition(...)`. The seeded theses (`THESIS[1]`, `THESIS[2]`, `BELIEF_THESIS`) are single sentences with no colon, so `proposition()` returns them whole and these assertions are unchanged.
- :67–71: `openRecords` comes before the `Version` select.
- :73–85: `Findings`, `What would falsify it`, `Contradictions` and `Falsifiers` are unchanged (they stay above the fold).
- :90–96, the scenarios (:148–161) and the export (:175–182): after `openRecords`.
- :99–113: the gate names are unchanged; the banner is now at the top.
- :205–207 (`What it rests on`, `Control beliefs`) and :229 (`Against it`): after `openRecords`.
- :236: `Source` becomes `Open in source`.
- :246–259, the theme test:
  - The `Hypotheses` list moves into Records. Assert that the thesis block holds `THESIS[2]` and `1 draft`, then `openRecords` and check the list.
  - The regex `published \d{4}-\d\d-\d\d` becomes `Published \d{1,2} \w{3}`.
  - The h2 `nth(1)` check becomes a lookup of the `What Atlas believes` region.

**beliefs.spec:**
- :52: `Source` becomes `Open in source`.
- :69: `openRecords` comes before `Judgement history`.
- `Nothing believed yet.` in `Control` is unchanged, because the theme has Beliefs.

**issues.spec:**
- :25/:44: `table` becomes `list`, with the same name; the `row` and `cell` selectors become `listitem` plus text.
- New: a row opens `/issue?id=`, with the title as the h1.

**sessions.spec:** in round 1, only the nav click changes. Round 2 adds `openRecords` before `Research sessions, newest first` and `Facts recorded in the session`.

**source-viewer and pdf-viewer:** the highlight note's text changes, and the `characters` text is now asserted inside `Provenance`.

**New specs:**
- **`e2e/today.spec.ts`:**
  - one card per seeded theme, in config order
  - the proposition, check word and strip visible in the 1440×900 viewport (`toBeInViewport`)
  - the Due row's text
  - a starting theme's line
  - no Decide banner when the queue is empty
- **`e2e/record-decide.spec.ts`:**
  - Record's stat strip and first-checkpoint line
  - Decide's `Nothing waits on you.`
  - with the dossier seed's unpublished v2, its gate row and link on Decide
- **`e2e/surface.spec.ts`**, for Today, Theme, Hypothesis, Belief, Issues, Record and Decide at 1440 and 390:
  - `expectNoOverflow` (`scrollWidth <= innerWidth`).
  - `expectRecordsClosed`.
  - `expectNoLeaks`: in the page, clone `main` and remove every `<Quote>` node (`blockquote`, `.quote`) and every `details.reader-records`. Quotes are removed because verbatim document text can legitimately contain `10:30`, `characters` or a negative decimal. The clone's `textContent` must not match `/atlas-[a-z]+|source path|universe config|Hindsight|mental model|\d{2}:\d{2}(:\d{2})?|characters \d+|valence|-0\.\d+/i`.

Secondary check: `unit/no-system-on-surface.test.ts` scans the reader pages' and components' source outside `RecordsFold` for `source_path`, `universe_version`, `char_start`, rendering of `actor`, and `mode="exact"`.

---

## 8. Round one: ordered checklist with acceptance criteria

Measure on production after deploy, with Playwright against `https://atlas.ekenhome.se`. Use the same capture as `.scratch/ui-review/2026-10-18/` and save the results to `.scratch/ui-review/<date>/after/`. Heights are `document.documentElement.scrollHeight` with Records closed.

1. **Foundations:** CSS tokens, type scale, frame, `.measure`, monospace removed from `time`, `.th-wrap`, row-as-link, no underlines outside prose.
   - *Accept:* no page shows dates in monospace, and every reader page shares one left edge. The lint, typecheck and build gates pass.
2. **Libraries:** `status.ts`, `format.ts` (three helpers, replacing `day` and `shortDate`), `argument.ts`, `thesis.ts`, `seen.ts`, and the client additions.
   - *Accept:* the unit tests pass, including the enum-coverage test (it fails when an enum value is deleted from a mapping). `proposition()` on the production v2 thesis returns its first clause, at most 160 characters.
3. **Components:** `site-nav`, `records-fold`, `status`, `confidence`, `quote`, `argument-strip`, `step-rows`, `stat-strip`, `due-list`, and the `Timestamp` modes.
   - *Accept:* `RecordsFold` children are absent from the DOM until the fold opens. The strip's `<li>` names read like `Relief, against the thesis: 3 proven, strongest 75%`.
4. **Fix the broken pages:** Issues as a list plus the `/issue` page; prediction measures get `.th-wrap`.
   - *Accept:*
     - `/issues` with production's 43 Issues is ≤ 3,500 px at 1440 (12,131 today).
     - Neither `/issues` nor the Hypothesis predictions table overflows sideways at 1440 or 390.
     - Every Issue row opens `/issue?id=`.
5. **Nav and `/system`.**
   - *Accept:* five items in one row, `aria-current` correct for each section, the nav ≤ 48 px tall at 390, and every System link resolves.
6. **Today.**
   - *Accept at 1440×900, without scrolling:*
     - the photonics card's proposition
     - `Not checked since correction` (warn)
     - `Weakest step: …`
     - the full strip
     - the first Due row (`18 Nov · in 31 d · first checkpoint · 22 calls`)
     - the memory-packaging `Starting` line
   - *Accept at 390×844, on the first screen:* the photonics proposition, the check word, and the strip's first row of four cells.
   - *Height:* ≤ 1,400 px at 1440.
   - *Content:* no investigation rows and no theme descriptions on `/`.
7. **Themes and Theme.**
   - *Height:* photonics ≤ 1,800 px at 1440 (78,728 today) and ≤ 6,000 px at 390 (494,195 today).
   - *Above the fold at 1440×900:* the h1, the thesis, the status line and at least the first four step rows.
   - *At 390×844:* the h1, the proposition and the status line.
   - *Lazy records:* no edge rows and no candidate rows in the DOM while Records is closed.
   - *Starting theme:* memory-packaging is ≤ 1,200 px at 1440, with no `Nothing believed yet` text.
8. **Hypothesis.**
   - *Height:* the published photonics Hypothesis is ≤ 2,000 px at 1440 (49,927 today).
   - *Above the fold at 1440×900:* the kicker with its check word, the proposition h1, `Weakest step` and at least four step rows.
   - *At 390×844:* the kicker and the full proposition.
   - *Order:* the band (falsifiers, open questions, due) sits above Records. The gate banner appears only for the dossier seed's unpublished v2.
9. **Belief and source viewer.**
   - *Accept:*
     - The verdict line reads `Proven NN% · judged …`, and no valence number appears anywhere.
     - Each quote has an `Open in source` target at least 24 px tall that lands on the highlighted span.
     - From the theme page this takes two clicks: the Belief row, then `Open in source`. Opening a step's `<details>` is a disclosure, not a navigation.
     - The highlight note reads `Quoted passage · <form> · filed <day>`, and the character range appears only in Provenance.
10. **`/record` and `/decide`** (read-only).
    - *Accept:* Record shows 22 open calls, `First checkpoint 18 Nov`, and the 4 predictions with their ranges. On production, Decide shows `Nothing waits on you.` plus the lead's three counts. Neither page overflows sideways at 1440 or 390.
11. **Tests:** every spec edit in §7 and the new specs. Then `npm --prefix frontend run lint`, `typecheck`, `test` and `build`, then `uv run python scripts/e2e.py`, all green.
    - *Accept:* the surface spec passes on all seven pages at both widths, and `scripts/gen_api_client.sh --check` is clean (no client change is expected).
12. **Record the work** in `docs/implementation-log.md`: files, tests, and heights before and after.

**Round two**, in order:
1. Decide's inline actions and their e2e (a seeded blocked draft appears, publishes and leaves the queue).
2. Record's per-horizon hit lines.
3. Agents (`/sessions`, `/session`).
4. Company.
5. The phone pass, with the break-ui worst cases.
6. The sweep of the System pages.

Each step runs the same overflow and leak checks. The company page must be ≤ 2,000 px at 1440.

---

## 9. Backend tickets for the lead (not UI work)

- **B1 (must-have).** A correction must re-judge the thesis before its version can publish, and the publish gate must refuse `content.thesis_judged == null` with a typed failure `thesis_unchecked`. The published photonics v2 is unchecked today because a correction reset its verdict.
- **B2.** `GET /api/v1/sessions` items should gain:
  - `agent` (`scout | researcher | skeptic | lead`)
  - `beliefs_proposed`
  - `beliefs_examined` (`{confirmed, qualified, contradicted, nothing_new}`, from `belief_examination`)
  - `issues_opened`

  Until then, Agents shows only runs, Facts and zero-yield runs.
- **B3 (optional).** A `theme_id` filter on `GET /api/v1/hypotheses`. The list is 112 KB with every version; meanwhile the UI filters client-side.
- **B4.** Hypothesis drafting should emit the thesis proposition separately from its supporting facts (for example `content.thesis_proposition`). `lib/thesis.ts` prefers it when present; the colon rule is the fallback.
- **B5 (optional).** A `newest_evidence_at` field (the latest cited document date) on `BeliefSummary`, for a theme-level `newest evidence 14 Aug` line. Round 1 shows examination freshness and `as of` instead.
- **Later.** `GET /api/v1/scorecard?theme=` once the scorecard ticket lands. For each case: the case, the date Atlas would have called it, the date it was priced, the lead time, and hit or miss with the reason. Record renders its scorecard section only when the route answers.
---

## 10. Round 3: the Chokepoint Watch (W1 8623f56)

Built on `ui/the-board` (main at v0.6.16 plus `ticket/w1-the-board` 8623f56). Round 3 adds the board, the Watch memo and the bear checks to the owner's pages. It reuses rounds 1 and 2 without change: the tokens, `<Status>`, `<Quote>`, `<RecordsFold>`, the row-as-link, the `.step` / `.step-details` disclosure, the three date helpers, `lib/seen` and the leak guard. It adds no npm dependency and no colour token. The debate behind this section is in `debate-round3-2026-10-18.json`.

**The shipping state is empty.** 0.6.17 goes live with no chokepoint and no watch run, so each new slot renders nothing, or one terse line where §10.3 says so. With Records closed, Today stays at 999/1542 px or less (desktop/phone) and Theme photonics at 1722/2904 px or less. Both are acceptance checks (§10.9, item 10).

### 10.1 Decisions

#### Where I yield to the director

| # | Director's point | What I build |
|---|---|---|
| Z1 | The bear checks were drafted against a shape the backend does not have. `value` is a dict, `basis` is agent prose, and a source span has no Assertion | `lib/bear-checks.ts` formats each check's `value` from its own fields (§10.6). The Unknown reason is written in the UI, per check, until B8 adds `unknown_reason`. A source span links through a new viewer path, `/version/?id=&from=&to=&parse=`, which highlights the span (§10.6). I never promise a highlight that cannot render. |
| Z2 | On Today, the memo leads and the board does not | Line 2 of the Watch row names up to two chokepoints, each linked, so Today → chokepoint → `Open in source` is two clicks. The memo excerpt moves to line 3 (one-line clamp, `Memo →`). The row says `Thesis-ready:` (the current state), never "became thesis-ready", until B12 adds `status_set_at`. |
| Z3 | The board-only theme put the memo above the board, and twice | The memo block and "This week's" are cut. The status line is `Watching · last watch 24 Oct · 4 chokepoints · 1 thesis-ready`. The board header's `Memo · 24 Oct →` is the page's only memo entry. |
| Z4 | "Lead" meant three things | The chokepoint status `lead` becomes `Spotted`, with the group `Spotted (n)`. The step status `primary` becomes `Quoted`. "Lead" now means the record only (`2 leads`). The step status `lead` becomes `Unquoted` (H2). |
| Z5 | "Needs a second look" already has a meaning, and here it fired on progress | A lapsed gate takes new words, `Below the bar` (H1). It is warn only when a thesis step lost its quote or the falsifiers were cleared. When only the open question is missing, it reads `No open question`, muted. The verdict line never says "No longer thesis-ready" next to `Thesis-ready`. The open-Issue gate goes to the lead (B13). The e2e seeds both cases (§10.8). |
| Z6 | R4 gave robotics both a card and a Watch row | A Today card shows when the theme has active Beliefs, or when it has no board, no run and `company_count > 0` (today's Starting card). A theme with a board or a run but no Belief has a Watch row only. The two robotics cases then look the same on Today (§10.2.4). Themes keeps every card (`Watching` / `Not started`). |
| Z7 | The theme layout depended on a condition, not on the data | The page always loads `GET /chokepoints?theme=` and `GET /watch-runs?theme=&limit=8` by slug, in parallel with `/themes`. The layout is chosen from what comes back (§10.3.1). This covers memory-packaging with a board. A zero-company theme with nothing in it reads `Not started · the first watch has not run`. |
| Z8 | The step strip was not glanceable | The label's brightness carries the state: `Quoted` is `--text` with `●`, `Unquoted` is `--text-2` with `○`, `Not examined` is `--muted` with no mark, and `Contradicted` is `--gap` with `✕`. The mark comes first. The layout stays 4 + `Against` + 2. One legend line appears, on the board only. On desktop the strip sits on the right of line 2. |
| Z9 | Rows repeated their group's word, the counts included the ruled-out, and the board pushed the thesis's Changed \| Due down | Grouped rows carry badges only, no status word. "Active" means not ruled out, and Ruled out keeps its own count. On a theme with a thesis, the board sits **after Changed \| Due and before Companies**, so the thesis's changes and due dates stay beside its steps. |
| Z10 | Warn was overused | `Quiet since …` is muted, and quiet rows sort to the end of their group. `Holder not yet named` and `None written yet` are muted. Warn is kept for two things: `Below the bar` (a lapsed thesis step or falsifier) and Today's stopped watch (`last watch 24 Oct`, warn). |
| Z11 | Three near-synonyms for falsifiers | The band is `What would falsify it`, and the gate text says `a falsifier`. Step f keeps `STEPS.invalidation`, `What would invalidate it`, the Hypothesis page's pairing. The extra sentence under `Context, not evidence` is cut. The gate lines read `Meets the bar for a thesis.` and `Waiting for proof` (muted). |
| Z12 | Real memos will leak | `markdown.ts` runs a deterministic owner-words pass over its text nodes, driven by the `lib/status.ts` tables (§10.5). A UUID is removed and the gap it leaves is collapsed. Exactly one internal link form is allowed, `atlas:chokepoint/<uuid>` (it depends on B9). B9 fixes the memo's shape. `expectNoLeaks` against production is part of W2's first-run acceptance. |
| Z13 | Correctness: R7, Facts on mount, Issue titles, the runs limit, holder matching, the mode word, the relief clamp | Spans link through `fact.assertion.id` (as `company/page.tsx:443` does). On mount the page reads only the first Fact of each thesis step (at most 3, plus their documents); the rest load when a step opens. Any Issue title missing from the cached list is read with `GET /issues/{id}`. Today reads `GET /watch-runs?limit=200`. A holder is matched by slug, else CIK, else exact name. Only `First survey` is shown as a mode word; the weekly default shows none. The relief horizon is clamped at a word boundary, with an ellipsis. The board-only theme's Issue list is titled `Open questions`. |
| Z14 | On a phone, the bear-checks grid goes ragged | The checks are rows: label, then the value right-aligned, then a word only for Flag or Unknown. Each row is a disclosure. Two columns at ≥ 64rem. The order of the checks is fixed (Y7); a flag is coloured, never moved. |
| Z15 | Optional: crowding words | `Early`, `Emerging`, `Crowded`, each with `title="Atlas's guess at how widely it is known"`. "Not yet noticed" asserted a fact the model cannot know. |
| Z16 | Optional: two-line board rows, the memo h1, EDGAR links | The board rows are two lines on desktop (§10.3.3). The memo page's h1 is `Robotics · 24 Oct`. Each holder CIK in Records links to its EDGAR filer page. |

#### Where I hold

- **H1: `Below the bar`, not `Gate lapsed`.** The chokepoint page already says `Meets the bar for a thesis.` One concept should have one word on all three surfaces: the badge, the page line and the gate text. "Gate" is the system's word for publishing, and Decide shows it only in "gate blocks". The page line reads `Below the bar: no quote for control`.
- **H2: the step status `lead` reads `Unquoted`, not `Unquoted lead`.** The backend sets `lead` for a step that rests on a lead *or an Issue* (`StepEvidence`: "`lead` a lead or an Issue"). A step backed only by an open question would then read "lead", which is false, and it brings back the word Z4 retires. `Unquoted` pairs with `Quoted`, and says exactly what the owner cannot yet click.
- **H3: a bear check's `basis` goes in the company page's Records, not in the open row.** Real basis strings carry ISO dates, `XBRL`, `in the ledger`, `the as-of time`, unscaled numbers, bracketed concept names and the rule's own text. The owner's rule allows raw records only in Records, and a muted line inside an open row is still above Records. The open row shows the UI-written figures from `value`, plus the quotes and the filings with their links. Records holds `Bear checks: how each was read`, with every check's basis verbatim.

#### Kept from the draft (the director agreed)

- R1: the Watch is keyed by theme slug.
- R6: board rows fetch no Fact.
- R9: the memo is React elements, never `innerHTML`, and only http(s) links leave Atlas.
- R10: the memo is not exempt from the leak guard.
- R12: the vocabularies live in `lib/status.ts`.
- The Watch section sits below the theme cards.
- `Ruled out` is its own closed, lazily rendered fold outside Records.
- The band (falsify / supply catches up / context).
- Stale is read from `last_evidence_at`.
- Empty Today slots render nothing.
- The step regions use `lib/beliefs.STEPS` (step f reads `What would invalidate it`). The strip and pips use `lib/argument.STEP_LABELS`. Step letters never render.

### 10.2 Owner words (all in `lib/status.ts`, covered by the enum test)

| Source | Value | Word | Tone |
|---|---|---|---|
| `ChokepointStatus` | `lead` | Spotted | muted |
| | `candidate` | Candidate | muted |
| | `thesis_ready` | Thesis-ready | ok |
| | `killed` | Ruled out | gap |
| derived: `needs_review`, `missing` has a step or `kill_criteria` | | Below the bar | warn |
| derived: `needs_review`, `missing` is only `open_issue` | | No open question | muted |
| derived: `stale` | | Quiet since `<plainDay(last_evidence_at)>` | muted |
| `StepState.status` | `primary` | Quoted (`●`, label `--text`) | — |
| | `lead` | Unquoted (`○`, label `--text-2`) | — |
| | `unexamined` | Not examined (no mark, label `--muted`) | muted |
| | `contradicted` | Contradicted (`✕`) | gap |
| `Crowding` | `early` / `emerging` / `consensus` | Early / Emerging / Crowded (title: `Atlas's guess at how widely it is known`) | muted |
| | null | Crowding not judged | muted |
| `WatchMode` | `architect` | First survey | muted |
| | `delta` | (no word: the default) | — |
| gate `missing` | `step_a_primary` | a quote for the constraint | — |
| | `step_b_primary` | a quote for demand against supply | — |
| | `step_d_primary` | a quote for control | — |
| | `kill_criteria` | a falsifier | — |
| | `open_issue` | an open question | — |
| | anything else | something else, needs review (plus a console warning, as `gateFailureText` does) | — |
| route filter `BoardFilter` | `stale`, `needs_review` | mapped for coverage only; the UI does not filter by them | — |
| `CheckStatus` | `flag` / `clear` / `unknown` | Flag / (no word) / Unknown | warn / — / muted |
| `CheckKey` | the six keys | §10.6 table | — |

**Section and group words:** `Watch`, `Memo`, `Chokepoints`, `Thesis-ready`, `Candidates`, `Spotted`, `All N spotted`, `Ruled out`, `Held by`, `Holder not yet named`, `not yet researched`, `The argument`, `Against the thesis`, `Still needs:`, `Meets the bar for a thesis.`, `Waiting for proof`, `What would falsify it`, `None written yet`, `When supply could catch up`, `Not estimated`, `Context, not evidence`, `Open questions`, `Nothing on the board yet.`, `Watching`, `Not started`, `last watch`, `Bear checks`, `Open the filing`, `Open in source`.

**Never shown above Records:**
- step letters and every enum code above;
- holder CIKs;
- event, run, session, Fact and chokepoint ids;
- tool calls, cost, tokens and a run's `counts` keys;
- the actor;
- a bear check's `basis`, concept names and ISO dates.

### 10.3 Pages

#### 10.3.1 Today (`app/page.tsx`)

**Reads.** Two reads join Today's parallel loads; each fails on its own (the slot rule):
- `GET /watch-runs?limit=200`, all themes, newest first. `latestByTheme` keeps the two newest runs per theme: the latest, and the previous one, which sets the window.
- `GET /chokepoints?limit=500`, all themes.

Both answer `items: []` in the shipping state. No Fact is read (R6).

**Cards (Z6).** `todayCards(themes, beliefs, board, runs)`:
- A theme with active Beliefs gets its round-2 card, unchanged, with no board line (the Watch row carries it).
- A theme with no Belief, no chokepoint, no run and `company_count > 0` gets today's Starting card.
- Any other theme gets no card.

Every layer name goes through `layerName()`: `COMPANY_LAYERS[layer]`, else the humanised slug (`gating-equipment` → `Gating equipment`). This applies to `startingLine`, `startingStatus` and `LayerMatrix`, so a W6a slug never renders `undefined`.

**The Watch section.** It sits between the theme cards and the Agents line: `<section aria-labelledby="watch">`, with the h2 `Watch` (`.reader-label`). It renders only when some slug is watched. A slug is watched when it has a run or an active (not ruled-out) chokepoint. Rows follow the cards' theme order, then watched slugs missing from `/themes`, alphabetically.

```
WATCH
● Robotics · 24 Oct · First survey                    4 chokepoints · 1 thesis-ready
  New: Precision reducer capacity · Servo magnet supply +2
  Two makers hold most precision reducer capacity; lead times stretched … Memo →
```

**Line 1:**
- The unseen dot, when the latest run's `created_at` is after the last-visit mark (`isUnseen`).
- The theme title: from `/themes`, else the humanised slug.
- `plainDay(run_date)`, then `First survey` for an architect run (nothing for a weekly one).
- When the latest run is more than 9 days old, the date reads `last watch 24 Oct`, in warn. Only a stopped watch takes warn.
- **Right side:** `boardLine(counts)`, for example `4 chokepoints · 1 thesis-ready · 1 below the bar`.
  - Active chokepoints only. Zero parts drop out.
  - `below the bar` is warn, and counts only the warn case of Z5.
  - It links to `/theme?id=<slug>#board`, above the row overlay as `.row-secondary`.

**Line 2: named chokepoints** (`namedOnBoard(board, runs)`), at most two, each a link to `/chokepoint/?id=`, then `+N` for the rest.
- **The window** runs from the previous run's `created_at` (a first run has no lower bound) to now.
- **What can be named, in order:**
  1. `Thesis-ready:` a chokepoint at that status with `last_event_at` in the window;
  2. `New:` one with `created_at` in the window;
  3. `Ruled out:` one ruled out with `last_event_at` in the window.
- Within a label, the API order holds (latest event first). Parts sharing a label share it, as in `New: A · B +2`.
- With nothing to name, line 2 is omitted. Until B12, the label is the current status; after B12 it reads from `status_set_at`.

**Line 3:** `memoExcerpt(memo)`, as plain text with a one-line clamp in `--text-2`, then `Memo →` to `/watch-run/?id=`. A theme with chokepoints but no run has no date in line 1 and no line 3.

**Row-as-link.** Each named chokepoint is its own link. The row overlay is not used, because the row holds three or more links.

**Empty, loading, failed.**
- The shipping state renders nothing: no heading, no skeleton.
- While loading, the section renders nothing.
- A failed read renders nothing and shows no error.

**Both robotics cases (after Z6 they are identical on Today):**

| | Robotics in `GET /themes` | Robotics not in `GET /themes` |
|---|---|---|
| Before its first run (the shipping state) | No card, no Watch row. Themes shows `Robotics · Not started` | Nothing anywhere |
| After the architect run | A Watch row only (no card) | A Watch row only. It opens `/theme?id=robotics` (board-led). Themes lists a `Watching` card for it, from `watchedSlugs` |
| After W6 admits holders, while it has no Belief | A Watch row only (a board exists, so no Starting card) | the same |

**Phone (390):**
- Line 1 wraps: the title and date, then the board line under them at 0.85rem.
- Line 2 wraps to at most two lines.
- Line 3 keeps its one-line clamp.
- A row is about 100 px.

#### 10.3.2 Theme (`app/theme/page.tsx`)

**Reads.** `Theme()` loads four reads in parallel: `/themes`, `/beliefs?theme=` (as today), `GET /chokepoints?theme=<slug>&limit=500` and `GET /watch-runs?theme=<slug>&limit=8`. `themeLayout(summary, beliefs, board, runs)` picks the page. Taken in order, the first that applies wins:
1. **Active Beliefs → the thesis layout** (round 2). It renders as soon as the Beliefs arrive, without waiting for the board.
2. **Any chokepoint (ruled-out ones too) or a run → the board-led layout.** This holds for robotics in or out of `/themes`, and for memory-packaging with a board.
3. **The slug is in `/themes` → Starting.** With `company_count > 0`, it is today's Starting block. With zero, the status line reads `Not started · the first watch has not run`, and no "documents arrive" text appears.
4. **Otherwise → today's error,** `Could not load the theme: it is not one of the themes.`

A failed board or runs read counts as empty when choosing the layout. `GET /beliefs?theme=` filters by plain equality, so an unknown slug answers an empty list. For a slug missing from `/themes`, a Beliefs error also counts as "no Beliefs", so the board-led path never depends on it. In the board-led layout, it renders `Chokepoints unavailable` in the board slot; in the thesis layout, nothing. Rule 1 does not wait for the board; rules 2 to 4 wait for all four reads, behind the round-1 thesis-block skeleton.

**Thesis layout (photonics):**
1. Crumb, h1
2. Thesis block
3. `What Atlas believes`
4. Changed \| Due
5. **`Chokepoints`** (Z9), only when the board has items or a run exists
6. Companies
7. Records

In the shipping state, item 5 renders nothing, so photonics keeps 1722/2904 px.

**Board-led layout (robotics, memory-packaging with a board):**
1. Crumb `Themes`, h1 (the summary's title, else the humanised slug).
2. **Status line:** `Watching · last watch 24 Oct · 4 chokepoints · 1 thesis-ready`. `last watch` is warn after 9 days.
3. **The board,** as the page's lead section.
4. **`Open questions`:** `<OpenIssues theme>`, 7 rows plus `All Issues`.
5. **`Companies`:** only when the theme is in `/themes` and has companies.
6. **`<RecordsFold counts="2 watch runs">`:**
   - each run as a row, `24 Oct · First survey · 212 tool calls · $3.10`, linking to its memo page;
   - the theme description and universe details, when the theme is in `/themes`.

A board-led theme with a run and no chokepoint shows the board slot as `Nothing on the board yet.` (one muted line).

#### 10.3.3 The board (`components/board.tsx`, `id="board"`)

```
CHOKEPOINTS                                                      Memo · 24 Oct →
● quoted  ○ unquoted  ✕ contradicted  · dim: not examined

THESIS-READY (1)
Indium phosphide substrate capacity                                Below the bar
AXT, Sumitomo Electric +1 · Substrate · Early · relief 2028…   ● Constraint ● Demand ○ Control Capture · Against Relief Invalidation

CANDIDATES (2)  …
SPOTTED (9)  … first 5, then "All 9 spotted" (expands in place)
▸ Ruled out (3)
```

**Header:**
- The h2 `Chokepoints`, with `Memo · <plainDay> →` on the right (the theme's latest run; omitted with none).
- The legend: one muted 0.8rem line, `aria-hidden`.

**Groups,** each a `.reader-label` h3 with its count; an empty group renders nothing:
1. `Thesis-ready`: `Below the bar` rows first.
2. `Candidates`.
3. `Spotted`: the first 5, then `All N spotted`.

Within a group, rows keep the API order (latest event first), and quiet rows move to the group's end.

**`Ruled out (n)`:** a closed `<details className="board-killed">` whose rows render on first open. Each row reads `<constraint> · ruled out <plainDay(last_event_at)> · <status_reason, one-line clamp>`.

**Row** (`components/chokepoint-row.tsx`, `<li className="reader-row">`):
- **Line 1:** the constraint (`.row-title`, the overlay link to `/chokepoint/?id=`, 2-line clamp). On the right, the badges only: `Below the bar` (warn), `No open question` (muted), `Quiet since 14 Aug` (muted).
- **Line 2, left** (`.row-secondary`, 0.85rem muted), each part omitted when absent:
  - holders, with up to 2 names and then `+N`;
  - `layerName(layer)`;
  - the crowding word;
  - `relief <horizon>`, clamped at a word boundary to about 28 characters, with `…`.

  Holder names are plain text here. They link only on the chokepoint page, so the row overlay keeps one target.
- **Line 2, right:** `<StepPips>`, a `<ul aria-label="Steps">` in `ARGUMENT_ORDER`: four items, a `·`, the small word `Against`, then two. Each `<li>` is the mark, then the `STEP_LABELS` label, in the Z8 brightness. Its accessible name reads `Control: unquoted`.
- **No** status word, CIK, event count or id.

**Heights:** about 60 px a row on desktop. On a phone, line 2's parts wrap and the pips take their own lines (4, then `Against` + 2), about 80 px.

#### 10.3.4 Chokepoint (`/chokepoint/?id=`, `app/chokepoint/page.tsx`; nav section Themes)

The page answers what is scarce, who holds it, how far the evidence has got, what it still needs, what would falsify it, and where the quotes are. Top to bottom:

1. **Crumb** to `/theme?id=<slug>#board`. **Kicker** `<theme title> · <layerName>`. **h1** the constraint.

2. **Holders:** `Held by Harmonic Drive Systems, Nabtesco, Leaderdrive`.
   - `holderView(holders, companies)` matches each holder by slug, else CIK, else exact case-folded name, against `GET /companies` (cached).
   - A match links to `/company?id=`. Otherwise the name is plain text, followed by a muted `not yet researched`.
   - With no holder: `Holder not yet named` (muted).

3. **Verdict line:** `<Status>` word, then `since <plainDay>`. The date is the last `status_set` event in `history`, else `created_at`; after B12, `status_set_at`.
   - Ruled out: `Ruled out 3 Nov: <status_reason>` (gap), with the reason whole.
   - Badges follow, as on the board.

4. **The bar line** (`barLine(chokepoint)`), with one case per state:

   | State | Line |
   |---|---|
   | Spotted or candidate, gate fails | `Still needs: a quote for demand against supply · a falsifier · an open question` |
   | Spotted or candidate, gate holds | `Meets the bar for a thesis.` |
   | Thesis-ready, gate holds | `Waiting for proof` (muted) |
   | Thesis-ready, a step or the falsifiers missing | `Below the bar: no quote for control` (warn; `no` + the gate words without their article, joined with ` · `) |
   | Thesis-ready, only the open question missing | `No open question linked` (muted) |
   | Ruled out | no line |

5. **`The argument`** (h2): the four for-steps, then an h3 `Against the thesis` and the two against-steps. Each is a `<section aria-label={STEPS[name]}>` using the `.step-details` disclosure.
   - **The summary:**
     - the step name and its status word;
     - the count line `2 quotes · 1 lead · 1 open question`, with zero parts dropped;
     - `set <plainDay(set_at)>`;
     - for a thesis step whose first Fact has loaded, that Fact's statement as the headline (2-line clamp).
   - **A not-examined step** is a plain row, `Relief · Not examined`, with no disclosure.
   - **The body:**
     - Facts as `<Quote>`s (statement, verbatim quote, caption, `Open in source →` via `routes.span(fact.assertion.source_version_id, fact.assertion.id)`). The caption is `<company> · <document> · <evidenceDay(available_at)>`. `against` is set on a contradicted step.
     - Issues as row-links to `/issue?id=`.
     - Leads as a muted `2 leads`, unlinked until B6.
   - **Fetching (Z13):**
     - On mount, the page reads the first Fact of steps a, b and d (at most 3) and their distinct Source Versions (`GET /source-versions/{id}`, cached).
     - A step's other Facts load when it first opens, with `+N quotes loading`.
     - A failed Fact shows `Quote unavailable` in its place.
     - Issue titles come from the cached `GET /issues`; any missing one is read with `GET /issues/{id}`.
   - **Two clicks:** board row → `/chokepoint` (1); open the step (a disclosure, not counted, as in §8.9); `Open in source` (2).

6. **The band:** three columns at ≥ 64rem, stacked below that.
   - `What would falsify it`: the kill criteria as a list. With none, `None written yet` (muted).
   - `When supply could catch up`: `horizon`, then `basis` as a `--text-2` paragraph. With none, `Not estimated`.
   - `Context, not evidence`: the crowding word, with its title. With none, `Crowding not judged`.

7. **`Open questions`:** the linked Issues still open, as rows. With none, the section is omitted (the bar line already says it).

8. **`<RecordsFold counts="14 events">`:**
   - **History,** oldest first, from `historyRows(events)`. It replays the events, so each sentence knows the before and after values:
     - `24 Oct · Created at Gating equipment, held by 3`
     - `Control: not examined → unquoted · why: <reason>`
     - `Status: Candidate → Thesis-ready`
     - `Falsifiers rewritten (2)`
     - `Note: <text>`

     Each sentence is followed by `· by <actor>`, the session link, and `exact` time.
   - The holders' CIKs, each linked to its EDGAR filer page.
   - The closed linked Issues.
   - The created-by session or run.

**States:**
- Loading: an h1 skeleton and six step outlines.
- Not found: `This chokepoint does not exist.`
- Error: `Could not load the chokepoint`.

**Phone:** the same order. The verdict line wraps, with the badges under the word, and the band stacks.

#### 10.3.5 Memo (`/watch-run/?id=`, `app/watch-run/page.tsx`; nav section Themes)

1. Crumb: the theme (`/theme?id=<slug>`). h1 `Robotics · 24 Oct` (the theme title · `plainDay(run_date)`). Kicker `First survey` for an architect run only.
2. One muted line: `The Watch's memo · not evidence`.
3. `<Memo source>` at `.measure`.
4. `Earlier runs`: up to 7 rows from `GET /watch-runs?theme=&limit=8`, each `24 Oct · <excerpt, one-line clamp>`, linked. Omitted with none.
5. `<RecordsFold>`: the `counts` as a key-value table, tool calls, cost, tokens, the session link and the exact created time.

**States:**
- Not found: `This memo does not exist.`
- Error: `Could not load the memo`.

**Phone:** the same order.

**The renderer** (`lib/markdown.ts` → `components/memo.tsx`). It parses the memo into `Block[]` and renders React elements. No `innerHTML`.
- **Blocks:** headings (levels 1–3 render as h3, 4–6 as h4), paragraphs, and lists (ordered or not, one level; deeper items are flattened).
- **Inlines:** text, `em`, `strong` and links.
  - A link renders as `<a target="_blank" rel="noopener noreferrer nofollow">` only when its target matches `^https?://`. Its host follows in muted text.
  - `atlas:chokepoint/<uuid>` becomes a `Link` to `/chokepoint/?id=` (B9 makes the Watch cite this way).
  - Any other target renders as its text.
- **Neutralised:**
  - Fenced and indented code blocks are dropped.
  - Inline code becomes text, then passes the owner-words pass.
  - Raw HTML stays literal text.
- **The owner-words pass** (`ownerWords(text)`), on every text node outside link targets, replaces exact tokens only:
  - each `ChokepointStatus`, `StepStatus`, `Crowding` and gate code by its §10.2 word, with case kept at sentence start;
  - step names `demand_vs_supply` and the like by their `STEPS` words;
  - `step a`…`step f`, `step_a`…`step_f` and `(a)`…`(f)` after the word "step" by the `STEP_LABELS` label.

  A UUID is removed, along with the whitespace and punctuation it leaves stranded (`Fact <uuid> shows` → `Fact shows`; `(<uuid>)` → nothing).
- **Robustness:** CRLF is normalised, unbalanced emphasis stays literal, and the parser is linear-time (no backtracking regex over unbounded input).
- **`memoExcerpt(src)`:** the first paragraph block as plain text, after the owner-words pass. It falls back to the first list's items joined with ` · `. A heading-only memo gives `""`, and line 3 then shows only `Memo →`.

#### 10.3.6 Company: the bear checks (§10.6)

### 10.4 Lib and component layout

**`frontend/lib/`** (pure modules, each unit-tested):
- **`status.ts`** (extended): `CHOKEPOINT_WORDS`, `STEP_STATUS_WORDS`, `STEP_MARKS`, `CROWDING_WORDS`, `WATCH_MODE_WORDS`, `GATE_MISSING`, `gateMissingText`, `BEAR_STATUS_WORDS`, `BEAR_LABELS`, `BEAR_UNKNOWN_REASONS`, and `OWNER_TOKENS` (the map the memo pass reads, built from the tables above).
- **`chokepoints.ts`:** `boardGroups`, `boardCounts` (active only, per theme, with `ready`, `below`, `killed`), `boardLine`, `badges(cp)` (returns `below` / `noQuestion` / `quiet`), `pipsOf`, `barLine`, `stepCounts`, `thesisHeadlineFactIds` (at most 3), `factIdsOf(step)`, `historyRows`, `holderView`, `layerName`, `themeTitle`, `humanise`, `clampWords`.
- **`watch.ts`:** `latestByTheme` (latest and previous), `watchedSlugs`, `watchRows`, `namedOnBoard`, `stoppedWatch` (more than 9 days), `todayCards`, `themeLayout`.
- **`markdown.ts`:** `parseMarkdown`, `ownerWords`, `memoExcerpt`.
- **`bear-checks.ts`:** `parseBearChecks` (a runtime guard until B8), `bearSummary`, `bearValue(check)`, `bearFigures(check)`, `unknownReason(check)`, `money(amount, unit)`.
- **`nav.ts`:** `/chokepoint` and `/watch-run` → Themes.
- **`routes.ts`:** `chokepoint(id)`, `watchRun(id)`, `spanAt(versionId, from, to, parse)`.
- **`api/client.ts`:**
  - `chokepoints({ theme?, status?, limit })`, `chokepoint(id)`, `watchRuns({ theme?, limit })`, `watchRun(id)`;
  - `companiesIndex()`, a memoised map by slug, CIK and folded name;
  - `bearChecks(companyId)`: a raw `send` with the guard; null on 404.

**`frontend/components/`:**

| Component | What it is |
|---|---|
| `watch-section.tsx` `<WatchSection rows>` | Today's Watch section. Renders null with no rows. |
| `board.tsx` `<Board items run? lead?>` | The header, legend, groups, `All N spotted`, and the lazy `Ruled out` fold. |
| `chokepoint-row.tsx` | One board row. |
| `step-pips.tsx` `<StepPips steps>` | The strip, with accessible names. |
| `chokepoint-steps.tsx` | The page's six step sections (`.step` / `.step-details`, `<Quote>`, Issue rows). |
| `memo.tsx` `<Memo source>` | The renderer over `Block[]`. |
| `bear-checks.tsx` `<BearChecks companyId>`, `<BearChecksRecords checks>` | The section, and its Records table. |

**Pages:** `app/chokepoint/page.tsx`, `app/watch-run/page.tsx`. Extended: `app/page.tsx`, `app/theme/page.tsx`, `app/themes/page.tsx` (the `Watching` / `Not started` cards and watch-only slugs), `app/company/page.tsx`, `app/version/page.tsx` (`?from=&to=&parse=`).

**CSS:** `.watch-row`, `.board-group`, `.board-killed`, `.pips`, `.pip-q` / `.pip-u` / `.pip-n` / `.pip-x`, `.bear-rows`, `.memo` (h3/h4 sizes from the scale; `.memo p a` underlined as prose). Existing tokens only.

### 10.5 The leak guard

**`surface.spec.ts`** adds the following pages at 1440 and 390, each with `expectNoOverflow`, `expectFoldsClosed` (plus `details.board-killed` closed and empty) and `expectNoLeaks`:
- Today, with the Watch rows;
- Theme photonics, with the board;
- Theme robotics;
- Chokepoints A, B, D and F;
- the photonics memo page;
- Company Lumentum, with the bear checks.

**`LEAKS`** gains exact tokens only (no snake_case catch-all):

```
\bstep [a-f]\b | \bstep_[a-f](_primary)?\b | \bthesis_ready\b | \bdemand_vs_supply\b | \bkill_criteria\b
| \bopen_issue\b | \bunexamined\b | \bneeds_review\b | \bshelf_or_atm\b | \bgaap_gross_margin\b
| \bcustomer_concentration\b | \bgoing_concern\b | \bnet_cash\b | \buv run\b | \bXBRL\b
| \bin the ledger\b | \bas-of time\b | \b\d{4}-\d{2}-\d{2}\b
| [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}
```

Quotes and Records stay excluded; the memo is not (R10). If the ISO-date token fails an existing surface page, that is a defect to fix, not a reason to drop the token.

**`unit/no-system-on-surface.test.ts`:**
- `SURFACE` adds the new pages and components.
- `FORBIDDEN` adds a rendered `.cik`, `.tool_calls`, `.cost_usd`, `.tokens`, `.basis`, `.concept` and `{step.step}`.
- `char_start` and `char_end` stay allowed only inside an `href` builder (`routes.spanAt`).

**W2's acceptance (for the lead):** after the first live Watch run, `expectNoLeaks` runs against production Today and that memo page (`.scratch/ui-review/<date>/watch-leaks.cjs`).

### 10.6 Company: the bear checks (`components/bear-checks.tsx`)

**Where.** `<section aria-labelledby="bear">`, with the h2 `Bear checks`, after `What Atlas believes` and before `On this company`.

**Summary line:** `1 flag · 4 clear · 1 unknown`.

**Rows.** The six checks are rows in this fixed order: dilution, shelf_or_atm, gaap_gross_margin, customer_concentration, going_concern, net_cash. One column on a phone and two at ≥ 64rem. Each row is a `<details>`:
- **Summary:** the label, then the value right-aligned in tabular figures, then the word, shown only for `Flag` (warn) or `Unknown` (muted).
- **An Unknown row** reads `Unknown · <reason>`. It is always shown, never collapsed into the others.

**`bearValue`, read from `value`'s own fields:**

| Key | Label | Flag / clear shown as | Unknown reason (UI-written until B8) |
|---|---|---|---|
| `dilution` | Share count growth | `growth_pct` → `+12% in a year` | `no comparable share counts` |
| `shelf_or_atm` | Shelf or offering filings | `filings[]` → `2 filings · S-3, 424B5 · latest 4 Mar` | `not in the filings Atlas collects` |
| `gaap_gross_margin` | Gross margin, last four quarters | `ttm_margin_pct`, `change_points` → `41% · down 6 pts` (or `· up 2 pts`; no change part when null) | `no usable quarterly figures` |
| `customer_concentration` | Largest customer | `current_percent` → `38% of revenue` (`more than 38%` when its match has `lower_bound`); clear on `no_customer_above` → `none above 10%` | `no customer share stated` |
| `going_concern` | Going-concern warning | flag → `in the <document.form>`; clear → `none in the <document.form>` | `no report fully read` |
| `net_cash` | Net cash or debt | `net_cash`, `unit` → `net cash $412M` / `net debt $1.2B` | `no complete balance sheet` |

An unknown key or status renders with its humanised key and `Unknown`, plus a console warning. A null or malformed `value` on a flag or clear row shows `—`.

**`money`:** `USD` → `$`, `EUR` → `€`, `GBP` → `£`, `JPY` → `¥`; any other unit follows the number (`412M CHF`). Scaling is B/M/K with `groupDigits`.

**The open row (`bearFigures`):**
- **The figures,** from `value` with UI labels:
  - dilution: shares now and a year earlier, each with `plainDay` of its date;
  - margin: the trailing and prior margins, and one row per quarter (`30 Jun 2026 · 41.2%`);
  - net cash: cash, short-term investments and debt;
  - shelf: one row per filing, `S-3 · 4 Mar 2026 · Open the filing →`.
- **Quotes:** each source span (`kind: source_version` with `char_start`, `char_end` and `quote`) is a `<Quote>`. Its `Open in source →` goes to `routes.spanAt(source_version_id, char_start, char_end, parser_version)`.
- A filing source without a span is `Open the filing →` (`/version/?id=`).
- Observation sources render nothing here: the figures already show them.

**The viewer's span path.** `app/version/page.tsx` accepts `?from=&to=&parse=`, loads that parse as it does for a reparsed Assertion, and highlights with the existing `splitAtSpan`. The note reads `Quoted passage · <form> · filed <day>`. `?assertion=` keeps priority, and the offsets appear only in the href and in Provenance.

**Records.** The company page's existing `<RecordsFold>` gains `Bear checks: how each was read`: per check its label, `basis` verbatim and the concept names, and the as-of time (`exact`).

**Empty or failed.**
- A 404 (an older backend) or a failed read hides the section, with no error line.
- A company with no filings shows six Unknown rows and `6 unknown`: honest, and shown.

**Height:** about 200 px at 1440 (three rows of two) and about 300 px at 390. The company page stays ≤ 2,000 px at 1440.

### 10.7 Backend tickets for the lead

- **B6 (should-have).** `GET /chokepoints/{id}` should resolve its evidence:
  - `facts[]` (`id, assertion_id, statement, quote, company_name, document_title, available_at, source_version_id`);
  - `leads[]` (`id, title, url, origin, published_at`);
  - `issues[]` (`id, title, status`).

  Leads then link, and the page reads nothing else.
- **B7.** `Holder` gains `company_id` when it resolves. The UI's slug/CIK/name match then goes.
- **B8 (must-have before the bear checks leave the runtime guard).** `CheckKey` and `CheckStatus` go into the OpenAPI schema. `value` gets one typed model per key (the fields of §10.6, with `customer_concentration` and `going_concern` pinned). Two fields are added: `unknown_reason`, an enum such as `form_not_collected`, `no_xbrl`, `not_comparable` or `no_statement`, and an owner-facing `summary`.
- **B9 (must-have before W2's first run).** The Watch prompt carries the owner's writing rules:
  - no ids, enum codes, step letters, commands, job or tool names, times of day or code blocks;
  - steps named in words;
  - http(s) links only for sources, and `atlas:chokepoint/<id>` for the board;
  - the shape: a lead paragraph of one or two sentences on what changed on the board, then the watch spec's four headed sections (discoveries, rejections, changes, next questions).
- **B10.** Once W6a lands, decide whether `ThemeSummary.empty_layers` stays the `CompanyLayer` enum. The UI already falls back through `layerName`.
- **B11.** Decide whether a theme with no companies appears in `GET /themes`. Both cases are designed (§10.3.1).
- **B12.** `Chokepoint.status_set_at`, which the fold already knows. Today's line 2 and the page's `since` then read it.
- **B13.** The open-question gate. Either the gate counts a linked Issue whether open or answered, or completing a chokepoint's last open Issue requires linking the next. Until then the UI mutes the open-question-only case (Z5).
- **B14 (optional).** Board counts on `ThemeSummary`, or `GET /chokepoints/counts`. `list_chokepoints` folds every chokepoint before slicing, and Today pays that on every load.

### 10.8 e2e

**Seeding** (`scripts/e2e.py`, `seed_board(base_url)`, with `httpx` against the first served API, after `running_api` and before Playwright; public routes only):
1. **Look up ids.** `GET /companies` gives the Lumentum id. `GET /facts?session_id=<the seeded session>` gives its two Facts (Lumentum's March 2026 10-Q).
2. **Issues.** `POST /issues` five times (I1 to I5) for theme `photonics`, so `issues.spec`'s seeded Issues are left as they are.
3. **One session.** `POST /sessions {theme: "photonics", question, as_of: now, seed_company_ids: [lumentum], actor: "e2e-watch"}`. As-of must be now, because events refuse a session more than 36 h old (`not_prospective`).
   - The session creates A and writes one event, then closes.
   - Every other write omits `session_id`.
   - `sessions.spec`'s `2 Facts` still holds, since this run adds no Fact.
4. **A, thesis-ready.** `constraint: "Indium phosphide laser capacity"`, `layer: "laser"`, holders Lumentum (slug) and `Outside Holder Co`. Then:
   - steps a, b and d `primary` with the two Facts;
   - e `lead` with I1;
   - `field_set` with `kill_criteria`, `add_issue_ids: [I1]`, `crowding: "early"` and `relief_horizon`;
   - status `candidate`, then `thesis_ready`.
5. **B, below the bar.** Built like A, linked to I2. Then `field_set {kill_criteria: []}`. The payload refuses null but accepts an empty list. The thesis-ready lock (`thesis_ready_step_locked`, `chokepoints/service.py`) applies only to a `step_set` of a, b or d, so this is a valid route to the warn case.
6. **F, no open question.** Built like A, linked to I3 only. Then `POST /issues/{I3}/complete`: the muted case.
7. **C, candidate.** Step f `contradicted` with a Fact, and step c `lead` with I4 only (H2's `Unquoted` backed by an Issue).
8. **D, ruled out.** Status `killed`, with the reason `Supply added faster than demand.`
9. **E, spotted.** No holders.
10. **Robotics.** `POST /watch-runs {theme: "robotics", mode: "architect", run_date: today, memo: CLEAN}`, plus one robotics chokepoint. `robotics` is not in the e2e universe.
11. **Photonics.** `POST /watch-runs {theme: "photonics", mode: "delta", run_date: today, memo: DIRTY}`. `DIRTY` holds:
    - a heading, a paragraph and a list;
    - `**bold**`;
    - `[ok](https://example.com)` and `[bad](javascript:window.__pwned=1)`;
    - `[A](atlas:chokepoint/<A's id>)`;
    - `<script>window.__pwned=1</script>`;
    - a fenced block holding `uv run atlas ingest --company x`;
    - inline `` `thesis_ready` `` and the prose `step d`;
    - a bare UUID mid-sentence.
12. **Memory-packaging** gets nothing: the empty-state control.

Stale is clock-derived, so it is covered by `unit/chokepoints.test.ts` on `unit/fixtures/board.json` (a real board answer) with a fixed `now`.

**New `e2e/watch.spec.ts`:**
- **Today:**
  - The `Watch` region has a Robotics row (`First survey`) and a Photonics row (no mode word).
  - The photonics row's line 2 starts `Thesis-ready:` and links a thesis-ready chokepoint (A, B or F) by name. Clicking it lands on `/chokepoint/?id=`.
  - There is no Memory packaging row and no robotics card.
  - `Memo` opens `/watch-run/?id=`.
- **The memo page:**
  - `window.__pwned` is undefined, and `main` has no `script` element.
  - `<script>` shows as literal text.
  - `bad` is text; `ok` is a link with `noopener`.
  - `A` links to `/chokepoint/?id=`.
  - `main` contains no `uv run` and no UUID. It reads `thesis-ready` and `Control`, never `thesis_ready` or `step d`, and has no double space where the UUID was.
- **Theme photonics:**
  - `Chokepoints` comes after `Changed` and before `Companies`.
  - The groups read `Thesis-ready (3)`, `Candidates (1)` and `Spotted (1)`.
  - B shows `Below the bar`, and F shows `No open question`.
  - `Ruled out (1)` is closed and renders no row until it is opened.
  - The pips' accessible names read `Constraint: quoted`, …, `Relief: not examined`.
  - Rows carry no status word.
- **`/theme?id=robotics`:** the h1 is `Robotics`, the status line starts `Watching`, the board leads, and nothing reads `not one of the themes`.
- **`/theme?id=memory-packaging`:** no `Chokepoints` region and no `Watch` text. Height as before.
- **A:**
  - `Waiting for proof` shows, and `Still needs` does not.
  - Opening `Constraint` and clicking `Open in source` lands on `/version/?id=…&assertion=<fact.assertion.id>` with the span highlighted. The only navigation clicks are the board row and `Open in source`.
  - `Lumentum` is a link. `Outside Holder Co` is not, and is followed by `not yet researched`.
  - On load the page makes at most 3 `GET /facts/` requests (counted with `page.on("request")`).
- **B:** `Below the bar: no falsifier` is the bar line, and the verdict still reads `Thesis-ready`.
- **F:** `No open question linked`, muted.
- **C:** Relief reads `Unquoted`.
- **D:** `Ruled out <day>: Supply added faster than demand.`

**Bear checks (with checklist item 9):**
- On the Company page (Lumentum), the `Bear checks` region has six rows in the fixed order, and the summary counts add up to 6.
- The shelf row reads `Unknown · not in the filings Atlas collects`; the fixtures hold no S-3.
- If a row has a quote, its `Open in source` lands on `/version/?id=&from=&to=&parse=` with a highlight.
- No ISO date shows above Records.

**Unit tests:**
- New:
  - `chokepoints.test.ts`: groups, the quiet order, every badge, `barLine` for each row of its table, `historyRows`, `holderView` by slug, CIK and name, `layerName`, `clampWords`.
  - `watch.test.ts`: `latestByTheme`, `namedOnBoard` (first run; window; none), `stoppedWatch` at 9 days, `todayCards` and `themeLayout` (every rule, with robotics both in and out of `/themes`).
  - `markdown.test.ts`: the draft's cases, plus the owner-words pass, UUID gap collapsing, `atlas:chokepoint/` with a valid and an invalid UUID, and a 50 KB memo in under 50 ms.
  - `bear-checks.test.ts`: the guard, every value format on fixtures copied from `tests/integration/test_bear_checks.py`'s answers, `money`, and the unknown reasons.
- Extended:
  - `status.test.ts`: enum coverage of `ChokepointStatus`, `StepStatus`, `Crowding`, `WatchMode` and `BoardFilter`, then `CheckKey` and `CheckStatus` once they are in `openapi.json`.
  - `nav.test.ts`.
  - `today.test.ts`.

### 10.9 Build checklist (in order)

1. **Words and libraries:** `status.ts` additions, `chokepoints.ts`, `watch.ts`, `markdown.ts`, `routes.ts`, `nav.ts`, and the client functions, with `scripts/gen_api_client.sh` run on the W1 schema.
   - *Accept:* the unit tests pass, including enum coverage. The markdown cases pass. `layerName("gating-equipment")` is `Gating equipment`. `gen_api_client.sh --check` is clean.
2. **Components:** `StepPips`, `ChokepointRow`, `Board`, `WatchSection`, `Memo`, and the CSS.
   - *Accept:* the pips' accessible names read `Control: unquoted`. `Board` renders null for `[]`. `Ruled out` rows are absent from the DOM until the fold opens.
3. **Theme page:** the four parallel reads, `themeLayout`, the board after Changed | Due, and the board-led layout. Themes gains the `Watching` / `Not started` cards.
   - *Accept:* photonics is pixel-equal in the empty state (1722/2904). Robotics renders board-led out of `/themes`. A zero-company theme in `/themes` reads `Not started · the first watch has not run`. Memory-packaging is unchanged.
4. **Today:** the Watch section, `todayCards`, `layerName` in the Starting lines.
   - *Accept:* Today is ≤ 999/1542 px in the empty state. A robotics theme in `/themes` with nothing in it adds no card (unit). Line 2's link reaches a chokepoint in one click.
5. **Chokepoint page.**
   - *Accept:* the two-click path from the board, at most 3 Fact reads on mount, the bar line for every state, holder matching. No CIK appears above Records.
6. **Memo page.**
   - *Accept:* the dirty memo's assertions (§10.8). Earlier runs and Records are correct.
7. **e2e seeding,** `watch.spec.ts`, and the surface-spec additions for the board pages and the memo.
   - *Accept:* `scripts/e2e.py` is green. The surface spec passes at 1440 and 390 on every new page with Records closed.
8. **Gates:** `npm --prefix frontend run lint | typecheck | test | build`.
   - *Accept:* all green.
9. **The bear checks** (last; their types arrive with the integrate branch): the viewer's `?from=&to=&parse=`, `lib/bear-checks.ts`, `<BearChecks>` and its Records table, the company page slot, and their e2e and unit tests. The runtime guard stays until B8, then the types replace it.
   - *Accept:*
     - Lumentum shows six rows in order, with counts adding to 6, and `Unknown · not in the filings Atlas collects` on the shelf row.
     - No basis text, concept name or ISO date appears above Records.
     - A quoted source lands highlighted in two clicks.
     - The company page is ≤ 2,000 px at 1440, with no sideways overflow at 390.
     - A 404 hides the section.
10. **Production acceptance** (an acceptance step, not a build item) after deploy, with Records closed and the same capture as round 2 (`.scratch/ui-review/<date>/after/`).
    - *Accept:*
      - Today is ≤ 999/1542 px.
      - Theme photonics is ≤ 1722/2904 px.
      - No `Watch` or `Chokepoints` text appears.
      - The Company page shows `Bear checks` with live rows.
      - The surface leak guard passes against production on Today, Theme and Company.
      - `docs/implementation-log.md` records the files, the tests and the heights before and after.

**Optional, after item 9:**
- On the chokepoint page, a researched holder carries its bear flag count (`AXT · 1 bear flag`), linking to the company's `#bear`. This is one bear-check read per researched holder, at most 3.
- An e2e universe with robotics in `/themes` and empty, so Z6's hidden card is covered beyond the unit test.
