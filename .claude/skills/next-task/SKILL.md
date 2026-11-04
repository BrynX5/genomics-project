---
name: next-task
description: Pick and do the next unchecked task in the RxGenome plan. Use at the start of every session, or when asked to "keep going", "continue", "do the next step" or "run the project".
---

# Next task

You are running the project from its checklist. One task per pass, finished and committed, before the next.

## Steps

1. Read `docs/status.md`. Find the first unchecked `- [ ]` item under the current day.
2. Run `make validate`. If anything fails, fixing it is the next task, ahead of the checklist.
3. Load the skill that owns the task (the table in `CLAUDE.md` maps stage to skill) and follow it.
4. Check your work: `make validate` must pass, plus the task's own done-check from its skill.
5. Tick the item in `docs/status.md` and add a dated line under **Log** with what you did, key numbers, and open doubts.
6. Commit with a message like `<stage>: <what>`.
7. If the item was the last one for the day, run the `gate-check` skill.

## Stop and report instead of guessing when

- A task needs a decision listed under "Stop and ask" in `CLAUDE.md`.
- The same validation error survives two honest fix attempts.
- An API stays unreachable after the pipeline's own retries. Record it under **Blocked** in `docs/status.md`, then move on to a task that doesn't need it.

## Output to the owner

Report in three lines: what you finished, the key number, and what comes next. Skip the play-by-play.
