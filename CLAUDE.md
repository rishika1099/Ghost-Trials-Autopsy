# CLAUDE.md: Ghost Trials Autopsy

Project 2 (Data Exploration Agent), **Deep Research path**. Team of 3. Goal: full marks on every rubric line.
Read this whole file before writing code. When a choice is unclear, pick the option that makes a rubric item easier for a grader to verify.

## 1. What we are building

**Ghost Trials Autopsy** is a deep research agent that investigates clinical trials that stopped early.
For a drug, sponsor, condition or trial ID, it answers:

1. **Why did the trial stop?** (registry status and stated reason)
2. **Were the results ever reported?** (results posted on ClinicalTrials.gov, journal publication, how late)
3. **What did the sponsor tell investors?** (SEC 8-K and other filings near the stop date)
4. **Do those stories match?** (registry reason vs. investor language vs. publication record)

**Who it's for:** health reporters, patient advocates, and research-integrity people. Example: a reporter covering a mid-size biotech asks "Did this company stop any trials without reporting results, and what did it tell investors?"

**Why it matters:** patients took risks in trials whose results were never shared, other researchers can't learn from those failures, and the reason given to investors may not match the registry.

## 2. Hard requirements (from the assignment)

Every item here must be true at submission. Section 12 is the final checklist.

- Uses data the model does not already know deeply, and gets it through **tools** (APIs, files, SQL).
- Combines evidence into a **supported claim**.
- Says clearly when **the data cannot answer** a question.
- **Shows its work:** keep the **/chat response shape from Project 1 exactly.** Sub-agent tool calls also go in `tool_calls`, each with an `agent` field.
- Has a **frontend** that says what the agent explores, who it is for, and how to use it. It must look clearly different from the starter.
- Is **deployed to GCP Cloud Run** with **continuous deploy from GitHub.**
- **Team of 3 means at least 3 data sources.** We use 4 core sources (Section 4).

Deep Research path items:
- At least **three agent shapes with different jobs** (we have Lead, Researcher, Writer, plus a Citation Checker).
- The **Lead fans out to several Researchers in one turn.** They run **in parallel, in fresh contexts.**
- The **Lead goes back for more** when findings leave a gap, **up to a turn cap.**
- **Vague questions trigger clarification** instead of research.
- **The output is accurately cited.**

## 3. Start from the starter

1. Unzip `wikipedia-deep-research.zip` into the repo and read all of it before changing anything. Keep its LLM client, agent loop style, and env var conventions.
2. Open our Project 1 repo (or its README) and copy the exact `/chat` request and response schema. **Do not invent a new shape.** If the Project 1 shape has no `agent` field on tool calls, add `agent` as an extra key on each tool call and change nothing else.
3. Replace the Wikipedia tools with the tools in Section 5. Replace the Wikipedia prompts with the prompts in Section 6.
4. If any part of the starter conflicts with this file, follow this file for rubric items and the starter for everything else. Note each conflict in `NOTES.md`.

## 4. Data sources (one lane per team member)

| Lane | Owner | Source | Access | Used for |
|---|---|---|---|---|
| A: Trials | Rishika (rm4318) | ClinicalTrials.gov API v2 `https://clinicaltrials.gov/api/v2/studies` | no key | status, `whyStopped`, phase, sponsor, dates, `hasResults`, enrollment |
| A: Trials | Rishika (rm4318) | openFDA Drugs@FDA `https://api.fda.gov/drug/drugsfda.json` | no key for light use | was the drug ever approved, and when |
| B: Money | Shreya (svs2148) | SEC EDGAR full-text search `https://efts.sec.gov/LATEST/search-index` and filings archive | no key; **User-Agent header required** | 8-K and 10-K language about the trial |
| B: Money | Shreya (svs2148) | SEC `https://www.sec.gov/files/company_tickers.json` | no key | map sponsor name to CIK |
| C: Science | Kshamaa (ks4423) | PubMed E-utilities `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/` | no key (optional key raises limit) | publications linked to an NCT ID |
| C: Science | Kshamaa (ks4423) | Europe PMC REST `https://www.ebi.ac.uk/europepmc/webservices/rest/search` | no key | fallback publication search |

Optional extra lanes, only after everything else passes: Retraction Watch data via Crossref, CMS Open Payments. Do not let them block anything.

Rules:
- SEC: set `User-Agent` from env var `SEC_USER_AGENT` (a team or course contact string). Never hardcode a personal email. Stay under 10 requests per second.
- NCBI: stay under 3 requests per second without a key.
- Every HTTP call has a timeout (10 to 20 s), retries with backoff (max 3), and a cache (Section 4.1).

### 4.1 Offline build step (ships with the deploy)

