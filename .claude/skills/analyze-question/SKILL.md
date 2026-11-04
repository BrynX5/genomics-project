---
name: analyze-question
description: Answer Q1 (gross spend by protein target) and Q2 (list-to-negotiated price cut by target class), producing the processed tables and three figures, and check them. Use on Day 2 after gate 1 passes, or when the inputs change.
---

# Analyze Q1 and Q2

All the logic lives in `src/rxgenome/analysis.py`. Run it, check it, and note what it shows. Put new analysis logic in that file with a test, never in a notebook only.

## Run

```
make analyze
```

This writes `data/processed/target_spend.csv` (both split rules), `data/processed/price_cuts.csv`, and three figures in `figures/`.

## Check before you believe it

1. **Totals reconcile.** The `equal` rows of `target_spend` must sum to the latest-year gross spend of the mapped drugs. Compute that total separately from `partd_drug_year` with `match_spend`, and log both numbers.
2. **Sensitivity.** Compare the top 5 targets under `equal` and `first_target`. Log any target whose rank moves by 2 or more places. This becomes a sentence in the README's limits.
3. **Q2 coverage.** `price_cuts` should have the 15 second-cycle drugs, unless more cycles have prices. A drug with no `target_class` means `target_classes.csv` is incomplete, so go back to `map-drug-targets`.
4. **Look at each figure.** Open each PNG and check that the labels are readable, the axis says gross or list price, and the footnote is present.

## Record the findings

Under **Findings draft** in `docs/status.md`, write three findings, each one sentence with its number copied from a processed CSV. For example: "Factor Xa accounts for X% of gross 2024 spend on the 25 negotiated drugs (target_spend.csv, equal split)."

## Done when

`make validate` passes, both checks are logged with numbers, and three findings are drafted.
