# Eval results

Run on 2026-11-05 and rerun on 2026-11-08 (same scores) with Gemini on Vertex (Lead, Writer and Checker `gemini-3.5-flash`, Researchers `gemini-3.5-flash-lite`, judge `gemini-3.5-flash`).
Margins are the rough ±1/sqrt(n) bound; Inspect's stderr is shown too. Small n, so read these as a sanity check, not a benchmark.

| Eval | n | Score | ±1/sqrt(n) | stderr | How to rerun |
|---|---|---|---|---|---|
| Lead gate (clarify / refuse / research) | 30 | 28/30 = 0.93 | ±0.18 | 0.046 | `uv run inspect eval evals/task.py@gate` |
| Facts, full pipeline, judged against gold SQL | 10 | 10/10 = 1.00 | ±0.32 | 0.000 | `uv run inspect eval evals/task.py@facts --limit 10` |
| Facts: report cites sources / has "can't tell us" | 10 | 10/10, 10/10 | ±0.32 | | same run |
| Citation Checker, rules only | 10 planted + 10 controls | 9/10 caught, 0/10 false positives | ±0.32 | | `uv run python evals/planted_claims.py` |
| Citation Checker, rules + model | 10 planted + 10 controls | 10/10 caught, 0/10 false positives | ±0.32 | | `uv run python evals/planted_claims.py --model` |
| Disclosures researcher quotes (s1, s2, s3) | 6 quotes (2026-11-05), 4 quotes (2026-11-08) | 6/6 and 4/4 word for word in the cited record | | | `uv run python scripts/run_disclosures.py` |

## Notes

- **Gate misses.** Both are intent questions labelled clarify: "Are drug trials honest?" and "Do biotech companies lie to investors?". The Lead refused instead, and each refusal says what the tool can check (registry vs. 8-K discrepancies). That matches the rule that we never judge intent, so we kept the labels and count them as misses.
- **Facts.** These are registry questions (stated reason, results posted and when) for 5 stopped phase 2 trials from smaller sponsors, with targets computed by `gold_sql` over the snapshot. They test that the full pipeline reads the registry correctly. They do not test the SEC or publication lanes.
- **Planted claims.** The rules catch wrong dates, misquotes and overreaching words (hid, misled, withheld). The model pass adds the one the rules miss: a wrong status and reason ("withdrawn because of safety concerns" for a trial terminated for slow enrollment). Results are in `runs/planted_claims_rules.json` and `runs/planted_claims_model.json`.
- **Disclosures quotes.** Per-sample outputs are in `runs/disclosures_*.json`. For vTv (s1), the 8-K of 2021-02-24 says Elevage "did not meet its primary objective" while the registry says "for business reasons": the discrepancy sample.
- Inspect logs are written to `logs/inspect/` (gitignored). Open them with `uv run inspect view --log-dir logs/inspect`.