Graders wait up to 5 minutes, and live APIs can be slow or down. So we build a **snapshot** offline, ship it with the image, and use live APIs only to add detail.

`scripts/build_snapshot.py` creates `data/autopsy.duckdb` (or Parquet files) with:

- **`trials`**: interventional, industry-sponsored, phase 2 or 3 trials with primary completion from 2015-01-01 to 2023-12-31, all statuses (`TERMINATED`, `WITHDRAWN`, `SUSPENDED`, `COMPLETED`) so we can compare. Columns: `nct_id, title, sponsor, sponsor_class, phase, conditions, interventions, overall_status, why_stopped, start_date, primary_completion_date, completion_date, enrollment, has_results, results_first_post_date, last_update_date`.
- **`trial_derived`**: `results_due_date` (primary completion + 365 days), `results_posted` (bool), `days_late` (or null), `stopped` (bool), `why_stopped_category` (`safety`, `efficacy`, `business/strategic`, `enrollment`, `other`, `blank`), classified by keyword rules first, then an LLM pass, with the method stored in a column.
- **`sponsor_cik`**: sponsor name to SEC CIK via normalized and fuzzy matching. Keep a `match_score` column and drop matches under the threshold. Private sponsors simply have no row.
- **`filings`**: for matched sponsors, 8-K filings within ±120 days of each stopped trial's last update or completion date that mention the drug name, the NCT ID, or the condition. Store `cik, accession, form, filed_date, url, snippet`.
- **`publications`**: PMIDs linked to each NCT ID (PubMed query `NCT01234567[si]`, then Europe PMC as fallback). Store `nct_id, pmid, title, journal, pub_date, url`.
- **`snapshot_meta`**: build date and row counts per table. The frontend and the Writer show the snapshot date.

This joined, derived dataset is what makes us unique. No one else has trials linked to investor filings and publication status.
Size rule: commit the data if every file is under 100 MB. Otherwise upload it to a GCS bucket and load it at startup (`DATA_GCS_URI` env var).
Document how to rebuild it in the README (`uv run python scripts/build_snapshot.py`).

## 5. Tools

Each tool returns structured JSON, and every record includes a `source_url` and a stable `evidence_id` (for example `ctgov:NCT01234567`, `sec:0001193125-21-123456`, `pubmed:34567890`, `fda:NDA021234`).

Lane A (Trials Researcher):
- `query_trials_sql(sql)`: read-only SQL over the snapshot (`SELECT` only; reject anything else; enforce `LIMIT`).
- `get_trial_live(nct_id)`: live ClinicalTrials.gov record, to confirm or refresh the snapshot.
- `get_fda_approvals(drug_name)`: Drugs@FDA lookup.

Lane B (Disclosures Researcher):
- `find_sponsor_cik(sponsor_name)`
- `search_sec_filings(query, cik=None, start_date=None, end_date=None, forms=["8-K"])`
- `get_filing_excerpt(url, keywords)`: returns only the paragraphs that match.

Lane C (Publications Researcher):
- `find_publications(nct_id)`: snapshot first, then a live PubMed or Europe PMC fallback.
- `get_abstract(pmid)`

Shared:
- `get_snapshot_stats()`: counts and base rates (for example, the share of stopped trials with a blank reason), so claims can be put in context.

## 6. Agents

Use **four agent shapes**. Each has its own system prompt file in `prompts/`.

### 6.1 Lead (`prompts/lead.md`)
1. **Clarify gate.** Before any research, decide if the question is specific enough. It is **vague** if it lacks a concrete target (drug, sponsor, NCT ID or condition) **and** a scope (phase, time window, or which question 1 to 4). If vague, **return a clarification and do not research.** Give 2 to 4 concrete options. Example: user asks "Why do Alzheimer's trials fail?" Lead replies with options such as "Industry phase 2 and 3 Alzheimer's trials that stopped from 2015 to 2023, by stated reason", "One sponsor (which?)", or "One drug (which?)".
2. **Plan.** Write a short research plan, then call `dispatch_researchers` **once** with a list of briefs, one per lane that is relevant (usually all three).
3. **Review.** Read the findings. List gaps as structured JSON (for example, "sponsor matched to CIK but no 8-K found in the window, widen to 10-Q", or "trial has results but no PMID, try Europe PMC with drug name").
4. **Go back for more.** If gaps exist and `round < MAX_RESEARCH_ROUNDS` (default 3), dispatch only the researchers needed for those gaps. Otherwise stop.
5. Hand the evidence store to the Writer.

