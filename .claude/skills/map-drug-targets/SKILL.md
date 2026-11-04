---
name: map-drug-targets
description: Build and repair the drug-to-protein-target crosswalk (RxNorm, ChEMBL, UniProt), hand-map failures in manual_mappings.csv, and assign each target a class in target_classes.csv. Use on Day 1, or when gate 1 reports unmapped drugs or unclassed targets.
---

# Map drugs to targets

The crosswalk is the riskiest part of the project. Measure it, fix it with evidence, and never fake it.

## 1. Run the automatic mapping

```
make map
```

This writes `data/interim/drug_target.csv` and `data/interim/unmapped.csv`. Write the printed coverage line (`N/25 drugs have a human target`) in the status log.

## 2. Hand-map what failed

For each row in `unmapped.csv`, and any drug whose only targets are non-human or have no UniProt accession:

1. Look up the ingredient on ChEMBL with `https://www.ebi.ac.uk/chembl/api/data/molecule/search.json?q=<name>`. Then get its mechanism from `.../mechanism.json?parent_molecule_chembl_id=<id>`.
2. Confirm the human UniProt accession at `https://rest.uniprot.org/uniprotkb/<accession>.json`.
3. Add one row per ingredient-target link to `data/reference/manual_mappings.csv`, with a `reason` and a `source_url`.
4. Run `make map` again. Manual rows replace automatic ones for that ingredient.

Known hard cases:
- **Biologics** (etanercept, ustekinumab): the target may be a protein complex with several UniProt components. Keep all of them.
- **Insulin aspart**: maps to the insulin receptor (INSR).
- **Combinations** (Trelegy, Breo, Janumet, Entresto): one target set per ingredient. The ingredient order in `generic` decides which target is primary (target_order = 1).
- **Rifaximin** acts on bacterial RNA polymerase. It has no human target, so leave it in `unmapped.csv` with that reason. The gate allows up to 2 drugs without a human target.

## 3. Classify every human target

For each UniProt accession in `drug_target.csv` with a human organism, add a row to `data/reference/target_classes.csv`.

- Choose the class from the controlled list only: Kinase, Protease, Other enzyme, GPCR, Ion channel, Transporter, Nuclear receptor, Cytokine or receptor, Other.
- Base the choice on the UniProt protein family or ChEMBL target classification, and put that page in `source_url`.
- Examples: factor Xa (F10) is Protease; SGLT2 (SLC5A2) is Transporter; GLP-1R is GPCR; BTK is Kinase; DPP-4 is Protease; TNF is Cytokine or receptor.

## Done when

`make gate1` reports no crosswalk problems. Log coverage weighted by spend (the share of latest-year gross spend whose drug has a human target), not just the drug count.
