# The scheduled tasks' artifacts, 2026-10-19

Snapshots of the eight Chokepoint Watch artifacts, read on 2026-10-20 with the Artifact tool (`read`, `path: index.html`). Each scheduled task republishes its artifact in place every week, so these files are the only copy of edition 1 (the themes) and edition 2 (the council). They are the baseline for the rewrite check and the parser's fixtures. Never edit them.

| File | Artifact | Version | sha256 |
|---|---|---|---|
| `photonics.html` | https://claude.ai/artifact/GnQmgEjsvfpTcxCetkqy2Y | 1792446458-ad47 | 1116274ec8f09f17039e4e33205977e26c33d90ade211bbb6baf6317d8171404 |
| `memory-packaging.html` | https://claude.ai/artifact/88Qn2HQn3JPmLM3sduzFLr | 1792446436-d70b | e11baabfb71b061e58c98ffd242f9f4fe1c66722511d5cf54c55e5d261ec8c52 |
| `robotics.html` | https://claude.ai/artifact/AqneSyMHifsh29UCGdtsfU | 1792446292-8264 | f73fecea89dc90c2a07fa5e27a9e843a23f5c2a89fd8ed8fafa2299579b19e76 |
| `power-equipment.html` | https://claude.ai/artifact/CXazK5byissDyBnExmP86F | 1792446329-0c8b | 215f9c686aab7861569da8313fd653b961802c243040647397cc790bb1889f61 |
| `aerospace-defence.html` | https://claude.ai/artifact/KF3JXhEUiZZuhrkvW9dhob | 1792448442-e425 | 63f904bc15639799ad24fe52043ecf0b1558a0ab73a900855849fa5eb776782a |
| `nuclear.html` | https://claude.ai/artifact/JQ3JqTaBSb5CYZSqXR5bne | 1792448607-c3e3 | 5f51914d82fc3cb9923b8913c6024c3d5d9e975b48e66683ba8858891d703573 |
| `quantum.html` | https://claude.ai/artifact/L6y14RYdjTSEUgcsr1VGoz | 1792448349-3c9c | a546ccc8915e7574bb0d7d85d8f1a0f1c7c30a0e2aaf189e36739768cb52b943 |
| `council.html` | https://claude.ai/artifact/2g6LeHkyCNjSmKu9JBbwUD | 1792449473-0835 | c033c2791d9584eaa0751981fa9f7da75b131fd06d2b273dffbbaa8e2c1aec8f |

What the parser must handle (all eight parse with: every `<pre>`, tags stripped, HTML entities unescaped, a leading ```` ```json ```` and a trailing ```` ``` ```` stripped, `json.loads`):
- The ledger's `<pre>` has `id="ledger"` in six files, none in `robotics.html` and `power-equipment.html`. Locate by parsing, not by id.
- `power-equipment.html` has no code fences around the JSON.
- `earliest_evidence` and `consensus` are present in aerospace, nuclear and quantum only (their prompts were revised); `council_answers` in aerospace, nuclear and quantum; `notes` in nuclear only.
- The council ledger has no `primary_sources`. Its items cite theme IDs (`pho-1`, `mem-1`, ...), so its quotes are checked through the theme ledgers.
