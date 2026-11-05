# Ghost Trials Autopsy

A deep research agent that investigates industry clinical trials that stopped early. For a drug, sponsor, condition or trial ID (NCT number), it answers:

1. **Why did the trial stop?** (registry status and stated reason)
2. **Were the results ever reported?** (results on ClinicalTrials.gov, journal publications, how late)
3. **What did the sponsor tell investors?** (SEC 8-K and other filings near the stop date)
4. **Do those stories match?**

**Who it's for:** health reporters, patient advocates, and research-integrity people. Example: a reporter covering a mid-size biotech asks "Did this company stop any trials without reporting results, and what did it tell investors?"

IEOR 4570 Project 2, Deep Research path. Work in progress: who does what is in `PROPOSAL.md`, and the plan and rubric are in `CLAUDE.md`.

## Run it locally

```bash
gcloud auth application-default login
cp .env.example .env    # set SEC_USER_AGENT to a contact string with an email
uv run app.py           # http://localhost:8000
uv run pytest           # offline tests; LIVE=1 uv run pytest also calls Gemini
```

## How it works

```
question -> Lead (gate: clarify / refuse / research, then plan)
              |  dispatch_researchers: all briefs at once, asyncio.gather, fresh context each
              v
   researcher:trials   researcher:disclosures   researcher:publications
              |  Lead reviews findings for gaps; another round only for the lanes that need it
              v  (max 3 rounds, 8 turns per researcher, 240 s budget)
           Writer (cites evidence ids only) -> Citation Checker (fixes or removes unsupported claims)
```

It combines the three course starters: the deep research pattern from `wikipedia-deep-research`, the offline DuckDB build step and schema mappings from `subway-survey-text2sql-improved`, and the Inspect eval suite from `nyc-311-agent`. See `NOTES.md`.

## Data

`data/autopsy.duckdb` is a snapshot built by `uv run python scripts/build_snapshot.py`: 16,473 industry-sponsored, interventional, phase 2 or 3 trials with primary completion from 2015 to 2023, joined to SEC 8-K filings and PubMed articles. Live tools add detail at question time.

| Lane | Owner | Sources |
|---|---|---|
| A: Trials | Rishika (rm4318) | ClinicalTrials.gov API v2, openFDA Drugs@FDA |
| B: Disclosures | Shreya (svs2148) | SEC EDGAR full-text search, SEC company tickers |
| C: Publications | Kshamaa (ks4423) | PubMed E-utilities, Europe PMC |

## Sample queries

Each sample is in `samples.json`. `uv run python scripts/run_samples.py` reruns them into `runs/`, and `uv run python scripts/baseline.py` asks the same model (`vertex_ai/gemini-3.5-flash`) the same question with no tools and no system prompt, into `baseline/`.

### Never posted results: Sorrento COVI-MSC (NCT04903327)

**Query:** "Sorrento Therapeutics terminated its phase 2 COVI-MSC trial NCT04903327. Why did it stop, and were the results ever posted or published?"

**Expected answer (checked by hand against the live registry and the snapshot on 2026-11-05):**

- Terminated. The registry reason is "Due to considerably slow enrollment, unable to reach enrollment targets" (category `enrollment`). Not "sponsor decision", and not the bankruptcy, which came in February 2023, after the trial ended.
- Started 2021-11-16, primary completion 2022-08-29, completion 2022-11-23, 43 people enrolled.
- No results on ClinicalTrials.gov (`hasResults: false`). Our approximate due date is 2023-08-29 (primary completion + 365 days), 1,164 days past it on the snapshot date.
- No results paper. The five PubMed articles that name the NCT ID (PMIDs 34831101, 35321737, 35782071, 35897770, 38005826) are all reviews found through Europe PMC mentions.
- Sorrento (CIK 0000850261) 8-Ks filed 2023-02-22, 2023-03-20 and 2023-03-31 still list COVI-MSC among products it "is also developing", after the trial had ended. A discrepancy, not proof of intent: the text is boilerplate.

**Source:**

- `https://clinicaltrials.gov/api/v2/studies/NCT04903327` (status module and `hasResults`)
- tables `trials` and `trial_derived` (`results_due_date`, `days_late`, `why_stopped_category`), row `nct_id = 'NCT04903327'`
- table `publications`, `nct_id = 'NCT04903327'` (all 5 rows `link_type = 'europepmc_mention'`)
- table `filings`, EDGAR accessions 0001104659-23-023902, 0001104659-23-034065, 0001104659-23-039478

**What the no-tools model says is wrong:** it gives the registry reason as "Sponsor decision" (the registry says slow enrollment), blames the February 2023 bankruptcy for a trial that ended in November 2022, and says the trial aimed for "up to 60 patients" without a source.

<details>
<summary>Same model, no tools and no system prompt (<code>baseline/s2_never_posted.md</code>), verbatim</summary>

The Phase 2 clinical trial for Sorrento Therapeutics’ **COVI-MSC** (NCT04903327), which was designed to evaluate allogeneic adipose-derived mesenchymal stem cells for the treatment of COVID-19-induced Acute Respiratory Distress Syndrome (ARDS), was officially **terminated**. 

