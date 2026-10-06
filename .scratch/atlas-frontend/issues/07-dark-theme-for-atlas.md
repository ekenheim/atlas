# Atlas in one dark theme

Type: build
Status: resolved
Blocked by: 02

## Question

Make the whole frontend dark, one theme, no toggle (the owner, 2026-10-06): colour tokens on `:root` in `globals.css` (background, surface, raised surface, text, muted, line, accent for links and the in-memory bar, and the states `--ok`, `--warn`, `--gap`), taken from the prototype's variant D (`prototype/memory-page`, `prototype.css`, `.pm.d`); `color-scheme: dark`; tables, inputs, buttons, `mark.span`, `pre.document`, blockquotes and focus rings restyled on the tokens. Colour only, no structural change to any page (the research pages are frozen until the verdict). Check every page's contrast (WCAG AA for text) and the e2e still green; screenshots of each page before and after in the ticket's answer.

## Answer

Tokens on `:root` from variant D, `color-scheme: dark`, one theme, no toggle; tables, inputs, buttons, `mark.span`, `pre.document`, blockquotes and focus rings restyled on them.

Contrast (WCAG AA, on bg / surface / raise): text 13.97 / 12.90 / 11.96; muted 6.15 / 5.68 / 5.27; accent 9.40 / 8.69 / 8.05; ok 8.44 / 7.79 / 7.23; warn 9.11 / 8.41 / 7.80; gap 6.27 / 5.79 / 5.37; edge (borders, not text) 4.10 / 3.79 / 3.51. Text on `mark.span` 6.87. All text pairs pass AA.

Accepted restyle: `thead th` is 0.8rem on every table, following variant D, a size change beyond "colour only".

Review fixes: the hover fill only on mouse devices, none on sortable headers; a disabled button loses its strong border; `--focus` is `--accent`.

Checked by the lead on production data through a local read-only preview: `/memory/`, `/relationships/` and `/company/` render dark and readable, structure unchanged. No before/after screenshot set was kept. The full e2e against the seeded databases is the runners' (`scripts/e2e.py` crashes on Windows before seeding). The landing page's CLI hint (`app/page.tsx`) is left for ticket 06.
