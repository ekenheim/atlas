# Controls for the early-call scorecard

Drawn 2026-10-18 from SEC EDGAR, live, by the rule of Amendment 2 ("Controls") and Amendment 1 ("Control list for the code half"). Per case: the SIC is the case's `sic` in its submissions JSON (today's SIC); candidates are every filer the EDGAR company browse lists under that SIC (`owner=include`, every page), less the case and every `cik:` in `configs/themes/ai-infrastructure.yaml` (Western Digital is not in that file, so it stays); eligible = its latest 10-K, 10-Q, 20-F or 40-F (amendments included) on or before the first as-of date D, per submissions (`recent` plus `files`), was filed within the 365 days before D (D-365 to D; rule note of 2026-10-18, the lead's decision, replacing 'any periodic report on or before D'); market value = `dei:EntityPublicFloat` (USD) from companyfacts, the latest 10-K/20-F/40-F (amendments included) filed on or before D, the latest `end` if it reports several; an eligible candidate with none is excluded and listed, never substituted. The case uses the same measure, else `dei:EntityCommonStockSharesOutstanding` of its first periodic report after D, as amended by a later amendment of that same cover (both figures recorded), times the close on D from Atlas's price history (`closes.json`, null until filled; phase2 stops on a null). Distance = |ln(candidate / case)|; eligible candidates with a float, sorted by CIK, are shuffled with `random.Random(20261018).shuffle` (a fresh generator per case) and stably sorted by distance; the first two are the controls. All values are the reported ones; a float of 0 has an undefined distance and is listed apart, not ranked.

**Status:** Snap drawn. SanDisk, IREN and POET pending their closes (`closes.json` is a template with null closes; `phase2.py` stops on a null). eToro undrawn: no SEC share count or float.

**Rule note, 2026-10-18 (the lead):** (1) freshness: a candidate's latest periodic report on or before D must have been filed D-365 to D; its float is still from the latest 10-K/20-F/40-F on or before D; (2) the share count is the first periodic report after D, as amended; (3) closes from Atlas's price history only, no web access; (4) eToro: no controls; (5) floats of 0 and non-USD floats stay excluded and listed, one seeded Random per case.


## sandisk

- SIC **3572**, Computer Storage Devices. CIK 0002023554; first as-of date 2025-02-28.
- Candidates found by the browse: 78 (less the case: 1, less the universe: 0) = 77. No periodic report on or before D: 24. Latest periodic report filed before 2024-02-29 (older than 365 days): 48. Eligible: 5.
- Excluded for no public float: 0 of 5 eligible (5 with a float, of which 0 reported 0 and are not ranked).

<details><summary>No public float (0)</summary>


</details>

- Case market value: **not obtained.** No `EntityPublicFloat` in a 10-K/20-F/40-F filed on or before D (no float in an annual report filed on or before D).
  - Shares, first periodic report after D: 114,863,251 (`dei:EntityCommonStockSharesOutstanding`, 10-Q filed 2025-03-07, as of 2025-02-27, accession 0002023554-25-000004).
  - Amended: 144,863,251 (10-Q/A filed 2025-03-17, same cover date, accession 0002023554-25-000016). Used: the amended figure, 144,863,251. Both recorded.
  - Times the close on 2025-02-28 from Atlas's price history: **pending** (`closes.json`).
- **Pending:** pending: close from Atlas price history.
- Ready to draw once the close is in: 5 eligible candidates with a positive float, in `controls.json` (`eligible_floats`).

## iren

- SIC **6199**, Finance Services. CIK 0001878848; first as-of date 2025-03-31.
- Candidates found by the browse: 605 (less the case: 1, less the universe: 0) = 604. No periodic report on or before D: 280. Latest periodic report filed before 2024-03-31 (older than 365 days): 173. Eligible: 151.
- Excluded for no public float: 44 of 151 eligible (107 with a float, of which 11 reported 0 and are not ranked).

<details><summary>No public float (44)</summary>

- Alpha Compute Corp (0001095435): no EntityPublicFloat
- The9 LTD (0001296774): no EntityPublicFloat
- Yueda Digital Holding (0001413745): no EntityPublicFloat
- Eason Technology Ltd (0001499494): no EntityPublicFloat
- SPROTT INC. (0001512920): no EntityPublicFloat
- SOLAI Ltd (0001517496): no EntityPublicFloat
- Chaince Digital Holdings Inc. (0001527762): no float in an annual report filed on or before D
- Prosper Funding LLC (0001542574): no EntityPublicFloat
- Orion Digital Corp. (0001602842): non-USD units: CAD
- 9F Inc. (0001619544): no EntityPublicFloat
- Yiren Digital Ltd. (0001631761): no EntityPublicFloat
- Wins Finance Holdings Inc. (0001640251): no EntityPublicFloat
- Metalpha Technology Holding Ltd (0001682241): no EntityPublicFloat
- Nu Holdings Ltd. (0001691493): no EntityPublicFloat
- High Templar Tech Ltd (0001692705): no EntityPublicFloat
- Amber International Holding Ltd (0001697818): no EntityPublicFloat
- LexinFintech Holdings Ltd. (0001708259): no EntityPublicFloat
- HIVE Digital Technologies Ltd. (0001720424): no float in an annual report filed on or before D
- X Financial (0001725033): no EntityPublicFloat
- Cango Inc. (0001725123): no EntityPublicFloat
- INX Ltd (0001725882): no EntityPublicFloat
- CNFinance Holdings Ltd. (0001733868): no EntityPublicFloat
- SANGRIX INC. (0001735556): no EntityPublicFloat
- Qfin Holdings, Inc. (0001741530): no EntityPublicFloat
- Jiayin Group Inc. (0001743102): no EntityPublicFloat
- Aurelion Inc. (0001765850): no EntityPublicFloat
- AMTD IDEA GROUP (0001769731): no EntityPublicFloat
- Canaan Inc. (0001780652): no EntityPublicFloat
- AMTD Digital Inc. (0001809691): no EntityPublicFloat
- Sentage Holdings Inc. (0001810467): no EntityPublicFloat
- Keel Infrastructure Corp. (0001812477): no float in an annual report filed on or before D
- Lufax Holding Ltd (0001816007): no EntityPublicFloat
- Sono Group N.V. (0001840416): no float in an annual report filed on or before D
- Argo Blockchain Plc (0001841675): no EntityPublicFloat
- Digi Power X Inc. (0001854368): no float in an annual report filed on or before D
- Abits Group Inc (0001864055): no EntityPublicFloat
- Magic Empire Global Ltd (0001881472): no EntityPublicFloat
- Coincheck Group N.V. (0001913847): no EntityPublicFloat
- Universal Token (0001919182): no float in an annual report filed on or before D
- Bitfufu Inc. (0001921158): no EntityPublicFloat
- Blue Chip Capital Group Inc. (0001932213): no float in an annual report filed on or before D
- Brera Holdings PLC (0001939965): no EntityPublicFloat
- Global-Smart.Tech Inc. (0001940243): no float in an annual report filed on or before D
- NFT Ltd (0001958713): no EntityPublicFloat

</details>

<details><summary>Float reported as 0 (11)</summary>

- General Motors Financial Company, Inc. (0000804269), filed 2025-01-28
- PROSPER MARKETPLACE, INC (0001416265), filed 2025-03-26
- TriLinc Global Impact Fund LLC (0001550453), filed 2025-03-28
- Creations Inc (0001795938), filed 2024-04-15
- SAIHEAT Ltd (0001847075), filed 2022-02-18
- KKR Private Equity Conglomerate LLC (0001957845), filed 2025-03-13
- Bloom HoldCo LLC (0001975931), filed 2023-12-21
- Fidelity Ethereum Fund (0002000046), filed 2025-03-14
- Apollo Asset Backed Credit Co LLC (0002000597), filed 2025-03-31
- Bitwise Ethereum ETF (0002013744), filed 2025-03-17
- Resolute Holdings Management, Inc. (0002039497), filed 2025-03-31

</details>

- Case market value: **not obtained.** No `EntityPublicFloat` in a 10-K/20-F/40-F filed on or before D (no float in an annual report filed on or before D).
  - Shares, first periodic report after D: 283,465,490 (`dei:EntityCommonStockSharesOutstanding`, 10-Q filed 2025-11-06, as of 2025-10-31, accession 0001878848-25-000081).
  - Times the close on 2025-03-31 from Atlas's price history: **pending** (`closes.json`).
- **Pending:** pending: close from Atlas price history.
- Ready to draw once the close is in: 96 eligible candidates with a positive float, in `controls.json` (`eligible_floats`).

## etoro

- SIC **6211**, Security Brokers, Dealers & Flotation Companies. CIK 0001493318; first as-of date 2025-09-30.
- Candidates found by the browse: 254 (less the case: 1, less the universe: 0) = 253. No periodic report on or before D: 100. Latest periodic report filed before 2024-09-30 (older than 365 days): 121. Eligible: 32.
- Excluded for no public float: 8 of 32 eligible (24 with a float, of which 2 reported 0 and are not ranked).

<details><summary>No public float (8)</summary>

- NOMURA HOLDINGS INC (0001163653): no EntityPublicFloat
- Futu Holdings Ltd (0001754581): no EntityPublicFloat
- UP Fintech Holding Ltd (0001756699): no EntityPublicFloat
- XP Inc. (0001787425): no EntityPublicFloat
- Lion Group Holding Ltd (0001806524): no EntityPublicFloat
- Galaxy Digital Inc. (0001859392): no float in an annual report filed on or before D
- Webull Corp (0001866364): no EntityPublicFloat
- Solowin Holdings, Ltd. (0001959224): no EntityPublicFloat

</details>

<details><summary>Float reported as 0 (2)</summary>

- JONES FINANCIAL COMPANIES LLLP (0000815917), filed 2024-03-12
- MMTEC, INC. (0001742518), filed 2019-04-22

</details>

- Case market value: **not obtained.** No `EntityPublicFloat` in a 10-K/20-F/40-F filed on or before D (no EntityPublicFloat).
  - Undrawn: no SEC share count or float (companyfacts for this CIK has only the taxonomies ['ifrs-full']; no shares outstanding in any periodic report after D).
- **Not drawn:** undrawn: no SEC share count or float.

## snap

- SIC **7370**, Services-Computer Programming, Data Processing, Etc.. CIK 0001564408; first as-of date 2025-08-31.
- Candidates found by the browse: 405 (less the case: 1, less the universe: 0) = 404. No periodic report on or before D: 120. Latest periodic report filed before 2024-08-31 (older than 365 days): 186. Eligible: 98.
- Excluded for no public float: 34 of 98 eligible (64 with a float, of which 4 reported 0 and are not ranked).

<details><summary>No public float (34)</summary>

- SIFY TECHNOLOGIES LTD (0001094324): no EntityPublicFloat
- GIGAMEDIA Ltd (0001105101): no EntityPublicFloat
- Baidu, Inc. (0001329099): no EntityPublicFloat
- VNET Group, Inc. (0001508475): no EntityPublicFloat
- Nebius Group N.V. (0001513845): no EntityPublicFloat
- GDS Holdings Ltd (0001526125): no EntityPublicFloat
- Wix.com Ltd. (0001576789): no EntityPublicFloat
- WEIBO Corp (0001595761): no EntityPublicFloat
- Jianpu Technology Inc. (0001713923): no EntityPublicFloat
- J & Friends Holdings Ltd (0001716338): no EntityPublicFloat
- HUYA Inc. (0001728190): no EntityPublicFloat
- Qutoutiao Inc. (0001733298): no EntityPublicFloat
- Alithya Group inc (0001734520): no EntityPublicFloat
- Aurora Mobile Ltd (0001737339): no EntityPublicFloat
- Sangoma Technologies Corp (0001753368): no EntityPublicFloat
- DouYu International Holdings Ltd (0001762417): no EntityPublicFloat
- ONECONNECT FINANCIAL TECHNOLOGY CO., LTD. (0001780531): no EntityPublicFloat
- Sound Group Inc. (0001783407): no EntityPublicFloat
- Dada Nexus Ltd (0001793862): no EntityPublicFloat
- Yalla Group Ltd (0001794350): no EntityPublicFloat
- Sportradar Group AG (0001836470): no EntityPublicFloat
- SIMILARWEB LTD. (0001842731): no EntityPublicFloat
- Kanzhun Ltd (0001842827): no EntityPublicFloat
- Nexxen International Ltd. (0001849396): no EntityPublicFloat
- Locafy Ltd (0001875547): no EntityPublicFloat
- MindForge Inc. (0001888525): no EntityPublicFloat
- Global Mofy AI Ltd (0001913749): no EntityPublicFloat
- REZOLVE AI PLC (0001920294): no EntityPublicFloat
- Lucas GC Ltd (0001954694): no EntityPublicFloat
- Real Messenger Corp (0001983324): no EntityPublicFloat
- IGTA Merger Sub Ltd (0001997698): no float in an annual report filed on or before D
- Robot Consulting Co., Ltd. (0002007599): no EntityPublicFloat
- Wintergreen Acquisition Corp. (0002053927): no float in an annual report filed on or before D
- NIQ Global Intelligence plc (0002054696): no EntityPublicFloat

</details>

<details><summary>Float reported as 0 (4)</summary>

- CLOUDASTRUCTURE, INC. (0001709628), filed 2025-03-31
- Go Go Buyers, Inc. (0001842563), filed 2025-03-31
- WidFit Inc. (0001912954), filed 2025-07-22
- MARKY CORP. (0001973047), filed 2025-04-30

</details>

- Case market value: **$21,500,000,000**, `dei:EntityPublicFloat`, 10-K filed 2025-02-05 (period end 2024-06-28), accession 0001564408-25-000019. Source: https://data.sec.gov/api/xbrl/companyfacts/CIK0001564408.json
- Nearest by distance: PINTEREST, INC. $23,100,000,000 (2025-02-06) d=0.0718; AppLovin Corp $23,700,000,000 (2025-02-27) d=0.0974; FACTSET RESEARCH SYSTEMS INC $17,602,720,964 (2024-10-29) d=0.2000; Zoom Communications, Inc. $15,800,000,000 (2025-02-28) d=0.3080; Flutter Entertainment plc $32,380,000,000 (2025-03-04) d=0.4095.

### The two controls

**1. PINTEREST, INC.** (CIK 0001506293)
- Ticker: PINS; exchange: NYSE.
- Forms filed 2024-2025: 10-K, 10-Q, 144, 3, 3/A, 4, 8-K, ARS, DEF 14A, DEFA14A, PRE 14A, S-8, SC 13G/A, SCHEDULE 13G, SCHEDULE 13G/A.
- Float: $23,100,000,000, period end 2024-06-28, 10-K filed 2025-02-06 (accession 0001506293-25-000022). Distance 0.0718.
- Filed in 2026: yes (periodic report in 2026: yes; latest filing 2026-10-15).
**2. AppLovin Corp** (CIK 0001751008)
- Ticker: APP; exchange: Nasdaq.
- Forms filed 2024-2025: 10-K, 10-Q, 144, 3, 4, 4/A, 424B3, 424B5, 424B7, 8-K, ARS, DEF 14A, DEFA14A, FWP, S-8, SC 13G, SC 13G/A, SCHEDULE 13G, SCHEDULE 13G/A.
- Float: $23,700,000,000, period end 2024-06-28, 10-K filed 2025-02-27 (accession 0001751008-25-000018). Distance 0.0974.
- Filed in 2026: yes (periodic report in 2026: yes; latest filing 2026-10-16).
- Reading check: the float comes from the filing that submissions lists as the latest annual report on or before D for all of the top six: yes.

## poet-technologies

- SIC **3674**, Semiconductors & Related Devices. CIK 0001437424; first as-of date 2025-11-30.
- Candidates found by the browse: 506 (less the case: 1, less the universe: 10) = 495. No periodic report on or before D: 129. Latest periodic report filed before 2024-11-30 (older than 365 days): 267. Eligible: 99.
- Universe companies excluded: AMKOR TECHNOLOGY, INC. (0001047127), APPLIED OPTOELECTRONICS, INC. (0001158114), ASE Technology Holding Co., Ltd. (0001122411), AXT INC (0001051627), FORMFACTOR INC (0001039399), MACOM Technology Solutions Holdings, Inc. (0001493594), Marvell Technology, Inc. (0001835632), MICRON TECHNOLOGY INC (0000723125), SK hynix Inc. (0002120882), STMicroelectronics N.V. (0000932787).
- Excluded for no public float: 22 of 99 eligible (77 with a float, of which 2 reported 0 and are not ranked).

<details><summary>No public float (22)</summary>

- TOWER SEMICONDUCTOR LTD (0000928876): no EntityPublicFloat
- UNITED MICROELECTRONICS CORP (0001033767): no EntityPublicFloat
- TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD (0001046179): no EntityPublicFloat
- METALINK LTD (0001098462): no EntityPublicFloat
- CHIPMOS TECHNOLOGIES INC (0001123134): no EntityPublicFloat
- SuperCom Ltd (0001291855): no EntityPublicFloat
- Silicon Motion Technology CORP (0001329394): no EntityPublicFloat
- Himax Technologies, Inc. (0001342338): no EntityPublicFloat
- SEQUANS COMMUNICATIONS (0001383395): no EntityPublicFloat
- DAQO NEW ENERGY CORP. (0001477641): no EntityPublicFloat
- JinkoSolar Holding Co., Ltd. (0001481513): no EntityPublicFloat
- Ambiq Micro, Inc. (0001500412): no float in an annual report filed on or before D
- GLOBALFOUNDRIES Inc. (0001709048): no EntityPublicFloat
- Maxeon Solar Technologies, Ltd. (0001796898): no EntityPublicFloat
- Valens Semiconductor Ltd. (0001863006): no EntityPublicFloat
- Nano Labs Ltd (0001872302): no EntityPublicFloat
- Intchains Group Ltd (0001895597): no EntityPublicFloat
- SEALSQ Corp (0001951222): no EntityPublicFloat
- ARM HOLDINGS PLC /UK (0001973239): no EntityPublicFloat
- TOYO Co., Ltd (0001985273): no EntityPublicFloat
- Semilux International Ltd. (0001990950): no EntityPublicFloat
- Qnity Electronics, Inc. (0002058873): no float in an annual report filed on or before D

</details>

<details><summary>Float reported as 0 (2)</summary>

- Canadian Solar Inc. (0001375877), filed 2014-04-28
- Palomino Laboratories Inc. (0001938569), filed 2025-03-28

</details>

- Case market value: **not obtained.** No `EntityPublicFloat` in a 10-K/20-F/40-F filed on or before D (no EntityPublicFloat).
  - Shares, first periodic report after D: 132,290,739 (`dei:EntityCommonStockSharesOutstanding`, 20-F filed 2026-03-31, as of 2025-12-31, accession 0001493152-26-014253).
  - Times the close on 2025-11-30 from Atlas's price history: **pending** (`closes.json`).
- **Pending:** pending: close from Atlas price history.
- Ready to draw once the close is in: 75 eligible candidates with a positive float, in `controls.json` (`eligible_floats`).

SEC requests made: 3159 (cache: scratchpad `controls\cache`; a rerun makes none). Stooq: 2 scripted requests and 2 Chrome page loads earlier, all refused, no data; no web access since, and the 2026-10-18 rerun used the cache only. Drawn 2026-10-18.
