# Decision log

One entry per decision that changes a contract, the scope, or a method. Newest first.

Format: `YYYY-MM-DD - decision - why - what changed`

- 2026-11-03 - Q3a firm = parent company, rolled up from CMS labeler names, by owner decision; joint ventures (ViiV), spun-off companies (Sandoz, Organon, Viatris) and separately listed majority-owned companies (Bausch & Lomb) are left out - ownership in the 2024 spend year is what counts, and each link must have a source - new contracts FIRM_LABELERS, PARTD_MFTR_YEAR, FIRM_EXPOSURE; `pipeline.reshape_cms_mftr`, `analysis.firm_exposure`

- 2026-11-03 - Scope extended to a firm track (Q3a exposure, Q3b drivers of the cut, Q3c promotion), approved by the owner after gate 2 - the target view could not answer Q2; firm economics might - docs/status.md Extensions

- 2026-11-03 - New processed table `class_summary` (Q1 gross spend and Q2 price-cut stats by target class), approved by the owner - README rule 3 needs every class-level number to come from data/processed - `contracts.CLASS_SUMMARY`, `analysis.class_summary`
- 2026-11-03 - Wording fix to the list_price_30d_usd descriptions in negotiated_drugs and price_cuts: list prices are CY2023 WAC for cycle 2026 and CY2024 WAC for cycle 2027, not "2024" for all - the CMS fact sheets say so - descriptions only, no rule changed
- 2026-11-03 - Metformin hand-mapped to one target (GPD2) instead of ChEMBL's ~50 complex I subunits, by owner decision - the subunits would swamp target counts - `manual_mappings.csv`

- 2026-11-02 - Spend is split equally across a drug's human targets, with "first target only" as a sensitivity check - no public data weights targets by effect - `analysis.q1_target_spend`
- 2026-11-02 - Target classes come from a fixed list of 9 classes, curated by hand in `target_classes.csv` - keeps Q2 groups comparable and reviewable - `contracts.TARGET_CLASSES`
- 2026-11-02 - Scope is the 25 Part D drugs with negotiated prices (2026 and 2027 cycles) - two-day budget - `negotiated_drugs.csv`
