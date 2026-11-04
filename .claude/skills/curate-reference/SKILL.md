---
name: curate-reference
description: Add, correct or verify rows in data/reference/negotiated_drugs.csv (the drugs selected for Medicare price negotiation, their list and negotiated prices, and the regexes that find them in CMS data). Use when prices need verifying, a new negotiation cycle is announced, or a drug fails to match CMS spend.
---

# Curate reference data

`negotiated_drugs.csv` is the only hand-written table the analysis depends on. Every value must trace to a page.

## Contract

Run `make describe` and read the `negotiated_drugs` section before editing. Key rules:
- `drug_id` is a lowercase slug and never changes once used.
- A price needs `price_source_url`. `verified` is `true` only after a check against the official CMS fact sheet.
- `negotiated_price_30d_usd` must be below `list_price_30d_usd`.

## Verify prices (the Day 2 gate needs this)

1. Open the CMS fact sheet for that cycle. For the 2027 cycle it is https://www.cms.gov/files/document/fact-sheet-negotiated-prices-ipay-2027.pdf. For other cycles, start from https://www.cms.gov/priorities/medicare-prescription-drug-affordability/overview/medicare-drug-price-negotiation-program.
2. For each row, compare both prices to the fact sheet.
   - If they match: set `verified=true` and put the fact sheet URL in `price_source_url`.
   - If they differ: use the fact sheet value, set `verified=true`, and say in `notes` what changed and from what.
   - If the fact sheet doesn't list a price: leave `verified=false` and say why in `notes`.
3. Run `make validate`.

## Fix a CMS match (when gate 1 says a drug matched no spend rows)

1. Look at the real names: `grep -i '<ingredient>' data/interim/partd_drug_year.csv | cut -d, -f1,2 | sort -u`.
2. Adjust `cms_generic_regex` and `cms_brand_regex`. CMS truncates generic names at about 30 characters, so match prefixes such as `^flutic.*umecl.*vilant`.
3. Check that you matched only the selected drug. For example, `sitagliptin` alone would also catch Zituvio, which wasn't selected, so filter by brand as well.
4. Run `make gate1` and confirm the drug no longer appears in the "no CMS spend rows matched" line.

## Add a new cycle

When CMS announces new prices (for example the 2028 cycle), add rows with `cycle=2028` and the correct `part`. Part B-only drugs have no Part D spend, so note that in `notes`. Get the owner's OK first, because a new cycle changes scope.

## Done when

`make validate` passes, and every changed row has a source URL that you actually opened in this session.
