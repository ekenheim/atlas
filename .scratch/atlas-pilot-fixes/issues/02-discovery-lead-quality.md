# 02: Discovery lead quality: English results, relevance ranking

**What to build:** In pilot investigation 1, the Scout's 10 queries were good and layer-tagged, but the 10 leads kept out of 100 were junk: dictionary entries for "coherent", Wikipedia, and Swedish-language pages. Two fixes:
1. SearXNG requests send `language=en`, configurable with `ATLAS_SEARXNG_LANGUAGE`.
2. Lead ranking scores each result for relevance to its query and purpose: overlap of query terms in the title and snippet, named companies, and product and layer terms. It demotes known low-value hosts (dictionaries, encyclopedias, broker quote pages) through a configurable deny or demote list. Investigations take the top-ranked leads, not the first ones.

**Blocked by:** None

**Status:** done

- [x] The SearXNG client sends the language; a unit test checks it.
- [x] The ranking is a pure function with unit tests: a dictionary or encyclopedia page ranks below an on-topic industry article for the same query.
- [x] An investigation's `leads` shows each lead's score and why it was kept. Integration test at the investigation seam, with the SearXNG fake.

Owner direction (during the build): English everywhere. `ATLAS_SEARXNG_LANGUAGE` defaults to `en` and is validated as a language code (never empty); every search sends it; non-English results rank below English ones for the same query.
