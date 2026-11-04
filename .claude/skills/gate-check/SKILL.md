---
name: gate-check
description: Run the Day 1 or Day 2 gate, fix or route every failure, and record the result. Use when a day's checklist is complete, before telling the owner a day is done, or when asked "are we done?".
---

# Gate check

A day is done only when its gate passes. Run it, don't argue with it.

## Steps

1. Run `make gate1` or `make gate2`.
2. For each failure, find the skill that owns it in the table in `CLAUDE.md`, fix it there, and rerun the gate.
3. Repeat until it passes. If one failure survives two honest attempts, stop and report it to the owner with what you tried.
4. Get a fresh pair of eyes. Start a subagent that hasn't seen your work, and ask it to read `README.md`, the three figures and `data/processed/` and report any number that doesn't match a processed CSV, any figure missing a gross or list label, and any claim the data can't support. Fix what it finds and rerun the gate.
5. In `docs/status.md`, mark the gate as passed with the date and the gate's final output.

## Done when

The gate prints `PASS`, the review findings are resolved, and the status file records both.
