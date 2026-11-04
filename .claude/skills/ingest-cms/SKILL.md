---
name: ingest-cms
description: Download and reshape the CMS Medicare Part D Spending by Drug file into data/interim/partd_drug_year.csv. Use on Day 1, or when the CMS file needs refreshing or its columns changed.
---

# Ingest CMS Part D spending

## Run

```
make ingest
```

This downloads the file into `data/raw/partd_spending_by_drug.csv` (cached; delete it to re-download). It keeps only the `Mftr_Name == "Overall"` rows, reshapes to one row per drug per year, and validates against the `partd_drug_year` contract.

## Check the result

1. The years should run to the latest edition, which currently ends in 2024. Confirm with `python -c "import pandas as pd; print(pd.read_csv('data/interim/partd_drug_year.csv').year.agg(['min','max']))"`.
2. Sanity check the scale. Total gross spend for the latest year should be in the hundreds of billions of dollars. Write the figure you got in the status log.
3. Spot check one drug, for example Eliquis, against the CMS data viewer: https://data.cms.gov/summary-statistics-on-use-and-payments/medicare-medicaid-spending-by-drug/medicare-part-d-spending-by-drug.

## If it fails

- **"no Tot_Spndng_... columns"**: CMS renamed columns. Read the header of the raw file, update `reshape_cms` in `src/rxgenome/pipeline.py`, and log the change in `docs/decisions.md`.
- **Network error**: check the dataset ID in `pipeline.py` against the catalog at https://catalog.data.gov/dataset/medicare-part-d-spending-by-drug-938d3. If it is still unreachable, ask the owner to download the CSV from the landing page into `data/raw/partd_spending_by_drug.csv`, then rerun.
- Never edit the raw file. Fix the code instead.

## Done when

`make validate` passes for `partd_drug_year`, and the year range and latest-year total are logged in `docs/status.md`.
