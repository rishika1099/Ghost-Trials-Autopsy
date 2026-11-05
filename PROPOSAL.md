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
| Snapshot: sponsor to SEC CIK, 8-K filings near each stop | built, empty until `SEC_USER_AGENT` is set |
| Lead: clarify / refuse / research gate, plan, gap review, round cap, time budget | done, tuning on real runs |
| Researchers in parallel, fresh contexts, three lane configs | done |
| Writer with evidence-id citations, numbered by code | done, tuning |
| Citation Checker (evidence-id check, then a model check) | done, tuning |
| Discrepancy finder: registry reason vs. 8-K language | to do |
| `/chat` in the Project 1 shape, with an `agent` field on every tool call | done |
| Frontend: live trace with parallel timing bars, trial timeline, clickable citations, "can't tell us" box | first pass done |
| Offline tests (`uv run pytest`) and live tests (`LIVE=1`) | done |
| Inspect evals: the Lead's gate, and full runs against gold SQL answers | built, not run yet |
| Deploy to Cloud Run on Kshamaa's GCP project | to do |
| README with sample queries and no-tools baselines | in progress |

## Who owns what
Everyone owns **one data lane** (the course asks for one data source per team member), **one agent shape**, and **one piece that ties the project together**. Work on a branch per task (`shreya/sec-filings`) and open a PR into `main`.

### Everyone: get set up first (by Nov 5)
- [ ] Install uv (`brew install uv`) and the gcloud CLI; `gcloud auth application-default login`
- [ ] Clone the repo, `cp .env.example .env`, `uv run app.py`, open http://localhost:8000
- [ ] Click the example chips: the vague one should ask a clarifying question; the others show the Lead, three Researchers with timing bars, the Writer and the Checker in the trace
- [ ] `uv run pytest` passes
- [ ] Read `CLAUDE.md` (plan and rubric) and `NOTES.md` (how the three starters were combined)
- [ ] Once Kshamaa shares the GCP project ID, set `VERTEX_PROJECT=<id>` in `.env`

The snapshot (`data/autopsy.duckdb`) is already in the repo, so you don't need to rebuild it to start.

### Rishika: trials + the Lead
**Data lane A: ClinicalTrials.gov and Drugs@FDA** (`get_trial_live`, `get_fda_approvals`, `query_trials_sql`; `prompts/lane_trials.md`)
- [x] Snapshot vs. live registry: 70 random stopped trials, 0 mismatches (`scripts/verify_trials.py`)
- [x] Stop-reason labels spot-checked; fixed negations ("not due to safety"), "before enrollment" and "administrative" (`tests/test_classify.py`)
- [x] `get_fda_approvals` finds withdrawn and biologic drugs (Aduhelm, Leqembi)
- [x] Empty searches return a citable "nothing found" record instead of the model inventing an id
- [ ] Trials researcher on 10 more briefs after the fixes

