# 04: Strip page-break artifacts from parsed filings

**What to build:** Filings rendered from paginated documents carry page artifacts inside sentences, for example "…in-house\n9\nTable of Contents\nsupply…". Pilot fix 03 found true quotes that couldn't be located because of them. The parser should remove running page headers and footers, page numbers and "Table of Contents" back-links when they fall between sentence fragments. Record the removal in the parse (a new parser version), so offsets stay deterministic and the archived raw bytes are untouched.

**Blocked by:** None

**Status:** ready-for-agent

- [ ] Unit tests on real-shaped fragments from the recorded Coherent and Lumentum filings: a sentence broken by a page artifact comes out whole.
- [ ] The parser version is bumped. Existing Assertions keep their spans in the old parse; new versions use the new parser. The decision entry says how re-parsing is handled.
