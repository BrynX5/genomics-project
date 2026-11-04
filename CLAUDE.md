# RxGenome: project rules for Claude Code

You are the engineer on a two-day portfolio project. The owner reviews your work; you do the building.

**Mission.** Link the 25 Part D drugs with Medicare negotiated prices to their protein targets, then answer:
- **Q1** Which protein targets absorb the most gross Part D spend among these drugs?
- **Q2** Did negotiation cut list prices harder for some target classes than others?

Anything else (more drugs, pathways, dashboards, models) is out of scope. Add it to the Extensions list in `docs/status.md` and keep going.

## Start every session

1. Read `docs/status.md` to see what is done and what comes next.
2. Run `make validate` to see the state of every table.
3. Use the `next-task` skill to pick the next task and do it.

## Workflow and the skill that owns each stage

| Stage | Skill | Writes |
|---|---|---|
| Reference data | `curate-reference` | `data/reference/negotiated_drugs.csv` |
| CMS spending | `ingest-cms` | `data/interim/partd_drug_year.csv` |
| Crosswalk | `map-drug-targets` | `data/interim/drug_target.csv`, `unmapped.csv`, `data/reference/manual_mappings.csv`, `target_classes.csv` |
| Analysis | `analyze-question` | `data/processed/*.csv`, `figures/*.png` |
| Write-up | `write-findings` | `README.md` |
| Day gates | `gate-check` | `docs/status.md` |

Each stage reads only what the stages before it wrote. Don't skip ahead.

## Data contracts are law

- Every table has a contract in `src/rxgenome/contracts.py`. Run `make describe` to see them all.
- A hook validates any table file you write. If it blocks you, fix the data. Don't loosen the contract to get around it.
- To change a contract on purpose, edit `contracts.py`, add a dated entry to `docs/decisions.md`, then run `make test`.
- `data/raw/` is read-only. Never hand-edit a downloaded file. All fixes go in `data/reference/`.

## Non-negotiable rules

1. **No number from memory.** Every price, date or ID comes from a page you opened or an API response, and its URL goes in the row.
2. **Label every figure.** CMS spend is *gross* (before rebates). Prices are *list* vs *negotiated*. Never write "net", "savings" or "Medicare paid" for these numbers.
3. **Generated numbers only.** Any number in `README.md` must come from a file in `data/processed/`. Quote it, don't recompute it in prose.
4. **Manual over automatic, with a reason.** When ChEMBL is wrong or empty, add a row to `manual_mappings.csv` with a reason and a source URL. Never patch `drug_target.csv` directly.
5. **Small steps.** Make one task, validate it, commit it, then move on. Commit messages say `<stage>: <what>`, for example `map: hand-map insulin aspart to INSR`.
6. **Stop and ask** before deleting data, changing scope, changing a contract's meaning, or pushing to a remote.

## Commands

```
make setup      # create .venv and install requirements
make describe   # print every data contract
make validate   # validate every table that exists
make ingest     # CMS Part D -> data/interim/partd_drug_year.csv
make map        # negotiated drugs -> protein targets
make analyze    # Q1, Q2 tables and three figures
make gate1      # Day 1 gate      make gate2   # Day 2 gate
make test       # unit tests for contracts and analysis
```

## Done means

- Day 1: `make gate1` passes (at least 23/25 drugs mapped to a human target, every target classed, every drug matched to CMS spend).
- Day 2: `make gate2` passes (tables and figures exist, prices verified, README has findings with no placeholders and correct labels).
- After every task: `docs/status.md` is updated with what you did, the numbers you got, and anything you're unsure about.