Here are the details regarding why the trial stopped and the status of its results:

### 1. Why did the trial stop?
The official reason listed on the ClinicalTrials.gov registry for the termination of NCT04903327 is **"Sponsor decision."** 

Behind this designation were two major contributing factors:
* **Financial Distress and Chapter 11 Bankruptcy:** In February 2023, Sorrento Therapeutics filed for Chapter 11 bankruptcy protection following a costly legal dispute and multi-million dollar arbitration loss to NantPharma (and billionaire Patrick Soon-Shiong). This financial crisis forced Sorrento to halt, suspend, or terminate the majority of its active and expensive clinical trials to preserve capital and restructure its assets. 
* **Recruitment and Evolving Pandemic Landscape:** Like many COVID-19 therapeutic trials initiated during the height of the pandemic, recruiting patients with severe COVID-19 ARDS became increasingly difficult as vaccination rates rose, milder variants (like Omicron) became dominant, and standard-of-care treatments improved. 

### 2. Were the results ever posted or published?
* **ClinicalTrials.gov:** No results have been posted to the NCT04903327 registry. Because the trial was terminated prematurely, the data set was incomplete and did not meet the requirements or threshold for official registry posting.
* **Peer-Reviewed Publications:** There are **no published peer-reviewed journal articles** containing Phase 2 data from this specific trial. 

#### *Note on Phase 1 Data:*
It is worth noting that Sorrento did previously publish and publicize positive results from its **Phase 1 trial** of COVI-MSC (NCT04488081). In that early, small-scale study, 10 out of 10 enrolled patients with severe COVID-19 ARDS survived and were discharged from the hospital after receiving COVI-MSC infusions. However, the larger Phase 2 trial (NCT04903327), which aimed to enroll up to 60 patients to rigorously prove efficacy against a placebo, was cut short before any definitive, publishable data could be generated.

</details>

<details>
<summary>Our agent (<code>runs/s2_never_posted_latest.md</code>, full trace in <code>runs/20261105-1206_s2_never_posted.json</code>), verbatim</summary>

## Answer
The clinical trial registry states that Sorrento Therapeutics terminated its Phase 2 COVI-MSC trial because slow enrollment prevented it from reaching its targets. [1] Clinical results have not been posted to ClinicalTrials.gov, even though they were due on August 29, 2023. [1] Furthermore, no primary results papers reporting clinical data for the 43 enrolled patients have been published in scientific literature. [2][3][4][5][6]

## Timeline
The trial started on November 16, 2021, and achieved primary completion on August 29, 2022, after enrolling 43 patients. The trial reached final completion on November 23, 2022, with results due by August 29, 2023, but no results have been posted to the registry or published in scientific literature.

## Evidence
- The Phase 2 trial of COVI-MSC (NCT04903327) was terminated after enrolling 43 patients. [1]
- The registry lists the reason for termination as being due to considerably slow enrollment and an inability to reach enrollment targets. [1]
- The trial started on November 16, 2021, and achieved primary completion on August 29, 2022. [1]
- No clinical results are posted on ClinicalTrials.gov for the trial. [1]
- No Drugs@FDA application was found for the COVI-MSC therapeutic. [7]
- Sorrento Therapeutics, Inc. is identified as the trial sponsor under SEC CIK 0000850261. [8]
- SEC 8-K filings from February and March 2023 list COVI-MSC as a product under development in standard pipeline and trademark tables. [9][10][11]
- Five identified scientific publications mention the trial, but all are review articles or text-mining references rather than primary results papers. [2][3][4][5][6]

## Where the stories differ
- The registry states that the trial was terminated in late 2022 due to slow enrollment, whereas Sorrento Therapeutics' SEC filings from February and March 2023 continued to list COVI-MSC as an active product under development in standard pipeline and trademark lists. [1][9][10][11]

## What the data can't tell us
- We cannot determine the real clinical or commercial reasons for terminating the study beyond the brief explanation provided in the registry.
- The discrepancy between the registry status and the investor pipeline lists is not proof of an intent to mislead.
- The calculated results due date of August 29, 2023, only approximates the federal deadline, which applies exclusively to applicable clinical trials, meaning the missing data is not proof that the sponsor broke the law.
- We cannot rule out that results were published in conference abstracts, non-indexed journals, or on company websites that were not captured in our search.
- Because of external API search limitations, we cannot tell if more detailed disclosures about the trial's cancellation were made in the company's full 10-K or 10-Q filings.

