# Decision log

One entry per decision that changes a contract, the scope, or a method. Newest first.

Format: `YYYY-MM-DD - decision - why - what changed`

- 2026-11-02 - Spend is split equally across a drug's human targets, with "first target only" as a sensitivity check - no public data weights targets by effect - `analysis.q1_target_spend`
- 2026-11-02 - Target classes come from a fixed list of 9 classes, curated by hand in `target_classes.csv` - keeps Q2 groups comparable and reviewable - `contracts.TARGET_CLASSES`
- 2026-11-02 - Scope is the 25 Part D drugs with negotiated prices (2026 and 2027 cycles) - two-day budget - `negotiated_drugs.csv`
