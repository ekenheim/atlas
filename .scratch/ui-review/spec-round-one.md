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