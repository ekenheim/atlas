# 08: A pointer lands on the passage its fact came from

**What to build:** When Memory points at a long section, the Investigator and the Skeptic read the window the fact was extracted from, not the window whose words happen to match the fact's text best.

Spec: `.scratch/atlas-memory-quality/spec.md` ("Chunk-exact pointers"). Recordings: ticket 01 (`include.chunks`, and whether a chunk's text is a verbatim slice of the retained content). If ticket 01 found that it is not, this ticket is closed as not built, with the reason, and nothing else changes.

- Pointer recalls ask for the chunks of their results. A pointer whose memory has a chunk that occurs verbatim in the pointed section records that chunk's span in the section (`placed_by` `chunk`); otherwise the best-match window stands (`placed_by` `match`), as today.
- Passage selection takes a chunk-placed pointer's window from the span: the selection window that contains the span's start, extended by the existing rule when the span crosses a window.
- The investigation read, the card's `read` and the Evidence tray's `passage_selected_by` say which rule placed a pointer.
- An observation's pointer is placed by its source fact's chunk.
- `docs/decisions.md`: the placing rule, and that a chunk is located, never quoted.

Migration revision `0065` (down: main's head).

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] Integration test at the investigation seam: a section of several windows where the fact's words match one window best but its chunk lies in another; the passage read is the chunk's window, and the pointer says `chunk`.
- [ ] A chunk that does not occur verbatim leaves the pointer on the best-match window with `match`.
- [ ] The Skeptic's pointers are placed the same way.
- [ ] Decision entry; `AGENTS.md` line; API client regenerated.