## Sources
1. Study of Intravenous COVI-MSC for Treatment of COVID-19-Induced Acute Respiratory Distress. ClinicalTrials.gov registry record. https://clinicaltrials.gov/study/NCT04903327
2. Molecular Mechanisms of Multi-Organ Failure in COVID-19 and Potential of Stem Cell Therapy.. PubMed article. https://pubmed.ncbi.nlm.nih.gov/34831101/
3. Mesenchymal stem/stromal cell therapy for COVID-19 pneumonia: potential mechanisms, current clinical evidence, and future perspectives.. PubMed article. https://pubmed.ncbi.nlm.nih.gov/35321737/
4. Association between Mesenchymal Stem Cells and COVID-19 Therapy: Systematic Review and Current Trends.. PubMed article. https://pubmed.ncbi.nlm.nih.gov/35782071/
5. Immunomodulation of Mesenchymal Stem Cells in Acute Lung Injury: From Preclinical Animal Models to Treatment of Severe COVID-19.. PubMed article. https://pubmed.ncbi.nlm.nih.gov/35897770/
6. Immune-Cell-Based Therapy for COVID-19: Current Status.. PubMed article. https://pubmed.ncbi.nlm.nih.gov/38005826/
7. Drugs@FDA search for COVI-MSC: no application. Drugs@FDA application. https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=BasicSearch.process&searchterm=COVI-MSC
8. Sorrento Therapeutics, Inc. (SEC CIK 0000850261). SEC company record. https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000850261
9. SEC 8-K 0001104659-23-023902. SEC EDGAR filing. https://www.sec.gov/Archives/edgar/data/850261/000110465923023902/tm237448d1_ex99-2.htm
10. SEC 8-K 0001104659-23-034065. SEC EDGAR filing. https://www.sec.gov/Archives/edgar/data/850261/000110465923034065/tm239933d1_ex99-1.htm
11. SEC 8-K 0001104659-23-039478. SEC EDGAR filing. https://www.sec.gov/Archives/edgar/data/850261/000110465923039478/tm2310928d1_ex99-1.htm

_Snapshot date: 2026-11-05. Research rounds: 2. citations_checked: 25, removed: 0._

_114 s, 31 tool calls_

</details>

## Asking the snapshot in SQL (Text2SQL)

The trials researcher answers list and count questions ("how many phase 2 Alzheimer's trials stopped, and why?") by writing SQL over the snapshot, using the Text2SQL starter's pattern:

1. **Schema with meaning.** `scripts/build_snapshot.py` writes `data/mappings.json`: every table and column with a plain description, and the exact allowed values of enum columns (`phase`, `overall_status`, `why_stopped_category`, ...). Descriptions carry the traps, for example that `results_due_date` is an approximation and is NULL for trials that never enrolled anyone.
2. **Tools.** `read_mappings` returns that schema, `get_enum_values(table, column)` the exact values, and `query_trials_sql(sql)` runs the query.
3. **Guardrails** (`ghost/db.py`): one statement only, `SELECT` or `WITH` only, write and admin keywords rejected (checked with string literals removed, so `'update'` inside a string is fine), `= 'NA'` rejected because missing values are NULL, a read-only DuckDB connection (the real boundary, since prompts can be talked around), and every query wrapped in a `LIMIT` (50 rows).
4. **Citable rows.** Every returned row with an `nct_id`, `accession` or `pmid` becomes evidence (`ctgov:NCT...`, `sec:...`, `pubmed:...`). An aggregate becomes `sql:<hash>`, stored with its query, so the Checker can see the exact SQL behind a number.

Example from `runs/trials_t08_condition.json`: asked how many industry phase 2 Alzheimer's trials stopped, the researcher wrote

```sql
SELECT d.why_stopped_category, count(*) AS n
FROM trials t JOIN trial_derived d USING (nct_id)
WHERE d.stopped AND t.phase = 'PHASE2' AND array_to_string(t.conditions, ' ') ILIKE '%alzheimer%'
  AND t.sponsor_class = 'INDUSTRY'
GROUP BY 1 ORDER BY n DESC
```

and answered 27 trials: 7 efficacy, 5 blank, 5 business/strategic, 4 enrollment, 3 safety, 3 other. The same counts come back when the query is run by hand. (Every trial in the snapshot is industry-sponsored, so the last filter changes nothing.)

`scripts/run_trials.py` runs the trials researcher alone on 10 briefs (safety, efficacy, enrollment, withdrawn, blank reason, suspended, sponsor list, condition counts, FDA approval, outside the snapshot) and checks each claim mechanically: every cited id exists, every date in a claim is in the cited record, every quote is in a cited record, and no withdrawn trial is called late. All 10 pass with 0 problems.

## Layout

| Path | What it is |
|---|---|
| `app.py` | FastAPI: `POST /chat` (Project 1 shape), `GET /run` (live stream for the page), `GET /health` |
| `index.html` | The frontend |
| `ghost/pipeline.py` | Lead, Researchers, Writer, Checker, and the round loop |
| `ghost/tools.py` | The agents' tools, one section per lane |
| `prompts/` | One system prompt per agent shape, plus one per lane |
| `scripts/build_snapshot.py` | Builds the snapshot and `data/mappings.json` |
| `scripts/baseline.py`, `scripts/run_samples.py` | No-tools baseline, and the agent on `samples.json` |
| `evals/` | Inspect evals: the Lead's gate, and full runs against gold SQL answers |
| `tests/` | pytest suite and `test_deploy.sh` |
