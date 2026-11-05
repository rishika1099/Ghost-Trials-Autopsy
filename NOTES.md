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
2. **/chat shape.** The deep research starter only has `/run` (SSE). We took the `/chat` models from the Text2SQL starter, which match Project 1: `{message, session_id}` in, `{response, session_id, tool_calls}` out, each tool call `{name, args, result}`. We added only `agent` to each tool call, as the assignment says. **To do: confirm against the Layer Lab (Project 1) repo that the field names match exactly.**
3. **Writer citations.** The starter's Writer cites Wikipedia links inline. Ours cites evidence ids in a structured output; code numbers them `[n]` and builds the source list from the evidence store, so a number can never point at a source the agents didn't fetch.
4. **Fourth agent shape.** Added a Citation Checker (not in the starter).
5. **Frontend.** Replaced completely (the starter's two-column Wikipedia page and context panel UI are gone). The context-recording code is kept: each researcher's first message list is in the trace (`first_contexts`) as proof of fresh contexts.
6. **SEC lane needs a contact.** SEC rejects requests without a contact email in the User-Agent. It is read from `SEC_USER_AGENT`; no personal email is in the repo.

## Rubric checklist

| Rubric | Status | Evidence |
|---|---|---|
| README and valid `submission.json` | in progress | `README.md`, `submission.json` (deploy_url filled; README sample write-ups for s1 (vTv) and s2 done, s3 still to do) |
| Deployed and reachable | in progress | https://ghost-trials-autopsy-895402809785.us-central1.run.app (Cloud Run, us-central1, 600 s timeout, 2 GiB); `/health` 200; `bash tests/test_deploy.sh` PASS in 169 s on the never-posted sample. To do: continuous deploy from GitHub, `min-instances=1` before grading, `SEC_USER_AGENT` secret |
| Clear purpose | done | page header; README intro |
| Answers its research questions correctly | in progress | `samples.json`, `runs/*_latest.md`; never-posted (NCT04903327) and discrepancy (vTv NCT03980730) samples hand-checked in README; `scripts/run_trials.py`: 10 trials briefs, 0 problems; `evals/RESULTS.md`: facts eval 10/10, gate 28/30; sponsor sample still to write up |
| Unique dataset or problem | done | joined trials + 8-K + publications snapshot (`data/autopsy.duckdb`); sign-up sheet entry |
| Data the model doesn't know | in progress | `baseline/` vs `runs/` in README: for NCT04903327 the no-tools model gives the wrong registry reason ("Sponsor decision") and blames a bankruptcy that came after the trial ended; for vTv it says the registry gave COVID-19 as the reason (it says "for business reasons") and that the two stories match (they don't); sponsor sample still to write up |
| Admits what the data can't answer | done | "What the data can't tell us" in every report (`ghost/report.py`); `tests/test_cant_answer.py` |
| 3+ agent shapes | done | lead, researcher (3 lane configs), writer, checker in `ghost/pipeline.py` |
| Parallel fan-out in fresh contexts | done | `tests/test_parallel.py`; timing bars in the trace panel |
| Lead goes back for more, with a cap | done | `tests/test_gap_loop.py`; round count in the trace |
| Vague input asks for clarification | done | `tests/test_clarify.py`; README example |
| Accurately cited | done | `check_citations` in every trace (`citations_checked: n, removed: k`); `tests/test_citations.py`; planted errors: 10/10 caught, 0/10 false positives (`evals/RESULTS.md`) |
| Frontend changed from starter | done | `index.html` |
| Agent does something interesting | done | registry vs. investor vs. publication discrepancy finder: `discrepancies` table (43 trials labelled, 7 hand-checked), vTv sample in README |
| One data source per team member | done | 3 lanes, 6 sources; owners in README |
