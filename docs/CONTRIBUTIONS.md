# Team and Contributions

Each team member owned a research data lane. The table also credits the agents, interface, evaluation and deployment work across those lanes.

| Member | UNI | Data lane | Agents | Cross-cutting work |
|---|---|---|---|---|
| Rishika Mamidibathula | rm4318 | A: ClinicalTrials.gov and openFDA Drugs@FDA | Lead, Skeptic, Ledger Analyst | Frontend and Explore views, testing, Cloud Build configuration, sample runs, evaluation reruns, submission |
| Shreya | svs2148 | B: SEC EDGAR | Citation Checker | Discrepancy finder, evaluation datasets and scoring |
| Kshamaa | ks4423 | C: PubMed and Europe PMC | Writer | Google Cloud deployment |

## Problem

Drug companies stop clinical trials early all the time. Patients took risks in those trials, but the results
are often never posted or published, so other researchers cannot learn from the failure. The reason a sponsor
gives the public registry ("business decision") may also differ from what it tells investors in an SEC 8-K
("did not meet the primary endpoint"). Checking this today means reading ClinicalTrials.gov, EDGAR and PubMed
by hand, one trial at a time, which health reporters, patient advocates and research-integrity staff rarely
have time to do for a whole sponsor.

## Approach

- The user names a drug, sponsor, condition or NCT ID. A vague question gets clarifying options instead of research.
- The **Lead** plans and sends briefs to three **Researchers** at once, each in a fresh context: trials,
  disclosures and publications. It reviews their findings for gaps and sends researchers back for just those,
  up to 3 rounds and a 240 s budget.
- The **Writer** reports from stored evidence only. The **Citation Checker** verifies every cited sentence
  against its record and fixes or removes what is not supported. The **Skeptic** then reads the checked report
  like an editor: how strong the finding is, what else could explain it, and what to ask the sponsor.
- The **ghost ledger** gives instant, model-free views of the whole snapshot, and a **Ledger Analyst** agent
  answers whole-snapshot questions in SQL.
- Underneath is an offline snapshot built for this project: 16,473 industry phase 2 and 3 trials (2015 to
  2023) joined to 2,053 sponsor 8-K filings and 25,615 publication links.

## Rishika: trials, research agents and the frontend

**Data lane A** (`get_trial_live`, `get_fda_approvals`, `query_trials_sql`, `get_snapshot_stats`; `prompts/lane_trials.md`)

- Verified the snapshot against the live registry on 70 random stopped trials, with 0 mismatches (`scripts/verify_trials.py`).
- Hardened the stop-reason classifier against phrases that only look like reasons, such as "not due to safety"
  and "Data Safety Monitoring Board" (`ghost/classify.py`, `tests/test_classify.py`).
- Made `get_fda_approvals` find withdrawn drugs and biologics (for example Aduhelm and Leqembi).
- Made empty searches return a citable "nothing found" record, so the model never invents an id.
- Ran the trials researcher on 10 briefs covering every stop reason, status and an out-of-scope trial, with
  0 problems (`scripts/run_trials.py`, `runs/trials_*.json`). The runs led to four fixes: withdrawn and
  zero-enrollment trials get no results due date, researchers cannot cite ids no tool returned, month-only
  registry dates stay month-only, and list questions are answered with SQL.

**The Lead** (`ghost/pipeline.py`, `prompts/lead.md`, `prompts/lead_review.md`)

- Built the clarify, refuse or research gate, the planning step, the structured gap review, the round cap and the time budget.
- Tuned the gate and gap review on real runs. The Sorrento and Entero samples each run three research rounds.
- Gate eval: 28 of 30 correct (`evals/RESULTS.md`).

**Skeptic and Ledger Analyst**

