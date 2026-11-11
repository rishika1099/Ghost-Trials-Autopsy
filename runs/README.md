# Agent runs

Saved outputs from the agent, kept as evidence for the README and the evaluation.

| Files | What they are | Made by |
|---|---|---|
| `*_latest.md` | The latest report for each sample query in `samples.json`, quoted in the README | `scripts/run_samples.py` |
| `20261110-0925_s*.json` | Full traces of those runs: every tool call, timings, citations checked | `scripts/run_samples.py` |
| `deployed_samples_check.json` | All six sample queries sent to the deployed service at once: time, response shape, agents | final check before submission |
| `trials_*.json` | The trials researcher alone on 10 briefs, each claim checked mechanically | `scripts/run_trials.py` |
| `disclosures_*.json` | The disclosures researcher on the samples; every 8-K quote checked word for word | `scripts/run_disclosures.py` |
| `publications_*.json` | The publications researcher on the samples, and the live fallback on 5 trials | `scripts/run_publications.py`, `scripts/check_publications_live.py` |
| `planted_claims_*.json` | The Citation Checker on 10 planted errors and 10 correct controls | `evals/planted_claims.py` |
| `history/` | Earlier runs of the same queries, kept to show how the agent changed as prompts and tools were tuned | `scripts/run_samples.py` |

The no-tools answers to the same queries (same model, no tools, no system prompt) are in `../baseline/`.
