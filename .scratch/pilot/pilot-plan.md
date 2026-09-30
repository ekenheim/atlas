# Research pilot: five photonics investigations

The goal is to measure research usefulness, not traceability (the Codex review, 2026-09-30). Each investigation runs on production (`atlas.ekenhome.se`) with the 0.2.1 bottleneck-method prompts. Every substantive conclusion is then reviewed, and for each one we record:
- **Saved work:** a finding that was correct and useful, with a cited primary span, that would have taken manual reading to find.
- **Missed evidence:** something in the archived filings that answers the question, but that Atlas didn't surface. Checked by a spot search of the archive.
- **Unsupported or wrong:** a finding whose citation doesn't support it, a wrong direction or layer, or an overreach.
- **Corrections needed:** what the owner or the lead had to change.
- **Cost and latency:** tokens (MiniMax, and Codex through Hindsight), wall time, stop reason.

| # | Question (Serenity-style, multi-hop) | Seed companies | When |
|---|---|---|---|
| 1 | For 800G/1.6T AI transceivers, who supplies the laser chips (EML, CW/DFB, VCSEL), who is capacity- or allocation-constrained, and what feedstock or equipment (InP substrates, MOCVD) limits them? | Lumentum, Coherent | now (both fully ingested) |
| 2 | Is indium phosphide substrate supply a chokepoint for optical laser chips: who makes it, how concentrated is it, and do export controls (gallium, germanium, indium) bind? | AXT, Coherent, Lumentum | after the rollout's first nights |
| 3 | Where is transceiver module assembly constrained: contract manufacturing and module capacity, customer concentration, and qualification cycles? | Fabrinet, Applied Optoelectronics, Coherent | after the rollout |
| 4 | Is the DSP/driver layer a chokepoint for 1.6T modules: who supplies, how many qualified sources, and what are the technology transitions (LPO, CPO)? | Marvell, MACOM | after the rollout |
| 5 | How does coherent-optics and systems demand (DCI, 800ZR) pull on component supply, and where does it bind? | Ciena, Lumentum, Coherent | after the rollout |

Results go in `.scratch/pilot/results.md` (one section per investigation) and are summarized in `docs/implementation-log.md`.
