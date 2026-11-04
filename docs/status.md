# Status

Claude: read this first every session. Tick items as you finish them, and add a dated line to the Log.

## Day 1: data and crosswalk

- [x] Run `make setup`, then `make validate` (reference tables pass)
- [x] ingest-cms: build `partd_drug_year.csv`; log the year range and latest-year gross total
- [x] map-drug-targets: run `make map`; log coverage
- [x] map-drug-targets: hand-map failures in `manual_mappings.csv`
- [x] map-drug-targets: classify every human target in `target_classes.csv`
- [x] curate-reference: fix any CMS regex that matched no spend
- [x] gate-check: `make gate1` passes (2026-11-03: `PASS gate 1`)

## Day 2: analysis and write-up

- [x] curate-reference: verify the 15 second-cycle prices against the CMS fact sheet
- [x] analyze-question: `make analyze`; reconciliation and sensitivity checks logged
- [x] analyze-question: draft three findings below
- [ ] write-findings: README.md
- [ ] gate-check: `make gate2` passes, plus the fresh-eyes review

## Findings draft

1. **Q1.** Factor Xa (F10, via Eliquis and Xarelto) absorbs 26.5% ($27.0B) of the $102.1B gross 2024 Part D spend on the 24 negotiated drugs with a human target (target_spend.csv, equal split; share_of_total 0.264614).
2. **Q1.** Three targets dominate: F10 26.5%, SGLT2 (SLC5A2, Farxiga + Jardiance) 16.4%, GLP-1R (semaglutide) 14.9%. The next target, DPP-4, has 5.4%. The top three are identical under both split rules (target_spend.csv).
3. **Q2.** The cut from list to negotiated 30-day price ranged from 37.6% (Imbruvica, BTK kinase) to 84.8% (Janumet, DPP-4 protease). Both BTK-kinase drugs were near the bottom (Imbruvica 37.6%, Calquence 39.6%); all three DPP-4 drugs were near the top (Janumet 84.8%, Tradjenta 84.0%, Januvia 78.6%) (price_cuts.csv). Caveat for the README: classes hold only 1–6 drugs, the two cycles use different list-price years, and the low-list-price primary-care drugs (about $400–$650 list) were cut harder than the high-list-price specialty drugs. The data cannot separate a target-class effect from a list-price-level effect.

## Blocked

(none)

## Extensions (out of scope until gate 2 passes)

1. Scale the crosswalk to every Part D drug, 2019-2024
2. Add the 2028 cycle (first Part B drugs) once negotiated prices are published
3. Reactome pathway enrichment, negotiated vs non-negotiated targets
4. Streamlit dashboard
5. Negotiation-selection model, checked against the CMS top-50 eligible list

## Log