- Built the Skeptic to review the checked report for evidence strength, alternative explanations and follow-up questions.
- Built the Ledger Analyst to answer questions about the full snapshot using SQL. Added prompts and tests for both agents. [Agent implementation](https://github.com/rishika1099/Ghost-Trials-Autopsy/commit/c0b9a35)

**Testing and deployment**

- Expanded coverage for edge cases and individual research steps, reran the evaluations and verified the deployed service.
- Authored the Cloud Build configuration used by the deployment trigger. [Build configuration](https://github.com/rishika1099/Ghost-Trials-Autopsy/commit/ed7e30b)

**Frontend** (`index.html`)

- Built the Explore section with the ghost ledger, sponsor report cards, discrepancy browsing and shareable cases. [Explore implementation](https://github.com/rishika1099/Ghost-Trials-Autopsy/commit/c1ecd18)

- Designed the hand-drawn lab notebook interface: live agent trace with parallel timing bars, trial timelines,
  clickable citations, the "What the data can't tell us" box, light and dark themes, and a phone-width layout. [Frontend redesign](https://github.com/rishika1099/Ghost-Trials-Autopsy/pull/13)

## Shreya: disclosures lane, the Citation Checker and the discrepancy finder

**Data lane B** (`find_sponsor_cik`, `get_trial_filings`, `search_sec_filings`, `get_filing_excerpt`; `prompts/lane_disclosures.md`)

- Matched 591 sponsors to SEC CIKs by normalized and fuzzy name matching, threshold 92 (`ghost/names.py`),
  and collected 2,053 8-K filings within 120 days of a stopped trial. 770 stopped trials have at least one.
- Spot-checked 20 sponsor matches and 10 filing rows for the right company, trial and snippet.
- The disclosures researcher quoted 8-K language word for word in 6 of 6 quotes on the sample queries (`scripts/run_disclosures.py`).
- The SEC contact string is read from `SEC_USER_AGENT`, kept in Secret Manager on Cloud Run, and never committed.

**The Citation Checker** (`check_citations` in `ghost/pipeline.py`, `ghost/citecheck.py`, `prompts/checker.md`)

- Deterministic rules (evidence id exists; dates, numbers and quotes appear in the cited record; no
  accusatory words) run first, then a model check.
- On 10 planted errors against real records, rules alone caught 9 and rules plus the model caught 10, with
  0 of 10 correct controls changed (`evals/planted_claims.py`).

**Evaluation**

- Prepared the 30 gate questions and 30 snapshot questions with SQL targets, ran the planted-error checks and recorded the scores in [the evaluation results](../evals/RESULTS.md).

**The discrepancy finder**

- Added the "Stories differ" example to the frontend.

- Built the `discrepancies` table: 43 stopped trials whose 8-K points a different way than the registry, 5 of them checked by hand.
- Chose and verified the README's discrepancy sample, vTv NCT03980730: the registry says "business reasons", the 8-K says the trial "did not meet its primary objective".

## Kshamaa: publications lane, the Writer and deployment

**Data lane C** (`find_publications`, `get_abstract`; `prompts/lane_publications.md`)

- Spot-checked 20 links per link type and found that Europe PMC mentions are almost never the trial's results
  (1 of 20). Only formal registry and PubMed links published after the trial started now count as a possible
  results paper, which changed the share of stopped trials with a publication from 81.8% to 21.4%
  (`docs/DESIGN_NOTES.md`).
- Added a live PubMed and Europe PMC fallback for trials with no snapshot links, checked on 5 such trials
  (`scripts/check_publications_live.py`, `runs/publications_live_check.json`).
- The publications researcher states plainly when no results paper was found, with 0 problems on the samples (`scripts/run_publications.py`).

**The Writer** (`prompts/writer.md`, `ghost/report.py`)

- Reviewed real reports for a direct answer, one fact per evidence claim, and limits specific to the question, then fixed six problems the review found (`docs/DESIGN_NOTES.md`).
- All 44 timeline events across the sample reports match the snapshot.

**Google Cloud deployment**

- Hosted the project on her course credits (`ieor-agentic-ai-292704`) and granted Vertex AI access to the team.
- Set up continuous deploy: the Cloud Build trigger `deploy-on-main` runs `cloudbuild.yaml` on every push to `main`.
- Cloud Run settings: 600 s request timeout, 2 GiB memory, one minimum instance during grading, and the SEC
  contact string from Secret Manager.

## Verification before submission

- Offline and live test suites: all tests passed except 1 skipped (a live SEC test that needs a local contact string).
- `tests/test_deploy.sh` against the live service: pass, with the Sorrento sample answered in 111 s.
- All six sample queries sent to the live service at once: each answered in 70 to 177 s, in the Project 1
  response shape, with an `agent` on every tool call (`runs/deployed_samples_check.json`).

## Running the project

```bash
brew install uv
gcloud auth application-default login
cp .env.example .env   # set VERTEX_PROJECT and SEC_USER_AGENT
uv run app.py          # then open http://localhost:8000
uv run pytest
```

The snapshot (`data/autopsy.duckdb`) is in the repository, so it does not need to be rebuilt to run the app.
