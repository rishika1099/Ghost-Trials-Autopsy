# Ghost Trials Autopsy: Proposal and Team Plan

Due **Wed Nov 11, 11:59pm**. Team: Rishika (rishika1099), Shreya (shreyashetty2), Kshamaa (KshamaaS). Path: Deep Research.

## Problem
- Drug companies stop clinical trials early all the time. Patients took risks in those trials, but the results are often never posted or published, so other researchers can't learn from the failure.
- The reason a sponsor gives the public registry ("business decision") may not match what it tells investors in an SEC 8-K ("did not meet the primary endpoint").
- Checking this today means reading ClinicalTrials.gov, EDGAR and PubMed by hand, one trial at a time. Health reporters, patient advocates and research-integrity people don't have time to do that for a whole sponsor.

## How it works
- The user names a drug, sponsor, condition or NCT ID. A vague question ("Why do trials fail?") gets a clarifying question with concrete options instead of research.
- The **Lead** plans and sends briefs to three **Researchers** at once, each in a fresh context: trials (registry and FDA), disclosures (SEC filings) and publications (PubMed and Europe PMC).
- The Lead reads their findings, lists gaps ("sponsor matched to a CIK but no 8-K in the window") and sends researchers back for just those, up to 3 rounds and a 240 s budget.
- The **Writer** reports using only stored evidence: answer, timeline, evidence, where the stories differ, and what the data can't tell us. The **Citation Checker** then checks every cited sentence against its record and fixes or removes what isn't supported.
- Underneath is an offline snapshot nobody else has: 16,473 industry phase 2 and 3 trials (2015 to 2023) joined to sponsor 8-K filings and PubMed articles.

## Features
| Feature | Status |
|---|---|
| Snapshot: trials, derived results timing, stop-reason categories, publications | done (16,473 trials, 25,615 publication links) |
| Snapshot: sponsor to SEC CIK, 8-K filings near each stop | built, empty until `SEC_USER_AGENT` is set (#3) |
| Lead: clarify / refuse / research gate, plan, gap review, round cap, time budget | done, tuning on real runs (#5) |
| Researchers in parallel, fresh contexts, three lane configs | done |
| Writer with evidence-id citations, numbered by code | done, tuning (#6) |
| Citation Checker (evidence-id check, then a model check) | done, tuning (#11) |
| Discrepancy finder: registry reason vs. 8-K language | to do (#11) |
| `/chat` in the Project 1 shape, with an `agent` field on every tool call | done |
| Frontend: live trace with parallel timing bars, trial timeline, clickable citations, "can't tell us" box | first pass done (#6) |
| Offline tests (`uv run pytest`) and live tests (`LIVE=1`) | done |
| Inspect evals: the Lead's gate, and full runs against gold SQL answers | built, not run yet (#10) |
| Deploy to Cloud Run on Kshamaa's GCP project | to do (#8) |
| README with sample queries and no-tools baselines | in progress (#7) |

## Who owns what
Everyone owns **one data lane** (the course asks for one data source per team member), **one agent shape**, and **one piece that ties the project together**.

### Rishika: trials + the Lead
- **Data lane A:** ClinicalTrials.gov and Drugs@FDA (`get_trial_live`, `get_fda_approvals`, `query_trials_sql`; `prompts/lane_trials.md`). Verify the snapshot against the live registry (`scripts/verify_trials.py`) and the stop-reason labels (#2).
- **Agent shape:** the Lead: clarify gate, parallel fan-out, gap loop (`ghost/pipeline.py`, `prompts/lead.md`, `prompts/lead_review.md`). Tune it on real runs (#5).
- **Ties it together:** the sample runs in `runs/` and the final submission (#9).

### Shreya: disclosures + the Citation Checker
- **Data lane B:** SEC EDGAR (`find_sponsor_cik`, `search_sec_filings`, `get_filing_excerpt`; `prompts/lane_disclosures.md`). Build the `sponsor_cik` and `filings` tables and check the matches (#3).
- **Agent shape:** the Citation Checker (`check_citations`, `prompts/checker.md`). Measure it with planted errors (#11).
- **Ties it together:** the discrepancy finder, the project's headline feature (#11), and the Inspect evals (#10).

### Kshamaa: publications + the Writer + GCP
- **Data lane C:** PubMed and Europe PMC (`find_publications`, `get_abstract`; `prompts/lane_publications.md`). Check the publication links by type (#4).
- **Agent shape:** the Writer (`prompts/writer.md`, `ghost/report.py`) and the page that shows its report: timeline, citations, phone width (#6).
- **Ties it together:** GCP on her course credits: team access, then the Cloud Run deploy (#8).

### Everyone
- Set up and run locally (#1).
- README (#7): each person writes up the sample query closest to their lane, with the hand-checked answer, the source, and the no-tools baseline next to the agent's answer.

## Timeline
| Dates | Goal |
|---|---|
| Nov 4 to 5 | Everyone runs it locally. Kshamaa shares the GCP project ID and grants Vertex AI User. |
| Nov 6 to 7 | Lanes verified; SEC tables built; each lane's prompt tuned. Branch per feature, merged by PR. |
| Nov 8 | Deployed on Cloud Run. Lead, Writer and Checker tuned on real runs. |
| Nov 9 | Discrepancy finder, frontend polish, evals. |
| Nov 10 | Feature freeze. README sample queries tested on the deployed URL. |
| Nov 11 | Submit the repo URL on Courseworks (one person). |

## How we work
- `main` auto-deploys to Cloud Run once #8 is done, so keep it working: branch per feature (`shreya/sec-filings`), open a PR, get one teammate to look.
- Gemini calls bill the project in `VERTEX_PROJECT` (Kshamaa's). Set it in `.env` once she shares it.
- Tools follow the pattern in `ghost/tools.py`: return JSON; every record has a `source_url` and an `evidence_id`, and goes in the evidence store. Errors are JSON that tell the model what to do next.
- Never make up data, dates or citations. If a tool returns nothing, the report says so. No em dashes anywhere (see `CLAUDE.md`).
- Run `uv run pytest` before every push.
