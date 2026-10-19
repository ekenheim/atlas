# Parity on 0.6.20 (the reach fix), 2026-10-19

| Theme | Claude + skill (primary documents) | Atlas Watch on 0.6.20 (primary Facts) | Atlas before (0.6.18/0.6.19) |
|---|---|---|---|
| Robotics | 11 | 8 (MP Q2 release, Tesla Q2 update, USA Rare Earth 10-Q ×4, Microchip 10-Q ×2) | 0 |
| Power equipment | 11 | 11 (GE Vernova release, Howmet 10-Q, DPC Holdings/Doncasters 10-Q, Forgent 10-K, Cleveland-Cliffs; it found Doncasters, which the arm missed) | 1 |
| Aerospace and defence (blind; first run for both) | 15 | 6 Facts from 3 documents (NewMarket 10-K and 10-Q, the Ursa Major deck, Howmet 10-Q) | — |

**Aerospace:** the arm's first chokepoint, solid rocket motor capacity for PAC-3 and THAAD (Lockheed's 600 to 2,000 a year, L3Harris's $4.7B and fourfold THAAD frameworks, the Department of War's $1B stake), is absent from Atlas's board. Ammonium perchlorate is Atlas's top chokepoint; the arm rejected it on the same NewMarket 10-K ("sufficient"; a line adding more than 50% due in 2026). The lead checked 15 of the arm's quotes against the downloaded documents: all are verbatim.

**Why:** finding, then reach. L3Harris's and GE's 8-Ks and 10-Qs were reachable on EDGAR but not found; the run made one `web_search`. war.gov, Lockheed, L3Harris, GE Aerospace and Safran were not in the site register. Atlas also lost 18 `record_fact` calls across the three runs to `statement_beyond_quote`.

**Next:** W10 (the Watch gets Claude Code's WebSearch for finding) and W10b (the defence sites in the register) as 0.6.21, then aerospace again against the same answer.
