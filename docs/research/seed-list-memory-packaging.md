# Memory and packaging seed list: identity, disclosure paths and layers

Researched 2026-10-05 against primary sources only, as preparation for a second theme (nothing in this document is in the live config):
- SEC `company_tickers.json`, `data.sec.gov/submissions` and the filings themselves (User-Agent `Atlas Research ekenheim@gmail.com`; **44 SEC requests in total**: the ticker file, 23 submissions files, 20 documents)
- the latest 10-K, 20-F or prospectus of each SEC filer, read as text
- the GLEIF API (`/lei-records`, full-text and name filters)
- the FCA National Storage Mechanism search API and one document it links (18 requests)
- company IR sites and their `robots.txt`; the documents those allowed

Statements not marked otherwise were read in a source that day. **Unverified** marks anything I couldn't confirm from a primary source; **prior knowledge** marks what I believe but did not read. Where a page was read through a summarising fetch tool rather than as text, I say so.

*Disclosure:* the 18 requests to `api.data.fca.org.uk` and `data.fca.org.uk` went out with a User-Agent that carried the contact e-mail (`Atlas Research (ekenheim@gmail.com)`), against the brief's rule that only SEC hosts get it. Every other non-SEC request used `AtlasResearch/0.1 (manual research fetch)`. Nothing else was sent anywhere.

## Headline findings

1. **SK hynix is now an SEC foreign private issuer.** CIK 2120882 holds an F-1 (2026-06-24), the 424B4 prospectus (2026-07-10: 177,900,000 ADSs at US$149.00, each ADS one-tenth of a common share, "approved to list the ADSs on the Nasdaq Global Select Market … under the symbol 'SKHY'"; the common shares stay on "the KRX KOSPI Market … under the identification code '000660'"), an 8-A12B and 21 6-Ks since. No 20-F yet: the first is for FY2026 (due in 2027, **inference**). The prospectus already carries the theme's best bottleneck language: "In recent quarters, demand for our products has exceeded our available supply", "the lead times from order to delivery of such equipment can be over one year", and "our largest customer represented 23.9% of our total revenue in 2025". The HBM maker with the largest share is reachable through the `sec` path today.
2. **Samsung Electronics' English Business Report is on the FCA National Storage Mechanism**, because its GDRs are listed in London ("Name of stock exchange: London Stock Exchange (common stock)", conversion 1:25, read in the report). The NSM lists seven documents for LEI 9884007ER46L6N7EI764: six Annual Financial Reports (latest submitted 2026-04-30, the "2025 Business Report" for the year ended 2025-12-31, 21.9 MB of inline-XBRL HTML inside an ESEF zip) and one prospectus (2025-02-12). Atlas's `fca-nsm` adapter already reaches this host, but it **skips ESEF packages** (`backend/atlas/sources/fca_nsm.py`: "Only HTML and PDF documents are candidates (ESEF packages and other files are skipped)"). The NSM row also gives an `html_link` to the report served unzipped (`NSM/DirectUpload/NI-000144031/reports/9884007ER46L6N7EI764-2025-12-31-T01_ixbrl.html`), so a small adapter change (take `html_link` when `ProcessType` is `ESEF`) would make Samsung's annual disclosure a fetchable Source Version. Quarterly disclosure stays on DART and samsung.com (manual imports).
3. **Samsung's report is the one document that gives a memory maker's capacity in units**: "Memory 2,245,908,090" thousand 1Gb-equivalents for 2025 (2,238,240,405 in 2024), "converted output (after packaging, 1Gb equivalent) ÷ the utilization rate", plus a DRAM revenue share series (34.0% in 2025, 41.5% in 2024, 42.2% in 2023, "data from research firm DRAMeXchange") and wafer suppliers ("SILTRONIC, SK Siltron, etc."). Micron's and SK hynix's filings give no such figure.
4. **The package-substrate layer is where the issuers themselves name a shortage.** ASE's 20-F: "Raw materials such as IC substrates are prone to supply shortages since such materials are produced by a limited number of suppliers, such as Kinsus Interconnect Technology Corporation, Nan Ya Printed Circuit Board Corporation, and Unimicron Technology Corporation" and "the Ajinomoto Build-up Film (ABF) substrate, a crucial component for manufacturing high-performance chips, may face a higher risk of supply shortages or extended lead times". Ibiden's FY2025 results presentation (11 May 2026): "As IC package substrates become larger and more multi-layered, total SAP demands are expected to exceed the industry's supply capacity." None of the substrate makers files with the SEC; Ibiden, Unimicron and AT&S are manual-import companies, and Shinko is gone (finding 7).
5. **The ticker-file trap recurs, five times.** `company_tickers.json` maps ATEYY/ADTTF → Advantest (CIK 1158838: last 20-F 2015, an F-6 in 2026), KXIAY/KXHCF → Kioxia (CIK 2053383: five F-6EFs and nothing else), IBIDF → Ibiden (CIK 1654508: F-6EF/F-6 POS only), THNBY → Technoprobe (CIK 1971172: one F-6EF) and DISPF → Disco. None is an SEC filer. SKHY, by contrast, is real (finding 1), and ASX (ASE), TSM, CAMT, NVMI, SIMO and IMOS are 20-F filers. Samsung, BESI, ASMPT, Hanmi, Nanya, Powertech, Unimicron, AT&S, Shinko, Ajinomoto, Resonac and Phison are not in the ticker file at all.
6. **The disk-drive makers are out of the theme.** Western Digital's FY2026 10-K (filed 2026-08-14) describes a company "based on hard disk drive ('HDD') technology" after "the separation of our former flash-based products ('Flash') business in 2025" (completed 2025-02-21; SanDisk's 10-K: "As of February 21, 2025, we separated from WDC"). Seagate's 10-K is HAMR and HDD. Both are dropped; the NAND exposure sits in SanDisk (CIK 2023554, 10-K filed 2026-08-17), whose flash "is obtained from our joint ventures with Kioxia".
7. **Structural events since 2025-01-01.** Shinko Electric Industries' LEI is **RETIRED** in GLEIF with successor entity "JICC-04株式会社" (the JIC take-private; delisting is **prior knowledge**, consistent with the LEI record): drop it. Onto Innovation closed two acquisitions (Semilab USA, Q4 2025; a 27% stake in Rigaku Holdings for about $720 million on 2026-08-10, 8-K Item 2.01). ASMPT completed the disposal of ASMPT NEXX, Inc. on 3 June 2026 (interim results). Resonac is spinning off its petrochemical business (Crasus Chemical, "scheduled for October 1, 2026", Q2 FY2026 summary). Kioxia listed on the TSE Prime Market on 2024-12-18 (annual securities report); Toshiba still held 17.59% at 2026-03-31. Technoprobe moved from Euronext Growth Milan to Euronext Milan on 2023-05-02 and sold 2.5% to Advantest Europe in January 2025 (annual report). No seed on the recommended list has an 8-K Item 2.01 or a Form 25 since 2025.
8. **LEIs.** Missing: Hanmi Semiconductor (no record found under the English or Korean name; only a US ETF named after it) and ChipMOS. Lapsed: SK hynix (988400XAIK6XISWQV045, lapsed 2025-11-17), Silicon Motion (2020), FormFactor (2017), Aehr (2020), Nanya (2019), Powertech (2025-09-03), Western Digital (2025-06-20). The resolver's rule from the photonics research holds: accept LAPSED, never require an LEI.
9. **Customer concentration gives the first edges for free.** FormFactor → SK hynix 22.9% of FY2025 revenue; Amkor → Apple 29.8% and Qualcomm 11.1%; Kioxia → "Apple Group 476,014" million yen of FY2025 revenue of 2,337.6 billion (about 20%, my arithmetic); Silicon Motion → Micron, Kioxia, PHISEMI, AFASTOR (each >10%); Rambus sells interface chips "to major DRAM manufacturers, Micron, Samsung and SK hynix"; Technoprobe's first customer 27.6%; TSMC's largest 19% and second 17%; Micron's one customer 17% (unnamed); AT&S "generates more than 80% of its revenue with US companies" and names "a key customer for high-end IC substrates" (exchange-hosted release, read through a summarising fetch).
10. **The HBM-equipment chokepoint is poorly disclosed by the US filers and well disclosed by the Asian and European ones.** Kulicke & Soffa's FY2025 10-K mentions HBM only in an export-control sentence; Onto's 10-K not at all. ASMPT's H1 2026 interim results give TCB bulk orders ("new bulk orders for more than 50 of its C2S TCB tools from OSAT customers") and the HBM dependency ("the timing of customers' new tool purchase decisions remains dependent on HBM4 product rollout schedules"); BESI's Q2-26 release attributes growth "particularly [to] hybrid bonding"; Camtek's 20-F says "Approximately 50% of our revenues are generated from products supporting the production of artificial intelligence ('AI') applications", including HBM. Hanmi's documents could not be read at all (site 403).

