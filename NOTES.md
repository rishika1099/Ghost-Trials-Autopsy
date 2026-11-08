# NOTES

Working notes for the team: how the three course starters were combined, where we departed from them, and the rubric checklist with evidence.

## How the three starters were combined

| Starter | What we kept | Where it lives |
|---|---|---|
| `wikipedia-deep-research` (Deep Research, our path) | Agents SDK + LiteLLM on Gemini via Vertex, `set_tracing_disabled`, model settings (90 s timeout, 2 retries), Lead / Researcher / Writer roles, fresh-context researchers, SSE streaming of agent activity, the context-recording hooks (`context_panel.py`) | `ghost/pipeline.py`, `ghost/hooks.py`, `ghost/context_panel.py`, `app.py` `/run` |
| `subway-survey-text2sql-improved` (Text2SQL) | The offline build step (cleaned DuckDB + schema mappings with descriptions and enum values), `read_mappings` / `get_enum_values` tools, few-shot SQL in the prompt, the read-only connection, the `'NA'` guardrail, the `/chat` request and response models | `scripts/build_snapshot.py`, `data/mappings.json`, `ghost/db.py`, `ghost/tools.py`, `prompts/researcher.md`, `app.py` |
| `nyc-311-agent` (Evals) | Inspect tasks, silver samples with `gold_sql` and a source for each, deterministic scorers plus a model judge with a golden reference | `evals/` |

## Conflicts with the starter, and what we did

