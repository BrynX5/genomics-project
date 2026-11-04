# Status

Claude: read this first every session. Tick items as you finish them, and add a dated line to the Log.

## Day 1: data and crosswalk

- [x] Run `make setup`, then `make validate` (reference tables pass)
- [x] ingest-cms: build `partd_drug_year.csv`; log the year range and latest-year gross total
- [x] map-drug-targets: run `make map`; log coverage
- [x] map-drug-targets: hand-map failures in `manual_mappings.csv`
- [x] map-drug-targets: classify every human target in `target_classes.csv`
- [ ] curate-reference: fix any CMS regex that matched no spend
- [ ] gate-check: `make gate1` passes

## Day 2: analysis and write-up

- [ ] curate-reference: verify the 15 second-cycle prices against the CMS fact sheet
- [ ] analyze-question: `make analyze`; reconciliation and sensitivity checks logged
- [ ] analyze-question: draft three findings below
- [ ] write-findings: README.md
- [ ] gate-check: `make gate2` passes, plus the fresh-eyes review

## Findings draft

(empty)

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
