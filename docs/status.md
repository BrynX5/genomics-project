# Status

Claude: read this first every session. Tick items as you finish them, and add a dated line to the Log.

## Day 1: data and crosswalk

- [ ] Run `make setup`, then `make validate` (reference tables pass)
- [ ] ingest-cms: build `partd_drug_year.csv`; log the year range and latest-year gross total
- [ ] map-drug-targets: run `make map`; log coverage
- [ ] map-drug-targets: hand-map failures in `manual_mappings.csv`
- [ ] map-drug-targets: classify every human target in `target_classes.csv`
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
