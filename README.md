# RxGenome

RxGenome links the 25 Medicare Part D drugs with negotiated prices to the human proteins they act on, then asks which protein targets absorb the most gross Part D spend and whether negotiation cut list prices harder for some target classes than others. It turns a drug-by-drug price list into a view of which biology the gross Part D spend on these 25 drugs is concentrated on.

## Findings

1. **Three targets absorb over half the gross spend.** Of the $102.1B gross 2024 Part D spend on the 24 negotiated drugs with a human target, factor Xa (F10; Eliquis, Xarelto) takes 26.5% ($27.0B), SGLT2 (SLC5A2; Farxiga, Jardiance) 16.4%, and the GLP-1 receptor (semaglutide) 14.9%. The next target, DPP-4, takes 5.4%. By class, proteases take 33.8% of gross spend, GPCRs 22.1% and transporters 18.0%.
2. **Kinase-targeted drugs had the lowest median list price cut, in a small sample.** The median cut from list price to negotiated price was 49.7% for the 5 drugs whose primary target is a kinase, against 70.2% for proteases (6 drugs) and 73.2% for nuclear receptors (3 drugs). Per drug, cuts ran from 37.6% (Imbruvica, BTK) to 84.8% (Janumet, DPP-4).
3. **Target class and list price level are confounded, so Q2 has no firm answer.** Four of the five kinase drugs are high-list-price specialty drugs (Imbruvica, Calquence, Ofev, Ibrance: $12,622 to $15,741 list price per 30 days) with cuts of 37.6% to 50.0%. The fifth, NovoLog/Fiasp ($495 list price, via the insulin receptor), was cut 76.0%. But a high list price does not always mean a small cut (Pomalyst, $21,744, cut 60.2%), and some lower-priced drugs had small cuts (Vraylar, $1,376, cut 44.0%). With 1 to 6 drugs per class, these data cannot separate target class from list price level or negotiation cycle.

![Gross 2024 Part D spend by protein target](figures/q1_spend_by_target.png)
![Gross 2024 Part D spend by target class](figures/q1_spend_by_class.png)
![List price to negotiated price cut by primary target class](figures/q2_price_cut_by_class.png)

## How it works

1. **Reference:** 25 negotiated drugs with list price and negotiated price from the two CMS fact sheets (`data/reference/negotiated_drugs.csv`).
2. **CMS spend:** the Medicare Part D Spending by Drug file, 2020–2024, reshaped to one row per drug per year.
3. **Crosswalk:** each ingredient goes through RxNorm and ChEMBL mechanisms to UniProt targets, with hand fixes (and reasons) in `manual_mappings.csv`; each target gets one of nine classes.
4. **Analysis:** gross spend is attributed to targets, and price cuts are grouped by primary target class (`data/processed/`).

Coverage: 24 of 25 drugs map to a human target, covering 98.88% of their 2024 gross spend. Xifaxan (rifaximin) acts only on bacterial RNA polymerase.

## Limits

- **Gross spend, before rebates.** CMS spend is gross, before manufacturer rebates, so Medicare's real cost for these drugs is lower than shown.
- **List price vs negotiated price.** Cuts compare the list price (WAC) with the negotiated price. Neither includes rebates, so the cut is larger than the true reduction after rebates. List prices are CY2023 for the 2026 cycle and CY2024 for the 2027 cycle.
- **Spend split.** A drug's gross spend is split equally across its human targets. Giving it all to the first target instead keeps the top three unchanged, but moves the glucocorticoid receptor (NR3C1) from 8th to 4th and BTK from 5th to 7th.
- **Q1 and Q2 group differently.** Q1 spreads gross spend over every target of a drug, while Q2 puts each drug in the class of its primary target only. So a class can hold many targets in Q1 but few drugs in Q2 (kinases: 13 targets, 5 drugs).
- **Mapping choices.** Metformin (in Janumet) is mapped to one target, GPD2, rather than ChEMBL's ~50 complex I subunits; its mechanism is contested. Classes follow ChEMBL's protein classification, so the insulin receptor counts as a kinase.
- **Scope.** Results cover the 25 negotiated drugs only and don't generalise to all of Part D.

## Reproduce

```bash
make setup && make ingest && make map && make analyze
```

`make gate2` checks every table, the figures and this README. Progress, checks and open doubts are in `docs/status.md`; method decisions are in `docs/decisions.md`.

## Data sources

- CMS [Medicare Part D Spending by Drug](https://data.cms.gov/summary-statistics-on-use-and-payments/medicare-medicaid-spending-by-drug/medicare-part-d-spending-by-drug)
- CMS negotiated price fact sheets: [2026 cycle](https://www.cms.gov/files/document/fact-sheet-negotiated-prices-initial-price-applicability-year-2026.pdf), [2027 cycle](https://www.cms.gov/files/document/fact-sheet-negotiated-prices-ipay-2027.pdf)
- [RxNorm](https://lhncbc.nlm.nih.gov/RxNav/) (NLM), [ChEMBL](https://www.ebi.ac.uk/chembl/) (EMBL-EBI), [UniProt](https://www.uniprot.org/)