**Agent shape: the Lead** (`ghost/pipeline.py`, `prompts/lead.md`, `prompts/lead_review.md`)
- [x] `uv run python scripts/run_samples.py` on all 5 samples: each under 240 s, none crash (97 to 140 s; vague 8 s)
- [ ] `LIVE=1 uv run pytest` passes (clarify, refuse, can't-answer)
- [x] At least one run shows a second research round, for the README (the never-posted sample ran 2 rounds)
- [ ] Tune the gate and the gap review where real runs go wrong

**Ties it together:** the sample runs in `runs/` and the final submission (checklist below).

### Shreya: disclosures + the Citation Checker
**Data lane B: SEC EDGAR** (`find_sponsor_cik`, `search_sec_filings`, `get_filing_excerpt`; `prompts/lane_disclosures.md`). PR 14: 591 sponsors matched to a CIK, 2,053 `filings` rows, 770 stopped trials with an 8-K.
- [ ] Agree on a team contact string and put it in `.env` as `SEC_USER_AGENT="Ghost Trials Autopsy name@columbia.edu"` (never in the repo)
- [x] Rebuild: `uv run python scripts/build_snapshot.py` (other sources are cached, so only the SEC steps are new)
- [x] Check 20 sponsor matches (`ghost/names.py`, threshold 92) and 10 rows of `filings`: right company, right trial, relevant `snippet`
- [ ] Run the disclosures researcher on the three samples in `samples.json`; it should quote 8-K language exactly

**Agent shape: the Citation Checker** (`check_citations` in `ghost/pipeline.py`, `prompts/checker.md`)
- [ ] On 3 real reports, read what the Checker kept, fixed or removed. Does it catch a wrong date, a misquote, an overreaching word ("hid")?
- [x] 10 claims with planted errors against real records: how many does it catch? (9 of 10, no false positives)
- [x] Tune `prompts/checker.md`; `tests/test_citations.py` must still pass

**Ties it together: the discrepancy finder** (the headline feature)
- [x] Find stopped trials where `why_stopped_category` differs from what the 8-K `snippet` says; add a `discrepancies` table to `scripts/build_snapshot.py`
- [x] Pick the README's discrepancy sample from it and hand-check it: vTv NCT03980730 (Veru turned out to be consistent: its 8-Ks also give funding as the reason)
- [ ] Bonus: `uv run python evals/build_dataset.py`, then `uv run inspect eval evals/task.py@gate` and `@facts --limit 10`; scores in the README

### Kshamaa: publications + the Writer + GCP
**Data lane C: PubMed and Europe PMC** (`find_publications`, `get_abstract`; `prompts/lane_publications.md`)
- [ ] Spot-check 20 links per `link_type`. `europepmc_mention` is the weakest: e.g. the "never posted" sample NCT04903327 only has review articles that name the NCT ID, not a results paper
- [ ] Decide whether `europepmc_mention` counts as "published" in `get_snapshot_stats` and the Writer, and document it
- [ ] Check the live fallback in `find_publications` on 5 trials with nothing in the snapshot
- [ ] Run the publications researcher on the three samples; it should say "no results publication found" plainly

**Agent shape: the Writer** (`prompts/writer.md`, `ghost/report.py`) **and the page** (`index.html`)
- [ ] On 3 real reports: is the Answer direct, one fact per Evidence claim, "What the data can't tell us" specific (not boilerplate)?
- [ ] Timeline events right on the 3 samples (start, stop, results due, posted or never, 8-K, publication)
- [x] Phone width (375 px), light and dark mode, timeline labels don't overlap, `[n]` opens its source (PR 13)
- [x] Make it feel like ours (peer review scores originality): hand-drawn lab notebook design (PR 13)

**Ties it together: GCP on her course credits**
- [ ] Share the project ID; give Rishika and Shreya **Vertex AI User** (and **Cloud Run Developer** to whoever helps deploy)
- [ ] Cloud Run > Connect repository > Developer Connect > this repo, build with the `Dockerfile` (course guide "Deploying to Cloud Run from GitHub")
- [ ] Request timeout 600 s, memory 2 GiB, min instances 1 during grading; `SEC_USER_AGENT` in Secret Manager, `VERTEX_PROJECT` as an env var
- [ ] `/health` returns 200; `bash tests/test_deploy.sh <url>` passes; URL in `submission.json`

### Everyone: README and submission (Nov 10 to 11)
- [ ] README: each person writes up the sample query closest to their lane: query, hand-checked expected answer, exact source, the no-tools answer (`baseline/`) and our agent's answer (`runs/`) pasted verbatim
- [ ] README: one vague-question example, one "can't answer" example, architecture, deployed URL with a curl example, limitations
- [ ] Sample queries tested on the deployed URL, each under 5 minutes
- [ ] `uv run pytest`, `LIVE=1 uv run pytest`, `bash tests/test_deploy.sh` pass; no em dashes anywhere
- [ ] Every rubric row in `NOTES.md` ticked with evidence
- [ ] One person submits the repo URL on Courseworks by Nov 11, 11:59pm

## Timeline
| Dates | Goal |
|---|---|
| Nov 4 to 5 | Everyone runs it locally. Kshamaa shares the GCP project ID and grants Vertex AI User. |
| Nov 6 to 7 | Lanes verified; SEC tables built; each lane's prompt tuned. Branch per feature, merged by PR. |
| Nov 8 | Deployed on Cloud Run. Lead, Writer and Checker tuned on real runs. |
| Nov 9 | Discrepancy finder, frontend polish, evals. |
| Nov 10 | Feature freeze. README sample queries tested on the deployed URL. |
| Nov 11 | Submit the repo URL on Courseworks (one person). |
