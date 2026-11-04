---
name: write-findings
description: Write or update README.md with the project question, pipeline, figures, findings and limits, using only numbers from data/processed. Use at the end of Day 2, or after the analysis changes.
---

# Write the findings

A hiring manager reads the README in two minutes. It should lead with the answers, show the three figures, and state the limits plainly.

## Structure (keep these headings, since gate 2 checks for `## Findings`)

1. `# RxGenome`: one sentence on what it does, one on why it matters.
2. `## Findings`: three numbered findings, each with its number, then the three figures inline (`![...](figures/....png)`).
3. `## How it works`: the four stages in four lines, plus the coverage figure (drugs mapped, and spend-weighted coverage).
4. `## Limits`, always including:
   - Spend is gross, before manufacturer rebates, so real Medicare cost is lower.
   - Price cuts compare list price to negotiated price, not net price, so they overstate real savings.
   - Spend is split equally across a drug's targets, and the first-target rule changes the ranking as logged.
   - Results cover the 25 negotiated drugs only and don't generalise to all of Part D.
5. `## Reproduce`: `make setup && make ingest && make map && make analyze`.
6. `## Data sources`: CMS, RxNorm, ChEMBL and UniProt, with links.

## Rules

- Copy every number from `data/processed/*.csv` or the status log's checks. Never round it differently in two places, and never compute it in your head.
- Say "gross spend" and "list price" every time. Never use "net", "savings" or "Medicare paid".
- Keep it to one screen of text plus the figures. Move detail to `docs/`.

## Done when

`make gate2` reports no README problems.