1. **Lead loop in code, not in the prompt.** The starter's Lead calls a `research` tool and decides on its own when to stop ("at most twice"). CLAUDE.md needs a hard round cap, a wall clock budget, structured gap JSON, and a clarify gate that provably makes no researcher calls. So the Lead is called twice per round with structured outputs (`LeadPlan`, then `LeadReview` with `gaps`), and `dispatch_researchers` is a code step that runs every brief with `asyncio.gather`. It is recorded in `tool_calls` as a `lead` call named `dispatch_researchers`, with the per-researcher start and end times in its result.
2. **/chat shape.** The deep research starter only has `/run` (SSE). We took the `/chat` models from the Text2SQL starter, which match Project 1: `{message, session_id}` in, `{response, session_id, tool_calls}` out, each tool call `{name, args, result}`. We added only `agent` to each tool call, as the assignment says. Confirmed on 2026-11-07 against Layer Lab (Project 1) `app.py`: `ChatRequest{message, session_id}`, `ChatResponse{response, session_id, tool_calls}`, tool calls `{name, args, result}`. Ours is identical plus `agent`.
3. **Writer citations.** The starter's Writer cites Wikipedia links inline. Ours cites evidence ids in a structured output; code numbers them `[n]` and builds the source list from the evidence store, so a number can never point at a source the agents didn't fetch.
4. **Fourth agent shape.** Added a Citation Checker (not in the starter).
5. **Frontend.** Replaced completely (the starter's two-column Wikipedia page and context panel UI are gone). The context-recording code is kept: each researcher's first message list is in the trace (`first_contexts`) as proof of fresh contexts.
6. **SEC lane needs a contact.** SEC rejects requests without a contact email in the User-Agent. It is read from `SEC_USER_AGENT`; no personal email is in the repo. On Cloud Run it comes from the Secret Manager secret `sec-user-agent` (set 2026-11-07).

## Rubric checklist

| Rubric | Status | Evidence |
|---|---|---|
| README and valid `submission.json` | done | `README.md` (all 3 sample write-ups: expected answer, source, no-tools and agent answers verbatim; vague and can't-answer examples), `submission.json` (`path: "research"`, rm4318, svs2148, ks4423, live `deploy_url`) |
| Deployed and reachable | done | https://ghost-trials-autopsy-895402809785.us-central1.run.app (Cloud Run, us-central1, 600 s timeout, 2 GiB, `min-instances=1` since 2026-11-07); continuous deploy: Cloud Build trigger `deploy-on-main` runs `cloudbuild.yaml` on every push to `main`; `SEC_USER_AGENT` from Secret Manager (`sec-user-agent`); `/health` 200; `bash tests/test_deploy.sh` result below |
| Clear purpose | done | page header; README intro |
| Answers its research questions correctly | done | all three samples hand-checked in README: vTv NCT03980730 (discrepancy), Sorrento NCT04903327 (never posted), Entero (sponsor, 3 trials, 2026-11-07 run: 34 citations checked, 0 removed); `scripts/run_trials.py`: 10 trials briefs, 0 problems; `evals/RESULTS.md`: facts eval 10/10, gate 28/30 |
| Unique dataset or problem | done | joined trials + 8-K + publications snapshot (`data/autopsy.duckdb`); sign-up sheet entry |
| Data the model doesn't know | done | `baseline/` vs `runs/` in README: for NCT04903327 the no-tools model gives the wrong registry reason and blames a bankruptcy that came after the trial ended; for vTv it says the stories match (they don't); for Entero it names none of the three trials, and its three NCT IDs belong to other sponsors (Radboud, Pfizer, a Turkish university) |
| Admits what the data can't answer | done | "What the data can't tell us" in every report (`ghost/report.py`); `tests/test_cant_answer.py` |
| 3+ agent shapes | done | lead, researcher (3 lane configs), writer, checker in `ghost/pipeline.py` |
| Parallel fan-out in fresh contexts | done | `tests/test_parallel.py`; timing bars in the trace panel |
| Lead goes back for more, with a cap | done | `tests/test_gap_loop.py`; round count in the trace |
| Vague input asks for clarification | done | `tests/test_clarify.py`; README example |
| Accurately cited | done | `check_citations` in every trace (`citations_checked: n, removed: k`); `tests/test_citations.py`; planted errors: 10/10 caught, 0/10 false positives (`evals/RESULTS.md`) |
| Frontend changed from starter | done | `index.html` |
| Agent does something interesting | done | registry vs. investor vs. publication discrepancy finder: `discrepancies` table (43 trials labelled, 7 hand-checked), vTv sample in README |
| One data source per team member | done | 3 lanes, 6 sources; owners in README |

## Publication links: what counts as "published"

Spot check on 2026-11-05: 20 random rows per `link_type` from `publications`, each title read against the trial's title and drugs.

| link_type | Reports this trial | Other paper on the drug or programme (pooled, related trial) | Review, background or unrelated |
|---|---|---|---|
| ctgov_result | 14 | 2 | 4 (all 4 published years before the trial started) |
| pubmed_si | 13 | 4 | 3 (Cochrane and other reviews) |
| ctgov_derived | 15 | 4 | 1 |
| europepmc_mention | 1 | 1 | 18 (reviews that list the NCT ID) |

Decision: only `ctgov_result`, `pubmed_si` and `ctgov_derived` links published on or after the trial's `start_date` count as a possible results paper. `find_publications` labels every article `results_candidate`, `background` (published before the trial started; 280 of the 1,663 `ctgov_result` rows) or `mention_only` (Europe PMC). The researcher confirms a candidate with `get_abstract` before calling it the trial's results, since about a quarter of candidates are pooled analyses or reviews. When no article is a candidate, the tool returns a citable "No results publication found for NCT..." record listing the mentions, and it now also tries live PubMed `[si]` in case a paper came out after the snapshot.

Effect on `get_snapshot_stats`: `pct_stopped_with_publication` drops from 81.8% (any link) to 21.4% (formal link after start). The new `pct_stopped_mentioned_only` (59.9%) is the share of stopped trials named only in other papers. The timeline no longer draws a "Publication" marker for mentions or background papers. Tests: `tests/test_publications_tools.py`. Live fallback check on trials with no snapshot links: `uv run python scripts/check_publications_live.py`.

## Writer review on the three samples

Read `runs/s1_discrepancy_latest.md`, `s2_never_posted_latest.md` and `s3_sponsor_latest.md` (2026-11-05 runs) and their timeline JSON on 2026-11-07. Registry dates, results due and results posted were right in all three (s1: due 2021-12-01, posted 2022-01-21, 51 days late, matches `trial_derived`). Problems found and what changed:

| Problem | Where | Fix |
|---|---|---|
| "No results paper" claims cited the reviews that only mention the trial, so unrelated papers (a niclosamide lung cancer study, an ovarian anti-aging review) appeared as sources | s1, s2, s3 | `find_publications` returns a citable `pubmed:none:<nct>` record; `writer.md` says to cite it, never the mentions |
| Every "Publication" marker on the timelines was one of those mentions | s1 (5), s2 (5), s3 (all) | timeline keeps only `results_candidate` articles; checked: all five sample trials now have 0 candidates |
| `cant_tell` ended with a sentence about the time or round budget although research finished | s1, s3 | `report.py` drops model sentences about run limits and keeps only the code's own budget note (`tests/test_publications_tools.py`) |
| Answer opened with an intent disclaimer the question did not ask for | s1 | `writer.md`: the disclaimer leads only when the question itself asks for intent, the law or safety |
| "stopped in September 2022" used the primary completion date | s3 | `writer.md`: the registry has no stop date; say "primary completion" |
| "not published in scientific literature" overstated what we searched | s2 | `writer.md`: "no results publication found in PubMed or Europe PMC" |

Evidence claims were one fact each and `cant_tell` was otherwise specific to each question. To confirm on real runs: `uv run python scripts/run_publications.py` (lane checks) and `uv run python scripts/run_samples.py`.