### 6.2 Researchers (one shape, three lane configs) (`prompts/researcher.md`)
- Each Researcher starts in a **fresh context**: a new message list with only its system prompt and its brief. It never sees the Lead's conversation or other Researchers.
- It runs its own tool loop with `max_turns` (default 8).
- It returns structured findings: `[{claim, evidence_ids, confidence, notes}]` plus `gaps`.
- **Parallelism:** `dispatch_researchers` runs all briefs with `asyncio.gather` (or the starter's equivalent). Log start and end timestamps for each Researcher so the trace proves they overlapped.

### 6.3 Writer (`prompts/writer.md`)
Writes the final report using **only** evidence in the evidence store. Required sections:
1. **Answer** (2 to 4 sentences, the direct claim)
2. **Timeline** (start, stop, results due, results posted or never, 8-K date, publication date), as JSON for the frontend plus a short text version
3. **Evidence** (claims with inline citations `[1]`, `[2]`)
4. **Where the stories differ** (registry reason vs. investor language vs. publications), when relevant
5. **What the data can't tell us** (always present, specific to this question)
6. **Sources** (numbered list: title, source type, URL)

### 6.4 Citation Checker (`prompts/checker.md`)
Runs after the Writer. For each citation, it checks that the `evidence_id` exists in the store and that the cited fact (date, status, number, quote) matches the stored record. Unsupported sentences are fixed or removed, and the result is reported in the trace as `citations_checked: n, removed: k`. This is the "accurately cited" proof.

### 6.5 Limits
- Lead: max 3 research rounds. Each Researcher: max 8 turns. Writer and Checker: max 4 turns each.
- Whole request: hard wall clock budget of 240 s (`REQUEST_BUDGET_S`). When near the budget, skip further rounds and write with what we have, saying so in the report.

## 7. What the agent must refuse or qualify

The Writer and Lead must say plainly when the data can't answer. Cover at least these:
- **The real reason a trial failed** beyond the stated `whyStopped` text. We only know what was reported.
- **Intent or deception.** A mismatch between the registry and an 8-K is a discrepancy, not proof of hiding anything.
- **Legal violations.** Our `results_due_date` is an approximation. Which trials legally must post results (FDAAA "applicable clinical trial" status) is not fully public, so never say a sponsor broke the law.
- **Results published elsewhere** (conference abstracts, non-indexed journals, company websites) may be missed.
- **Private sponsors** have no SEC filings.
- **Trials outside the snapshot window or scope** get a live lookup or an explicit "outside our data" note.
- **Medical advice.** Never say whether a patient should take a drug.

If a question is entirely out of scope (for example, "Is drug X safe for me?"), answer with a short refusal that explains what the tool can do instead. Use the same response shape.

## 8. /chat API

- Keep the Project 1 request and response schema **exactly.** Every tool call from every agent goes in `tool_calls` with an `agent` field: `"lead"`, `"researcher:trials"`, `"researcher:disclosures"`, `"researcher:publications"`, `"writer"`, or `"checker"`.
- Include each tool call's arguments and a short result summary (not the full payload) so the response stays small.
- A clarification response uses the same shape, with the clarification as the answer and no researcher calls.
- Also add `GET /health` (returns 200 and the snapshot date). Adding a streaming endpoint for the frontend is fine as long as `/chat` is unchanged.

## 9. Frontend (creativity points)

Replace the starter UI completely. Keep it a single page served by `app.py`.

- **Header block:** what it explores, who it is for, how to use it, the snapshot date, and the data sources with links.
- **Example query chips:** the 3 README sample queries plus 1 vague question that shows clarification.
- **Live agent trace panel:** shows the Lead, each Researcher (with parallel timing bars), the Writer and the Checker, plus each tool call grouped by `agent`.
- **Trial timeline visual:** a horizontal timeline per trial with start, stop, results due, results posted (or a red "never posted" marker), 8-K date and publication date. Use plain SVG or a small charting library pinned to an exact version from a CDN.
- **Citations:** clicking `[n]` highlights the source and opens its URL.
- **"What the data can't tell us" box,** styled to stand out.
- Works on a phone-width screen. No horizontal scroll.

## 10. README.md (must include all of this)

1. **Project description and target user** (Section 1, in plain language).
2. **Data:** each source, its URL, what we pull, and the snapshot scope and date. How to rebuild (`scripts/build_snapshot.py`) and where the data lives (repo or GCS URI).
3. **Architecture:** a diagram of Lead, parallel Researchers, Writer and Checker, the round cap and turn caps, and how clarification works.
4. **Three sample queries for graders.** For each:
   - the query text
   - the **expected answer** (short, specific, checked by hand against the data)
   - the **source**: exact endpoint, table, or file (for example `clinicaltrials.gov/api/v2/studies/NCT0xxxxxxx`, table `trial_derived`, EDGAR accession number)
   - **the same model with no tools and no system prompt**, answer pasted verbatim
   - **our agent's answer**, pasted verbatim
   Pick queries about **mid-size sponsors and phase 2 trials**, where the no-tools model can't know the answer. Avoid famous failures it has memorized. Make one of them a discrepancy case (registry reason differs from 8-K language) and one a "never posted results" case.
5. **One vague-question example** showing the clarification response.
6. **One "can't answer" example** showing the refusal or qualification.
7. **Deployed URL** and how to call `/chat` with curl.
8. **Team and lanes:** who owns which data source.
9. **Limitations** (Section 7, in plain words).

`scripts/baseline.py` produces the no-tools answers: the same model ID as the agent, no tools, no system prompt, just the user query. Save outputs to `baseline/` and paste them into the README.

## 11. Repo, submission and deploy

**Repo root must contain:** `app.py`, `pyproject.toml`, `uv.lock`, `README.md`, `submission.json`.

`submission.json`:
```json
{
  "deploy_url": "https://<service>-<hash>.run.app",
  "authors": ["rm4318", "svs2148", "ks4423"],
  "path": "research"
}
```
Ask the team for their UNIs. Do not leave placeholders at submission.

**Collaborators** (if the repo is private): add `codeboi07`, `bhuvighosh3`, `nniishhh`, `x` under Settings > Collaborators.

**Cloud Run:**
- Continuous deploy from GitHub (Cloud Build trigger on push to `main`), following the course guide "Deploying to Cloud Run from GitHub".
- Dockerfile using `uv sync --frozen`, listening on `$PORT`.
- **Request timeout: 600 s** (graders wait up to 5 min; our own budget is 240 s).
- Memory 1 to 2 GiB. `min-instances=1` during grading so there are no cold starts.
- Secrets (LLM API key, `SEC_USER_AGENT`) in Secret Manager, never in the repo.
- Keep the service running until grades are released.

## 12. Tests and final rubric checklist

Write `tests/` with pytest. All tests must pass before submission:
- `test_shape.py`: `/chat` response matches the Project 1 schema; every tool call has an `agent` field.
- `test_parallel.py`: researcher start and end times overlap (proves parallel), and each researcher's first message list contains only its own system prompt and brief (proves fresh context).
- `test_gap_loop.py`: with a stubbed gap, the Lead runs a second round and stops at `MAX_RESEARCH_ROUNDS`.
- `test_clarify.py`: "Why do trials fail?" returns a clarification and makes no researcher calls.
- `test_citations.py`: every `[n]` in the report maps to a source, and every source's `evidence_id` exists in the evidence store.
- `test_cant_answer.py`: "Did sponsor X break the law?" returns a qualified answer with the limitations section.
- `test_deploy.sh`: curl the deployed `/health` and one sample query; fail if it takes over 300 s.

Final checklist (tick each one with evidence in `NOTES.md`):

| Rubric | Points | Evidence |
|---|---|---|
| README and valid `submission.json` | 1 | files at root, `path: "research"`, all UNIs, live `deploy_url` |
| Deployed and reachable | 9 | `/health` 200 from the public URL; sample queries finish under 5 min |
| Clear purpose | | frontend header and README intro |
| Answers its research questions correctly | | 3 sample queries checked by hand against the data |
| Unique dataset or problem | 4 | joined trials + 8-K + publications snapshot; question claimed on the sign-up sheet |
| Data the model doesn't know | | README no-tools vs. agent comparison |
| Admits what the data can't answer | | "can't tell us" section in every report; README example |
| 3+ agent shapes | 7 | Lead, Researcher, Writer, Checker |
| Parallel fan-out in fresh contexts | | `test_parallel.py`; timing bars in the trace UI |
| Lead goes back for more, with a turn cap | | `test_gap_loop.py`; round count in the trace |
| Vague input asks for clarification | | `test_clarify.py`; README example |
| Accurately cited | | Checker results in the trace; `test_citations.py` |
| Frontend changed from starter | 4 | new UI with timeline and agent trace |
| Agent does something interesting | | registry vs. investor discrepancy finder |
| One data source per team member | | 4 core sources across 3 lanes, owners listed in README |

## 13. Working rules for Claude Code

- Build in this order: snapshot, tools, Researchers, Lead, Writer, Checker, `/chat`, frontend, tests, README, deploy. Commit after each step with a clear message.
- Run the agent on the 3 sample queries after every major change and keep the outputs in `runs/`.
- Never make up data, dates, or citations. If a tool returns nothing, the report says so.
- No em dashes anywhere in prompts, UI text, README or reports.
- Don't print long separator lines of repeated `-` or `=` in scripts or logs.
- Pin every dependency in `pyproject.toml` and commit `uv.lock`.
- Ask before deleting files or changing the `/chat` schema.