- 2026-11-02 - Scaffold created: contracts, skills, hook, reference data (25 drugs; 15 second-cycle prices from news coverage, unverified)
- 2026-11-03 - Setup: git repo initialised, `make setup` built .venv (Python 3.14), `make validate` PASS all tables. Next: ingest-cms.
- 2026-11-03 - ingest-cms: `make ingest` fetched 14,536 CMS rows -> 16,429 drug-year rows, contract passed. Years 2020-2024. Latest-year (2024) gross Part D spend total $288,667,842,058 (all drugs, before rebates). Eliquis 2024 gross $20.77B, 24.06M claims. Doubt: Eliquis not yet spot-checked by eye in the CMS data viewer (only the API rows the pipeline read).
- 2026-11-03 - map-drug-targets (auto): `make map` -> 104 drug_target rows, 24/25 drugs have a human target, 0 ingredients unmapped. Only non-human: xifaxan (rifaximin -> bacterial RNA polymerase, 4 rows, organism Bacteria). Spend-weighted coverage: 98.84% of 2024 gross spend across the 24 CMS-matched drugs ($99,842,697,461 total; xifaxan $1,158,111,409). Doubts: (1) xifaxan is not in unmapped.csv even though the skill says it should be, with its reason; (2) metformin (Janumet) mapped to 51 rows (50 mitochondrial complex I subunits + GPD2), which would swamp target counts; needs a manual decision; (3) ibrance lists cyclin D1 (P24385) twice under two complexes; (4) stelara matched no 2024 CMS spend, so the regex needs a fix (curate-reference task). `make gate1` currently fails: 91 unclassed targets, stelara has no spend.
- 2026-11-03 - map-drug-targets (manual): metformin (Janumet) trimmed to one target, GPD2 (P43304, ChEMBL CHEMBL3391681), per the owner's decision; this replaces 50 complex I subunits plus GPD2. Palbociclib (Ibrance) hand-mapped so cyclin D1 (P24385) appears once, keeping CDK6 (Q00534) and CDK4 (P11802). The pipeline now lists ingredients that have only non-human targets in unmapped.csv: xifaxan/rifaximin ('no human target; ChEMBL targets are Bacteria'). Result: 53 drug_target rows, 41 distinct human UniProt targets, 24/25 drugs with a human target. Doubt: picking GPD2 over complex I is a judgement call, since metformin's mechanism is contested; README should say so. gate1 still fails: 41 unclassed targets (next task) and stelara has no 2024 spend.
- 2026-11-03 - map-drug-targets (classes): 41/41 human targets classed from the ChEMBL protein_classification tree (source_url = ChEMBL target page). IL12A, IL12B, IL23A and TNF are classed from UniProt 'Cytokine' keywords, because IL12A and IL23A have no ChEMBL single-protein target. Counts: Kinase 13, Other enzyme 7, GPCR 6, Cytokine or receptor 4, Other 4, Protease 3, Nuclear receptor 2, Transporter 2. Doubts: the 'Other' class is CCND1 (cyclin, the regulatory partner of CDK4/6) plus CRBN/DDB1/CUL4A (ChEMBL 'Unclassified'), yet RBX1 from the same CRL4 ligase is 'Other enzyme' per ChEMBL; GUCY2C (receptor guanylate cyclase) is 'Other enzyme'. gate1 now fails only on stelara having no 2024 CMS spend.
- 2026-11-03 - curate-reference: CMS lists Stelara's brand as `Stelara*` (footnote marker), so cms_brand_regex is now `^stelara\*?$`. No other ustekinumab brands appear in the CMS data. Stelara 2024 gross spend $3,378,017,374. All 25 drugs now match 2024 spend, totalling $103,220,714,835 gross. Spend-weighted human-target coverage is 98.88% (xifaxan $1,158,111,409 is the only gap).
- 2026-11-03 - gate-check: `make gate1` -> `PASS gate 1`. Day 1 done. The fresh-eyes review (gate-check step 4) needs README, figures and data/processed, which arrive on Day 2, so it runs with gate 2. Reminder for Day 2: list and negotiated prices in negotiated_drugs.csv are still empty or unverified.
- 2026-11-03 - curate-reference (prices): opened both CMS fact sheets (IPAY 2026 Aug 2024; IPAY 2027 Nov 2025; saved under data/raw/factsheets/). All 15 second-cycle prices (from news coverage) matched the fact sheet exactly. Filled the 10 first-cycle drugs, which had no prices. All 25 rows now verified=true with the fact-sheet URL. Check: the discount recomputed from list and negotiated price rounds to the CMS-printed % for all 25. Doubts for the write-up: (1) list prices come from different years (CY2023 WAC for the 2026 cycle, CY2024 WAC for the 2027 cycle), noted per row; (2) the NovoLog price covers the Fiasp/NovoLog family; (3) the semaglutide price covers Ozempic, Rybelsus and Wegovy.
- 2026-11-03 - analyze-question: `make analyze` -> target_spend.csv 59 rows, price_cuts.csv 25 rows, 3 figures. Reconciliation: equal-split sum $102,062,603,426.69 = first_target sum = independent match_spend total for the 24 mapped drugs (2024); all 25 drugs total $103,220,714,835.29, the gap being xifaxan. Sensitivity (equal vs first_target): BTK ranks 5 -> 7; NR3C1 ranks 8 -> 4 (Breo/Trelegy spend goes all to the glucocorticoid receptor under first_target). Top 3 unchanged. Q2: 25 drugs (both cycles priced); only xifaxan lacks a class, because it has no human target. Figure fixes: Q2 shows xifaxan as 'No human target' instead of 'Unclassified'; the Q2 footnote no longer says 'savings' and now states the list-price years; label overlap and axis clipping fixed; the Q1 class figure footnote gives its source. Tests: two tests hard-coded the scaffold's 15 unverified prices; updated to 25 verified, and the gate-2 'unverified' check is still exercised by marking one row false. Note: the previous commit (price fill) was pushed with those two tests failing. Doubt for write-findings: class-level totals and medians are not in any processed CSV, so README can only quote per-target and per-drug numbers unless a class summary table is added.
- 2026-11-03 - analyze-question (class summary): owner approved a new processed table, data/processed/class_summary.csv (contract CLASS_SUMMARY, decisions.md entry, unit test; gate 2 now requires it). 8 classes. Protease 33.8% of equal-split gross 2024 spend, GPCR 22.1%, Transporter 18.0%, Kinase 7.7%. Median list-to-negotiated cut: Nuclear receptor 73.2% (n=3), Protease 70.2% (n=6), Kinase 44.6% (n=4). Also corrected the list_price_30d_usd descriptions (CY2023 vs CY2024 WAC by cycle). make test 8 passed; gate2 fails only on README, as expected.
