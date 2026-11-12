# Submission evidence

The [rubric checklist](docs/DESIGN_NOTES.md#rubric-checklist) maps grading criteria to project evidence. The same document records where the implementation departs from the course starters.

| What to verify | Evidence |
| --- | --- |
| Researchers run concurrently in fresh contexts | [Parallelism tests](tests/test_parallel.py) |
| The Lead follows up on gaps and respects the round cap | [Gap loop tests](tests/test_gap_loop.py) |
| The report compares registry and investor accounts | [Saved discrepancy report](runs/s1_discrepancy_latest.md) |
| The agent distinguishes missing results from missing evidence | [Saved results search](runs/s2_never_posted_latest.md) and [limitations example](runs/cant_answer_latest.md) |
| The deployed service answered the sample questions | [Recorded deployment checks](runs/deployed_samples_check.json) and [script for a fresh check](tests/test_deploy.sh) |
