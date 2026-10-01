# 20: One-word filing phrases make off-theme Candidates

**What to build:** In investigation 1 on 0.2.5 (discovery `ca235cf4-e60c-408e-a8a8-83fc6f43dd43`, `propose_candidates` job `4c4ccf3c-7aa1-5070-961b-1bb19da76a0f`), the Scout (`scout.v3`) wrote a filing phrase for each of its 10 queries, and EDGAR full-text search proposed production's first 16 Candidates. About 5 are on the theme (Aeluma, Veeco, Tower Semiconductor, Axcelis, Semilux). The rest come from phrases that are one word or generic: `"VCSEL"`, `"CW laser"`, `"MOCVD"`, `"export controls"` find lidar makers (Hesai, Ouster), medical lasers (IRIDEX), Applied Energetics, Mesa Laboratories, NOVONIX, ECARX and Super Micro. The specific phrases (`"InP substrates"`, `"200G EML"`, `"EML chip"`, `"epiwafer"`, `"GaAs substrates"`) found the useful filers. No EDGAR lead made the investigation's top 10, so the channel's only visible output was the Candidates.

Decide and build:
- What a filing phrase must be: at least two words or a term of the theme's product and layer list; a generic phrase is searched together with a second theme term, or not at all.
- Whether a filer becomes a Candidate from one hit, or only when its hit also passes lead ranking above the kept threshold (ranking v2 scores filing leads against the phrase alone today).
- NVIDIA, already a counterparty company, was proposed as a Candidate: say whether that is the intended promotion path or a duplicate to suppress.

**Blocked by:** None

**Status:** superseded by `.scratch/atlas-memory-directed-reading/issues/`, ticket 04 (Specific filing phrases); this file keeps the evidence

- [ ] The decision in `docs/decisions.md`, with this discovery's phrases and filers as the evidence.
- [ ] At the discovery seam with the EDGAR fake: a one-word phrase proposes no Candidate on its own; `"InP substrates"` still proposes Aeluma.