## A layer taxonomy for the theme

Nine layers, in the photonics style (one line each, with the terms a document would use; these would become the theme's layer terms).

| Layer | What belongs | Terms a document uses |
|---|---|---|
| `memory-dram` | DRAM and HBM makers; the wafer fabs and the TSV/stack lines | DRAM, HBM, HBM3E, HBM4, TSV, DDR5, LPDDR5X, GDDR7, 1-beta, 1-gamma, bit growth, wafer input |
| `memory-nand` | NAND flash makers and their JVs; enterprise SSDs | NAND, 3D NAND, BiCS, QLC, TLC, enterprise SSD, Flash Ventures, HBF |
| `controller` | NAND controllers, memory-interface and signal-integrity chips (fabless) | SSD controller, NAND flash controller, RCD, MRCD, DDR5 interface, CXL, PMIC |
| `bond-equipment` | Die-attach, thermo-compression, hybrid and wire bonders; HBM stacking tools | TC bonder, TCB, thermo-compression bonding, hybrid bonding, fluxless, MR-MUF, die attach, chip-to-wafer, C2W, C2S |
| `process-control` | Inspection and metrology for wafers, bumps, stacks and panels | inspection, metrology, bump, overlay, 2D/3D inspection, advanced packaging metrology |
| `test` | ATE, probe cards, burn-in, test handlers | tester, ATE, memory tester, probe card, MEMS probe, wafer-level burn-in, known-good die, KGD, final test |
| `osat` | Assembly and test services, and foundry packaging | OSAT, CoWoS, SoIC, 2.5D, 3D IC, interposer, fan-out, FOCoS, flip chip, wafer bumping, HDFO |
| `package-substrate` | IC package substrates and the laminates under them | IC substrate, package substrate, FCBGA, build-up layers, SAP, ABF substrate, panel-level, glass core |
| `package-materials` | Build-up film, underfill, molding compound, die-attach film, bonding wire | ABF, build-up film, NCF, underfill, EMC, molding compound, die bonding film, gold wire, copper wire |

Overlaps to record:
- **With photonics:** the photonics theme's `substrate` means InP/GaAs wafers; this theme's `package-substrate` is organic laminate. Keep the names distinct so a layer term never matches across themes. BESI's and ASMPT's photonics and CPO lines (ASMPT: "ultra-high precision photonics, TCB and hybrid bonding" for CPO) are the real overlap: the same bonders assemble optical engines. Marvell/Broadcom DSPs are on the logic side of both themes but belong to neither list.
- **With a future "semiconductor materials, substrates and manufacturing tools" theme:** `bond-equipment`, `process-control`, `test` and `package-materials` would move there, or be shared. If that theme comes first, this one keeps `memory-dram`, `memory-nand`, `controller`, `osat` and `package-substrate` and reads the tool makers as counterparties.

## Per-company tables

MICs used: XNAS (Nasdaq), XNYS (NYSE), XKRX (Korea Exchange KOSPI), XTKS/XJPX (Tokyo Stock Exchange), XTAI (TWSE), XHKG (HKEX), XAMS (Euronext Amsterdam), XMIL (Euronext Milan), XWBO (Vienna), XTAE (Tel Aviv). TradingView symbols are **Unverified** throughout: I did not query TradingView; the form given is the exchange prefix TradingView uses for each market, from prior knowledge.

### Micron Technology, Inc. (`memory-dram`, `memory-nand`)

| Field | Value |
|---|---|
| Listing | MU, Nasdaq (XNAS). Independent: no Item 2.01 8-K or Form 25 since 2025. |
| SEC | CIK 723125, 10-K/10-Q/8-K, FYE early September. Latest 10-K filed 2025-10-03 (FY ended 2025-08-28); the FY2026 10-K was not yet filed on 2026-10-05. Latest 10-Q filed 2026-06-25 (quarter ended 2026-05-28). |
| LEI | B3DXGBC8GAIYWI2Z0172 (ISSUED, renews 2027-02-11) |
| Reports | SEC. English. TradingView `NASDAQ:MU` (Unverified). |
| Layer evidence | 10-K: "Cloud Memory Business Unit ('CMBU'): Focused on memory solutions for large hyperscale cloud customers, and HBM for all data center customers"; HBM defined as "A 3D stacked DRAM architecture that utilizes through-silicon via ('TSV') connections". Concentration: "Revenue from one customer was 17% (primarily included in the CMBU segment) of total revenue for 2025"; "approximately one-half of our total revenue was from our top ten customers". Supply: the 10-Q says "demand for memory and storage at a rate greater than our ability and the industry's ability to increase supply. This has led to decisions on supply allocation", and introduces "Strategic Customer Agreements" with "structurally constrained supply growth". Materials: "only a limited number of suppliers are capable of delivering certain raw materials"; the 10-K lists "substrates, lead frames" among single- or sole-sourced inputs. |

### SK hynix Inc. (`memory-dram`, `memory-nand`; SEC foreign private issuer, Asian)

| Field | Value |
|---|---|
| Listing | 000660, KRX KOSPI (XKRX); ADSs SKHY on Nasdaq Global Select (XNAS) since the July 2026 offering (424B4 filed 2026-07-10). OTC HXSCL. Independent. |
| SEC | CIK 2120882 (created 2026-03-24). Forms so far: DRS, F-1, F-1/A, 424B4, 8-A12B, F-6, 21 × 6-K. **No 20-F yet** (first expected for FY2026; inference). The 6-Ks carry the quarterly results. |
| LEI | 988400XAIK6XISWQV045 (에스케이하이닉스 주식회사 / SK HYNIX INC., KR), **LAPSED** 2025-11-17 |
| Reports | SEC (prospectus and 6-Ks). English. The Korean originals are on DART. `www.skhynix.com` robots: `Disallow: /etc`, `Allow: /`. TradingView `KRX:000660` or `NASDAQ:SKHY` (Unverified). |
| Layer evidence | 424B4: "In the HBM market, we were ranked first globally based on revenue with a market share of 56.4%" (IDC, Q1 2026); "we began the development of core technologies used in HBM production such as TSV packaging technology and MR-MUF"; "In June 2026, we announced a technology partnership with NVIDIA Corporation … which also includes the supply of memory semiconductors". Concentration: "Our two largest customers represented 14.8% and 12.4%, respectively, of our total revenue in the first quarter of 2026 and our largest customer represented 23.9% of our total revenue in 2025". Supply and equipment: "In recent quarters, demand for our products has exceeded our available supply"; "the lead times from order to delivery of such equipment can be over one year. We seek to manage this process through the early reservation of appropriate delivery slots"; "Wafers are the most significant raw material in terms of cost, representing approximately 10% of our cost of sales"; raw materials "include substrates, gold wire, wafer backside lamination tape and printed circuit boards". No bonder vendor is named (no "Hanmi", no "TSMC"). |

### Samsung Electronics Co., Ltd. (`memory-dram`, `memory-nand`; Asian, not an SEC filer)

| Field | Value |
|---|---|
| Listing | 005930, KRX KOSPI (XKRX; common and preferred). GDRs on the London Stock Exchange (common and preferred; 1 GDR = 25 shares), read in the Business Report. Not in `company_tickers.json`. Independent. |
| SEC | **None.** |
| LEI | 9884007ER46L6N7EI764 (삼성전자(주), KR, ISSUED, renews 2026-10-31) |
| Regulator path | **FCA NSM** (verified): seven documents for the LEI, six "Annual Financial Report" uploads (latest `NI-000144031`, submitted 2026-04-30, publication 2026-04-30T06:35Z, `ProcessType: ESEF`, `document_format: Tagged`) and a 2025-02-12 prospectus. The 2025 upload is a zip whose `reports/9884007ER46L6N7EI764-2025-12-31-T01.html` is the full English **2025 Business Report** (sections I Corporate Overview to XI Other Information, 1.5 M characters of text). The NSM row's `html_link` serves the same HTML unzipped. Quarterly results: DART (Korean, with English summaries) and samsung.com; **Unverified** which quarterly documents exist in English. |
| robots / terms | `www.samsung.com` robots: allows most paths, disallows search and some regional paths. NSM terms allow use (site register, `fca-nsm`). TradingView `KRX:005930` (Unverified). |
| Layer evidence | Business Report: "In the Memory Business, under low inventory levels and supply constraints, we expanded HBM sales"; "For DRAM, we plan to actively address customer demand with the timely and expanded supply of competitive HBM4 targeting new GPU and ASIC markets"; DRAM revenue share 34.0% (2025), 41.5% (2024), 42.2% (2023); memory capacity "2,245,908,090" thousand 1Gb-equivalents in 2025; "major customers (listed alphabetically) included Alphabet, Apple, Deutsche Telekom, Hong Kong Techtronics, and Supreme Electronics. Sales to the five major customers accounted for approximately 15% of total sales"; DS Division wafer suppliers "SILTRONIC, SK Siltron, etc.". |

### Sandisk Corporation (`memory-nand`)

| Field | Value |
|---|---|
| Listing | SNDK, Nasdaq Global Select (XNAS). Independent since the separation from Western Digital on 2025-02-21 (10-12B/A filings in January 2025; the 10-K: "As of February 21, 2025, we separated from WDC … and became a standalone publicly traded company"). A 424B4 on 2025-06-06 and 424B7s are secondary offerings (**Unverified** by whom). |
| SEC | CIK 2023554, 10-K/10-Q/8-K, FYE early July. 10-K filed 2026-08-17 (FY ended 2026-07-03). |
| LEI | 5299007I9R9N3RO43S32 (SANDISK CORPORATION, US, ISSUED, renews 2027-05-27) |
| Reports | SEC. English. TradingView `NASDAQ:SNDK` (Unverified). |
| Layer evidence | 10-K: "All of our flash-based memory is obtained from our joint ventures with Kioxia, which provide us with leading-edge, high-quality flash memory wafers"; competitors named "Kioxia, Micron Technology, Inc., Samsung Electronics Co., Ltd., SK Hynix, Inc., Yangtze Memory Technologies Co., Ltd."; "For 2026, 2025 and 2024, no customer accounted for more than 10% of our net revenue"; "many of our enterprise-grade SSD products incorporate DRAM, which is a commodity component that has experienced supply constraints"; "we source some of our components from a limited number of sole or single source providers". |

### Kioxia Holdings Corporation (`memory-nand`; Asian, not an SEC filer)

| Field | Value |
|---|---|
| Listing | 285A, TSE Prime (XJPX): "The Company's stock was listed on the Tokyo Stock Exchange Prime Market on December 18, 2024" (annual securities report). OTC KXIAY/KXHCF are unsponsored ADRs (CIK 2053383 holds only F-6EFs, the latest 2026-10-01). Independent; Toshiba held 17.59% and Bain-advised funds "a substantial number of shares" at 2026-03-31. |
| SEC | **None.** |
| LEI | 35380080RTKRARNH4R73 (キオクシアホールディングス株式会社, JP, ISSUED, renews 2027-08-26) |
| Reports | English **Annual Securities Report FY2025** (year ended 2026-03-31; `kioxia-holdings.com/content/dam/kioxia-hd/en-jp/ir/library/securities/asset/Annual-Securities-Report-FY2025-EN.pdf`, 107 pages), English earnings releases and presentations (the IR library pages are JavaScript-rendered; the Q1 FY2026 release of 2026-07-31 was found as an SGX corporate announcement, `links.sgx.com`, which I did not fetch because its robots.txt redirects to an error page). `www.kioxia-holdings.com` robots: disallows `/*/contact/` and `/*/search/` only. TradingView `TSE:285A` (Unverified). |
| Layer evidence | Securities report: "Revenue for the fiscal year ended March 31, 2026 was 2,337.6 billion yen, an increase of 631.2 billion yen … primarily due to a significant increase in ASPs following strong demand from generative AI-centered data center customers"; major customer "Apple Group 476,014" million yen (FY2025), Sandisk group and Dell group below 10%; "Kioxia Corporation established joint ventures with Sandisk Corporation for the purpose of strengthening NAND flash memory production". No "HBF" in the report. |

### Amkor Technology, Inc. (`osat`)

| Field | Value |
|---|---|
| Listing | AMKR, Nasdaq (XNAS). Independent. 424B7s and FWPs in 2025–26 (secondary sales; **Unverified** by whom). |
| SEC | CIK 1047127, 10-K/10-Q/8-K, FYE Dec. 10-K filed 2026-02-20; 10-Q filed 2026-07-28. |
| LEI | 529900VHLRTKPWZJBM84 (AMKOR TECHNOLOGY, INC., US, ISSUED, renews 2027-02-12) |
| Reports | SEC. English. TradingView `NASDAQ:AMKR` (Unverified). |
| Layer evidence | 10-K: "high density fan-out ('HDFO'), including SWIFT and S-Connect packaging technologies, 2.5D integration, advanced flip chip, fine pitch bumping"; "Our advanced packages may incorporate Through Silicon Via (TSV) interconnects and silicon interposers, enabling the integration of high-bandwidth memory and graphics processors into a single package". Concentration: "Our ten largest customers accounted for 72% of our net sales in 2025. Direct sales to Apple and Qualcomm accounted for 29.8% and 11.1%". Supply: "we could experience … potential shortages in equipment"; "We are a large buyer of gold and other commodity materials, including substrates and copper". Sites: the Vietnam Facility (Bac Ninh) and the Arizona Facility "under construction". |

### ASE Technology Holding Co., Ltd. (`osat`, `package-substrate`; SEC foreign private issuer, Asian)

| Field | Value |
|---|---|
| Listing | 3711, TWSE (XTAI; prior knowledge, not re-read); ADSs ASX on NYSE (XNYS). Independent. Former names "ASE Industrial Holding Co., Ltd." and "ADVANCED SEMICONDUCTOR ENGINEERING INC". |
| SEC | CIK 1122411, **20-F/6-K** (42 6-Ks since 2025). 20-F filed 2026-04-01 for FY2025. |
| LEI | 300300GO8QHPMV87NZ73 (日月光投資控股股份有限公司, TW, ISSUED, renews 2027-07-03) |
| Reports | SEC. English. TradingView `TWSE:3711` or `NYSE:ASX` (Unverified). |
| Layer evidence | 20-F: "sophisticated solutions such as 2.5D/FO-MCM/FO-EB/CoWoS/CoPoS/CoWoP/CPO/3D IC"; "leading-edge advanced packaging solutions, which have played a pivotal role in bringing advanced ASIC and HBM products to the marketplace". Concentration: "Our five largest customers together accounted for approximately 48.0%, 48.4% and 46.5% of our operating revenues in 2023, 2024, and 2025"; one customer above 10%. Supply: the IC-substrate and ABF sentences in finding 4; "Our operations, such as packaging operations, substrate operations, and EMS require that we obtain adequate supplies of raw materials" (ASE also makes substrates). |

### BE Semiconductor Industries N.V. (`bond-equipment`; European, not an SEC filer)

| Field | Value |
|---|---|
| Listing | BESI, Euronext Amsterdam (XAMS); Level 1 ADRs BESIY OTC (press release of 2026-07-23: "(Euronext Amsterdam: BESI; OTC markets: BESIY)"). Not in `company_tickers.json`. Independent (no offer or change of control seen in the 2026 releases; Applied Materials' shareholding is **prior knowledge**, not re-read). |
| SEC | **None.** |
| LEI | 7245007A1YFLI2GNYX06 (BE Semiconductor Industries N.V., NL, ISSUED, renews 2027-06-15) |
| Reports | Press releases as HTML on `besi.com` (Q2-26/H1-26 results, 2026-07-23; 2026 Investor Day, 2026-06-18; AGM 2026-04-23). Annual reports are PDFs under `/fileadmin/` or `/uploads/`, and **`robots.txt` disallows `/fileadmin/*.pdf$` and `/uploads/*.pdf$`**, so the annual report must come from the AFM register (**Unverified**: not checked) or by hand. Dutch issuer: the regulated-information path would be AFM, for which Atlas has no adapter. TradingView `EURONEXT:BESI` (Unverified). |
| Layer evidence | Q2-26 release: "Revenue of € 249.9 million grew … 68.7% vs. Q2-25 due primarily to broad based growth, particularly for hybrid bonding, photonics and datacenter applications"; "Orders of € 562.6 million rose 116.5% vs. H1-25 due to broad based growth across end-user markets with strength in photonics, hybrid bonding and datacenter computing applications"; product pages list "Hybrid Bonding: Datacon 8800 CHAMEO ultra plus AC" and "Thermo Compression Bonding: 9800 TC next". No customer concentration figure in the release. |

### ASMPT Limited (`bond-equipment`; Asian, not an SEC filer)

| Field | Value |
|---|---|
| Listing | 0522, HKEX (XHKG). Cayman-incorporated (LEI country KY). Independent; disposed of ASMPT NEXX, Inc. (closing 3 June 2026, interim results); new Group CEO announced 2026-08-11 (IR page, summarised). |
| SEC | **None.** |
| LEI | 529900PYFA1HFYKPT360 (ASMPT LIMITED, KY, ISSUED, renews 2027-05-31) |
| Reports | English results announcements as PDFs on `asmpt.com` (`/site/assets/files/85468/q2_2026_en_announcement.pdf`, H1 2026, 36 pages, read as text; Q1 2026 at `/site/assets/files/85243/…`). `www.asmpt.com/robots.txt` returns 404 (no restriction under RFC 9309); terms **not checked**. The regulator copy is HKEXnews, which Atlas may not fetch (HKEX Terms of Use; `configs/sources/sites.yaml`). TradingView `HKEX:522` (Unverified). |
| Layer evidence | H1 2026: "AP solutions include Thermo Compression Bonding ('TCB') and Hybrid Bonding"; "The AP business achieved record half-year revenue of US$339.0 million in 1H 2026 … contributing to 30% of Group revenue"; "In July 2026, the Group received new bulk orders for more than 50 of its C2S TCB tools from OSAT customers"; "In memory, even as the Group continued to secure repeat orders from HBM manufacturers, the timing of customers' new tool purchase decisions remains dependent on HBM4 product rollout schedules"; "The TCB total addressable market … is expected to expand beyond US$1.6 billion by 2028". |

### Camtek Ltd. (`process-control`; SEC foreign private issuer)

| Field | Value |
|---|---|
| Listing | CAMT, Nasdaq (XNAS) and Tel Aviv (XTAE; the 20-F discusses the dual listing). Israel. Independent. |
| SEC | CIK 1109138, **20-F/6-K**. 20-F filed 2026-03-19 for FY2025. |
| LEI | 5493000H80W07HCKGS43 (קמטק בע"מ, IL, ISSUED, renews 2027-06-02) |
| Reports | SEC. English. TradingView `NASDAQ:CAMT` (Unverified). |
| Layer evidence | 20-F: "Approximately 50% of our revenues are generated from products supporting the production of artificial intelligence ('AI') applications … including high-bandwidth memory (HBM) and advanced packaging"; FRT (Germany) acquired November 2023 for advanced-packaging metrology. Concentration: "In 2025, one customer accounted for 11% of total revenues"; "sales to China being 49% of our total revenues"; "sole manufacturing and integration facility … located in the North of the State of Israel". |

### FormFactor, Inc. (`test`)

| Field | Value |
|---|---|
| Listing | FORM, Nasdaq (XNAS). Independent. |
| SEC | CIK 1039399, 10-K/10-Q/8-K, FYE last Saturday of December. 10-K filed 2026-02-20 (FY ended 2025-12-27); 10-Q filed 2026-08-04. |
| LEI | 549300YCEEO6SZD1ZR61 (Formfactor, Inc., US), **LAPSED** (2017) |
| Reports | SEC. English. TradingView `NASDAQ:FORM` (Unverified). |
| Layer evidence | 10-K: probe cards for "DRAM, including high-bandwidth memory (HBM)"; "this high-frequency capability also enables us to compete favorably in HBM testing, which is a stack of eight, twelve, or even sixteen individual DRAM die assembled with advanced packaging processes like through-silicon-vias and thermo-compression bonding". Concentration: "SK hynix Inc. 22.9%" of FY2025 revenue (18.9% in 2024), Intel below 10% in 2025; quarterly SK hynix share 19.2–25.0% through 2025. Competitors named: "Japan Electronic Materials Corporation, Korea Instrument Co., Ltd., Micronics Japan Co., Ltd., MPI Corporation, STAr Technologies, Inc., Max One, Technoprobe S.p.A, TSE Co., Ltd.". |

### Ibiden Co., Ltd. (`package-substrate`; Asian, not an SEC filer)

| Field | Value |
|---|---|
| Listing | 4062, "Tokyo and Nagoya Stock Exchange (Code number: 4062)" (Q1 FY2026 results, 2026-08-04). Two-for-one stock splits on 2026-01-01 and 2026-10-01 (same document). OTC IBIDF is an unsponsored ADR (CIK 1654508, F-6EF 2026-07-17). Independent. |
| SEC | **None.** |
| LEI | 52990051DBFIQEY37C91 (イビデン株式会社, JP, ISSUED, renews 2027-01-22) |
| Reports | English PDFs on `ibiden.com/ir/items/`: consolidated results (tanshin), results presentations (`en_kessannsetsumeiFY2025.pdf`, 19 pages, read), Q&A summaries, and the Integrated Report 2025 (`IntegratedReport2025_en.pdf`, 9.3 MB; the download timed out, **not read**). `www.ibiden.com/robots.txt` is 404 (no restriction). The tanshin PDF extracts with run-together words, which a parser would need to handle. TradingView `TSE:4062` (Unverified). |
| Layer evidence | FY2025 results presentation (11 May 2026): "As IC package substrates become larger and more multi-layered, total SAP demands are expected to exceed the industry's supply capacity"; "We will maintain our top share in the high-end market through capacity expansion focused on cutting-edge semiconductors"; "With the electronics business as the core, we aim to achieve Net Sales of JPY 1 trillion and Operating Profit of JPY 300 billion (OPM: 30%) by FY2030"; AI GPU/ASIC demand charts "based on customer information". No customer is named. |

### Ajinomoto Co., Inc. (`package-materials`; Asian, not an SEC filer)

| Field | Value |
|---|---|
| Listing | 2802, "Listed stock exchange Tokyo Stock Exchange (Stock code: 2802)" (ASV Report 2026). Not in `company_tickers.json`. Independent. |
| SEC | **None.** |
| LEI | 353800UT0TLROREPIC92 (味の素株式会社, JP, ISSUED, renews 2026-12-27) |
| Reports | English ASV Report (Integrated Report) 2026 (`ajinomoto.co.jp/company/en/ir/library/annual/main/04/…/ASV_Report_2026_A4_en.pdf`, 106 pages, read; note the IR library lives on `ajinomoto.co.jp`, whose robots.txt is 404, while `www.ajinomoto.com` has a WordPress robots). English annual securities report: a link exists (`/company/en/ir/library/report.html`), **not read**. TradingView `TSE:2802` (Unverified). |
| Layer evidence | ASV Report 2026: "Growth in the Electronic Materials business is accelerating around ABF™, with expanding demand for AI providing a tailwind"; "ABF™ did not remain just another electronic material for a specific application. It grew into a global standard in the field of semiconductor packaging"; "create even more new functional materials — including materials for Photonic-Electronic Co-packages — by evolving Ajinomoto Build-up Film™ (ABF™)". No capacity or customer figure in the report; the ¥25 bn ABF expansion to 2030 is **prior knowledge** from press coverage, not read in a primary source. ABF's chokepoint role is attested by a customer's filing (ASE, finding 4). |

### Examined and not recommended

| Company | Identity (verified unless marked) | Layer evidence read | Why not (or alternate) |
|---|---|---|---|
| **Western Digital Corp.** | WDC, Nasdaq, CIK 106040, 10-K filed 2026-08-14 (FYE 2026-07-03). LEI 549300QQXOOYEF89IC56 LAPSED 2025-06-20. | "data storage devices and solutions based on hard disk drive ('HDD') technology"; "the Cloud end market accounted for 89% of our net revenue and our top 10 customers accounted for 73%", three customers 16%, 15%, 13%. | HDD only since the Separation. Outside the theme. |
| **Seagate Technology Holdings plc** | STX, Nasdaq, CIK 1137789, 10-K 2026-08-04, Irish plc (LEI 635400RUXIFEZSRU8X70, ISSUED), Singapore address. An SC TO-T in March 2025 (**Unverified** target; Intevac is prior knowledge). | HAMR/Mozaic; "We rely on sole or a limited number of … suppliers … including substrates for recording media, read/write heads". | HDD. Outside the theme. |
| **Nanya Technology Corp.** | TWSE 2408 (prior knowledge). LEI 254900STKVKJBRRO0835 LAPSED 2019. Not in the ticker file. `www.nanya.com/robots.txt` returns an HTML page (unclear) → site not fetched. | None read. | `memory-dram` alternate (the small merchant DRAM maker). MOPS/TWSE English filings **Unverified**. |
| **Taiwan Semiconductor Manufacturing Co.** | TSM, NYSE, CIK 1046179, 20-F filed 2026-04-16. LEI 549300KB6NK5SBD14S87 ISSUED. | The 20-F names "CoWoS® advanced packaging services" twice and capex "for specialty technologies and advanced packaging, including building/facility expansion for Fab 23 and Fab 24"; "our ten largest customers … 78% of our net revenue"; largest 19%, second 17%. | Packaging is a slice of a foundry's 20-F: the dilution-of-exposure case. Better as a counterparty (an edge target for "CoWoS allocation" Claims) than a seed. `osat` alternate. |
| **Powertech Technology Inc.** | TWSE 6239 (prior knowledge). LEI 254900O6KNZXH2RI9Q14 LAPSED 2025-09-03. `www.pti.com.tw/robots.txt` returns an HTML page (unclear) → not fetched. | None read. | `osat` alternate (memory OSAT). |
| **ChipMOS Technologies Inc.** | IMOS, Nasdaq, CIK 1123134, 20-F 2026-04-14, Taiwan. No LEI found. | "A significant portion of our revenue is derived from testing and assembling memory semiconductors"; "top five customers collectively accounted for 61% of our revenue"; customers listed include Micron, Nanya, Phison, Winbond. | A memory OSAT with a 20-F: a good `osat` alternate if a second one is wanted (it names its memory customers). |
| **Kulicke & Soffa Industries** | KLIC, Nasdaq, CIK 56978, 10-K filed 2025-11-20 (FYE 2025-10-04); the FY2026 10-K is due in November. LEI 529900H6BEIRBF429744 ISSUED. | "APTURA™ is a highly capable thermo-compression bonding system which supports an ultra-fine-pitch fluxless direct-copper thermo-compression bonding"; ten largest customers 54.8%. HBM appears only in an export-control sentence. | Wire-bond incumbent; the HBM TCB position is not disclosed. `bond-equipment` alternate. |
| **Hanmi Semiconductor** | KRX 042700 (prior knowledge). **No LEI found.** Not in the ticker file. `www.hanmisemi.com` returns 403 for robots.txt → not fetched. | None read (only non-primary search hits, not cited). | The HBM TC-bonder pure play is **Unverified** end to end. DART English filings **Unverified**. A discovery Candidate, not a seed, until a primary document is read. |
| **Onto Innovation** | ONTO, NYSE, CIK 704532, 10-K 2026-02-24; 8-K Item 2.01 2025-11-17 (Semilab USA) and 2026-08-10 (27% of Rigaku Holdings, about $720 million). LEI 254900RXZVN73CHOO062 ISSUED. | "lithography tools for advanced packaging"; no "HBM" in the 10-K; no customer percentage read. | `process-control` alternate behind Camtek. Two acquisitions in a year. |
| **Nova Ltd.** | NVMI, Nasdaq, CIK 1109345, 20-F 2026-02-17, Israel. LEI 529900B2DSWE5V3SC292 ISSUED. | "Optical Metrology for Advanced Packaging product lines … located in Mannheim, Germany"; five largest customers 51% (range 5–19%). | `process-control` alternate. |
| **Advantest Corporation** | 6857, "Prime Market of the Tokyo Stock Exchange" (Q1 FY2026 results, 2026-07-29). CIK 1158838 is dormant (last 20-F 2015; an F-6 2026-08-06). LEI 353800EMK32PDKS9XR54 ISSUED. `advantest.com` robots: `Disallow:` (empty). | Integrated Annual Report 2025 (71 pages): "established a dominant position in the memory tester market"; Q1 FY2026: "demand for key components such as memory semiconductors continues to exceed supply". No customer percentage found. | `test` alternate: the memory-ATE leader, English documents, manual imports. Took 2.5% of Technoprobe (Jan 2025). |
| **Teradyne, Inc.** | TER, Nasdaq, CIK 97210, 10-K 2026-02-19. LEI C3X4YJ278QNZHRJULN75 ISSUED. | "Memory test revenue remained stable despite a smaller overall market, supported by share gains in high bandwidth memory ('HBM') and DRAM final test applications"; Magnum platform "for parallel memory test in the flash, DRAM, HBM and multi-chip package markets"; competitors "Advantest Corporation, SPEA S.p.A., and Cohu, Inc.". No 10% customer sentence found. | `test` alternate with the easiest path (10-K). Memory test is a minority of Semiconductor Test. |
| **Technoprobe S.p.A.** | Euronext Milan (XMIL) since 2023-05-02 (annual report); controlled by T-PLUS S.p.A. (56.43%). OTC THNBY is an unsponsored ADR (CIK 1971172, one F-6EF). LEI 8156007154CD8334D053 ISSUED. `technoprobe.com` robots allows the report path. | Annual Financial Report 2025 (English, 268 pages): "The Group operates in the design and production of probe cards"; "First customer 173,402 [k€] 27.6%", "Second customer 100,979 16.1%"; "AI-related architectures continue to represent the primary growth driver for the entire sector, both in logic and memory". | Second European candidate; `test` alternate. Its path is Borsa Italiana/CONSOB (no adapter). |
| **Aehr Test Systems** | AEHR, Nasdaq, CIK 1040470, 10-K 2026-07-27 (FYE 2026-05-29). LEI 529900A4GWWZFRU2RE97 LAPSED 2020. | Wafer-level burn-in; "AI processors' … increased memory size and use create a unique opportunity". Full-wafer-contact revenue $31.5 m in FY2026. | Small; AI-processor burn-in rather than memory. Not an alternate. |
| **Unimicron Technology Corp.** | TWSE 3037 (prior knowledge). LEI 529900552WPFHC1YI579 ISSUED. `www.unimicron.com` failed TLS verification → not fetched. | None read; named by ASE as a limited substrate supplier. | `package-substrate` alternate; the Taiwanese ABF-substrate leader is a counterparty in ASE's 20-F already. |
| **AT&S Austria Technologie & Systemtechnik AG** | ISIN AT0000969985, Vienna Stock Exchange Official Market (XWBO), read in the 2026-05-21 results release on the Deutsche Börse news host through a summarising fetch. LEI 529900EVOKN4LCCD9321 ISSUED. `ats.net` robots allows; the report pages are JavaScript-rendered and no PDF URL was found. | Release: "demand by a key customer for high-end IC substrates of AT&S is growing"; "AT&S has decided to expand capacity at its location in Chongqing, China"; "AT&S generates more than 80% of its revenue with US companies"; FY2025/26 revenue about €1.8 bn. | The European `package-substrate` alternate (and the one-key-customer case). Path: Vienna/OeKB issuer information (no adapter). |
| **Shinko Electric Industries** | LEI 549300627MZ4832XWF51 is **RETIRED** (INACTIVE) with successor "JICC-04株式会社". `www.shinko.co.jp/robots.txt` 404. | None. | Taken private (JIC consortium: prior knowledge; the LEI record is the primary evidence). Dropped. |
| **Resonac Holdings Corp.** | 4004, TSE Prime (IR page, summarised). LEI 5493006AIPA1V92YPP18 ISSUED. | Q2 FY2026 summary: "Semiconductor and Electronic Materials" segment; "partial spin-off of Crasus Chemical Inc., scheduled for October 1, 2026", FY2025 restated. | `package-materials` alternate (NCF, die-bonding film: prior knowledge, not read). Mid-restructuring; revisit after the spin-off. |
| **Silicon Motion Technology Corp.** | SIMO, Nasdaq, CIK 1329394, 20-F 2026-04-30, Cayman/Taiwan. LEI 5299005RBVBZQJTYFC89 LAPSED 2020. | "Our customers constituting more than 10% of our net revenue were … PHISEMI, Kioxia, AFASTOR, and Micron in 2025" (58% in aggregate); foundries "primarily Taiwan Semiconductor Manufacturing Company ('TSMC'), and secondarily … SMIC"; "during periods of NAND shortages, our sales and profitability could be negatively affected". | `controller` alternate and the first swap-in: its 20-F names memory makers as customers, so it is an edge source. |
| **Phison Electronics Corp.** | TWSE 8299 (prior knowledge). LEI 984500BA9RE56493C972 ISSUED. `phison.com` robots permissive; not read. | None read; named as a ChipMOS and Silicon Motion counterparty. | `controller` alternate. |
| **Rambus Inc.** | RMBS, Nasdaq, CIK 917273, 10-K 2026-02-18. LEI 2549000211GDCQSLV833 ISSUED. | "Our memory interface chips are sold to major DRAM manufacturers, Micron, Samsung and SK hynix"; product revenue 49% of 2025 revenue. | `controller` alternate: an IP-and-chip company, not a capacity constraint. |

## Recommended seed list (12)

The Bottleneck lens: which layer can't add qualified capacity fast enough, who says so in their own filing, and what evidence would refute it.

| # | Company | Layer | Disclosure path | Why it's in |
|---|---|---|---|---|
| 1 | Micron | memory-dram, memory-nand | US 10-K | The one US memory maker; "supply allocation" and strategic customer agreements are the demand-side evidence. |
| 2 | SK hynix | memory-dram (HBM) | **SEC FPI: F-1/424B4, 6-K; 20-F from FY2026** | HBM share leader with "demand … exceeded our available supply" and equipment lead times over a year in its own prospectus. |
| 3 | Samsung Electronics | memory-dram, memory-nand | **Not SEC; FCA NSM (annual, ESEF) + manual imports** | The only unit capacity figure and DRAM share series in the theme; the second HBM supplier whose HBM4 ramp is the falsifier of an SK hynix chokepoint. |
| 4 | SanDisk | memory-nand | US 10-K | Newly independent NAND maker; its wafers come only from the Kioxia JVs, so the NAND capacity edge is explicit. |
| 5 | Kioxia | memory-nand | **Not SEC; TSE Prime; English securities report, manual imports** | The other half of the JV; Apple about 20% of revenue; the Asian non-SEC NAND path. |
| 6 | ASE Technology | osat, package-substrate | **SEC FPI: 20-F/6-K** | Names its limited substrate suppliers and the ABF risk; CoWoS-class packaging outside TSMC. |
| 7 | BESI | bond-equipment (hybrid bonding) | **Not SEC; Euronext Amsterdam; European** | The hybrid-bonding tool maker whose orders are the leading indicator; the robots block on PDFs makes it a test of the AFM path. |
| 8 | ASMPT | bond-equipment (TCB) | **Not SEC; HKEX 0522 (HKEXnews blocked); asmpt.com PDFs** | TCB bulk orders and the HBM4-timing dependency in its own interim report. |
| 9 | Camtek | process-control | SEC FPI: 20-F/6-K | About half its revenue from AI (HBM and advanced packaging); 49% China exposure as a risk edge. |
| 10 | FormFactor | test | US 10-K | SK hynix 22.9% of revenue: a verified Relationship into the HBM maker on day one. |
| 11 | Ibiden | package-substrate | **Not SEC; TSE/Nagoya 4062; English PDFs, manual imports** | The substrate maker that says industry SAP demand will exceed supply capacity. |
| 12 | Ajinomoto | package-materials | **Not SEC; TSE 2802; English integrated report, manual imports** | The ABF monopoly-by-standard that a customer (ASE) names as a shortage risk; the small-slice-of-a-large-company test case. |

Rules check: European non-SEC = BESI (Technoprobe and AT&S are the alternates). Asian = SK hynix, Samsung, Kioxia, ASE, ASMPT, Ibiden, Ajinomoto. SEC foreign private issuers = SK hynix (prospectus and 6-K), ASE (20-F) and Camtek (20-F). Not SEC filers at all = Samsung, Kioxia, BESI, ASMPT, Ibiden, Ajinomoto. Every layer has a company except `controller`, which is a fabless layer rather than a capacity chokepoint; Silicon Motion is the first swap-in if the owner wants it covered (for Ajinomoto or Camtek).

If the list must shrink to 10, drop Ajinomoto and Kioxia (ASE's 20-F still carries the ABF statement; SanDisk's 10-K carries the JV). If it may grow to 13, add Amkor (US 10-K, Apple 29.8%, the Arizona facility).

Reachability: six of the twelve need manual imports today (Samsung, Kioxia, BESI's annual report, ASMPT, Ibiden, Ajinomoto); Samsung's annual report would be fetchable with the ESEF change in finding 2, its quarterlies not. The preference for reachable paths is why the US names (Micron, SanDisk, FormFactor) and the three FPIs are in, and why a theme whose chain is Korean, Japanese and Taiwanese still has seven SEC-path seeds.

## Open questions for the owner

1. **ESEF on the NSM.** Should the `fca-nsm` adapter take an ESEF row's `html_link` (or unzip the package) so Samsung's Business Report ingests? Without it, Samsung is manual-import only.
2. **A KRX/DART path.** SK hynix's 6-Ks cover its quarterlies, but Samsung's and Hanmi's do not exist at the SEC. DART (dart.fss.or.kr) has an English site and an open API (prior knowledge); its terms were not checked.
3. **A TSE/JPX path.** Kioxia, Ibiden, Ajinomoto and Advantest publish English PDFs on their own sites (robots permit) and Japanese originals on TDnet/EDINET. Is a company-site PDF adapter acceptable for these, or are they manual imports until a JPX adapter exists? Ibiden's tanshin PDFs extract with run-together words; the presentation PDFs extract cleanly.
4. **BESI's annual report.** `besi.com` forbids crawling its PDFs. The AFM register (`afm.nl`) is the regulator copy; its terms were not checked. Manual import otherwise.
5. **HKEX licence.** ASMPT's regulator copy is HKEXnews, blocked by its terms as for Innolight. Its own site serves the same PDFs with no robots.txt and unchecked terms. Same decision as for Innolight.
6. **Hanmi.** No LEI, site returns 403, nothing read. Seed it blind, or let discovery find it (SK hynix's and Samsung's documents will name their bonder suppliers, if anywhere)?
7. **TradingView symbols** for every company (none verified).
8. **Taxonomy names.** `package-substrate` versus photonics' `substrate`: confirm the names before the layer terms are written, since the Claim layer rule matches on terms.

## Could not verify

- TradingView symbols (not queried).
- Hanmi Semiconductor's identity, listing and products from any primary source; its LEI (none found).
- Nanya's, Powertech's, Unimicron's and Phison's English disclosures (sites unclear, blocked by TLS, or not read); their TWSE listings are prior knowledge.
- Ibiden's Integrated Report 2025 (download timed out) and Ajinomoto's English securities report (not fetched).
- Who sold in SanDisk's and Amkor's 424B7/424B4 secondaries; the target of Seagate's SC TO-T.
- Applied Materials' stake in BESI; the JIC consortium behind Shinko's take-private; the Ajinomoto ¥25 bn ABF investment; TSMC's CoWoS capacity (none of these is in a document I read).
- BESI's and ASMPT's website terms; the AFM and SGX terms; whether the SGX hosts Kioxia's releases because of a bond listing (not checked).
- Kioxia's "HBF" product (not in the securities report).
- Samsung's quarterly English documents and their location.
