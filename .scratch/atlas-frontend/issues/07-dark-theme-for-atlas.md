# Atlas in one dark theme

Type: build
Status: open
Blocked by: 02

## Question

Make the whole frontend dark, one theme, no toggle (the owner, 2026-10-06): colour tokens on `:root` in `globals.css` (background, surface, raised surface, text, muted, line, accent for links and the in-memory bar, and the states `--ok`, `--warn`, `--gap`), taken from the prototype's variant D (`prototype/memory-page`, `prototype.css`, `.pm.d`); `color-scheme: dark`; tables, inputs, buttons, `mark.span`, `pre.document`, blockquotes and focus rings restyled on the tokens. Colour only, no structural change to any page (the research pages are frozen until the verdict). Check every page's contrast (WCAG AA for text) and the e2e still green; screenshots of each page before and after in the ticket's answer.
