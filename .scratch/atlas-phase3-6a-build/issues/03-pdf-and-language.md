# 03: PDF parsing and language handling

**What to build:** Annual reports and results announcements in PDF are parsed deterministically into text with page anchors, so Assertions can cite them like HTML filings. Scanned/image-only PDFs are marked unsupported. Non-English documents are archived with their language and excluded from retention and extraction.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] A pinned PDF library and a new parser version produce identical text for identical bytes; page anchors are available to the viewer and Assertions
- [ ] An Assertion on a PDF Source Version validates its exact span (API test)
- [ ] An image-only PDF fixture gets `parse_status=unsupported`; a non-English fixture gets its `language` and no retain job
- [ ] The source viewer shows page anchors for a PDF version
