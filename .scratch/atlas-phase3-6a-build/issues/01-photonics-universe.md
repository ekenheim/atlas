# 01: Photonics universe

**What to build:** The researcher sees the 12 verified photonics companies (AXT, Soitec, IQE, Coherent, Lumentum, MACOM, STMicroelectronics, Marvell, Zhongji Innolight, Applied Optoelectronics, Fabrinet, Ciena) in the theme, each tagged with its supply-chain layer and source path (`sec`, or `exchange:<hkex|lse-rns|euronext>`). SEC CIKs that carry only unsponsored-ADR paperwork (Soitec, IQE, Innolight) are not used as filers. Seed-list research: branch `research/seed-list`.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] The theme config lists the 12 companies with layer (substrate, epi, chip/laser, DSP, module, contract manufacturing, system) and source path; STMicroelectronics uses 20-F/6-K
- [ ] `atlas companies seed` creates or updates them idempotently; the companies API returns layer and source path
- [ ] A company whose source path isn't `sec` is refused by the SEC ingest with a clear message, not fetched
- [ ] Unsponsored-ADR CIKs are absent (or explicitly marked ignored) and a test guards it
- [ ] Existing Lumentum/Coherent ingest behaviour and tests are unchanged
