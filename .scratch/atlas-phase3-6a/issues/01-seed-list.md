# Verify the photonics seed list and each company's disclosure path

Type: research
Status: resolved
Blocked by: none

## Question

For each draft seed company (Lumentum, Coherent, Fabrinet, Applied Optoelectronics, Ciena, MACOM, AXT, STMicroelectronics, Soitec, IQE, Zhongji Innolight), establish from primary sources:
- current listing(s), ticker and exchange (MIC); whether it's still independent (acquisitions or delistings since 2025)
- SEC CIK and filing type (10-K/10-Q/8-K vs 20-F/6-K vs none)
- LEI (GLEIF)
- where the company publishes primary material outside the SEC: IR press-release RSS/Atom, annual-report PDFs, their language, and robots.txt/terms for automated fetching
- its photonics layer: substrate, epi, chip, laser, module, DSP, system, contract manufacturing

Recommend 8–12 companies meeting the spec §3 rules (≥1 European SEC filer, ≥1 European non-SEC, ≥1 Asian), with reasons tied to the Bottleneck lens.

## Context

Research in progress on branch `research/seed-list`; findings in `docs/research/seed-list.md` on that branch.

## Answer

Full findings: `docs/research/seed-list.md` on branch `research/seed-list` (`bbc1021`). 28 SEC requests.

- **Recommended 12, by layer:**
  - substrate: AXT, Soitec (European, not an SEC filer)
  - epi: IQE (European, not an SEC filer)
  - lasers and chips: Coherent, Lumentum, MACOM, STMicroelectronics (European SEC filer, 20-F/6-K, US GAAP)
  - DSP: **Marvell** (added; the draft had no DSP layer)
  - modules: Zhongji Innolight (Asian), Applied Optoelectronics
  - contract manufacturing: Fabrinet
  - systems: Ciena
- **Alternates:** Tower Semiconductor, AIXTRON, Broadcom, Sivers. To trim to 10, drop Applied Optoelectronics, then MACOM.
- **No acquisitions or delistings** since 2025. IQE stays independent (moving AIM → LSE Main Market).
- **Innolight listed on HKEX in July 2026** (03308), which gives it English filings via **HKEXnews**. Its own IR site's robots.txt is `Disallow: /`. Three of its pages were fetched in one batch before robots.txt was read; that's disclosed.
- **Trap:** SEC ticker files list CIKs for Soitec, IQE and Innolight, but those are only unsponsored-ADR paperwork. None of them reports with the SEC.
- **Six US issuers' IR sites block automated fetching** (Coherent, Fabrinet, AAOI, STM, Ciena, AXT), so SEC EDGAR is their only compliant route. MACOM's terms ban bots. The IR adapter is therefore mainly for the non-SEC names, and HKEXnews/RNS need their own source adapters.
- **LEIs:** MACOM's listed holding has none; Coherent, AXT and AAOI are LAPSED.
