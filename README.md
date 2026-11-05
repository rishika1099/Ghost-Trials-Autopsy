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

### Discrepancy: vTv Therapeutics Elevage (NCT03980730)

**Query:** "vTv Therapeutics terminated its phase 2 Elevage trial of azeliragon (NCT03980730). What reason did it give the registry, what did it tell investors, and do the two match?"

**Expected answer (checked by hand against the live registry, the snapshot and the 8-K text on 2026-11-05):**

- Terminated. The registry reason is "for business reasons" (category `business/strategic`).
- Started 2019-06-27, primary completion 2020-12-01, completion 2021-01-29, 43 people enrolled.
- Results were posted on ClinicalTrials.gov on 2022-01-21, 51 days after our approximate due date of 2021-12-01.
- vTv (CIK 0001641489) told investors in three 8-Ks near the stop:
  - 2020-11-05: "Following our decision to conclude enrollment in the Elevage Study at the end of September, we look forward to announcing topline results from this phase 2 study of azeliragon in December". No reason given.
  - 2020-11-24: topline results from the "ongoing Elevage Study" expected in December 2020. No reason given.
  - 2021-02-24: "On December 15, 2020, vTv announced that the phase 2 Elevage Study of azeliragon did not meet its primary objective." It also says vTv "has discontinued development of azeliragon for Alzheimer’s disease".
- **They do not match.** The registry gives a business reason; the 8-K that names the trial gives an efficacy result. That is a discrepancy between sources, not proof that anyone meant to mislead. It is one of 7 hand-checked rows in the `discrepancies` table (`decided_by = 'hand_checked'`, strength 9 of 10).
- No results paper: the 5 PubMed articles linked to the NCT ID are reviews from 2025 and 2026 found through Europe PMC mentions.

**Source:**

- `https://clinicaltrials.gov/api/v2/studies/NCT03980730` (status module, `whyStopped`, `hasResults`)
- tables `trials` and `trial_derived`, row `nct_id = 'NCT03980730'`
- table `sponsor_cik`, `sponsor = 'vTv Therapeutics'` (CIK 0001641489, `exact_core` match)
- table `filings` and table `discrepancies`, `nct_id = 'NCT03980730'`: EDGAR accessions 0001564590-20-051429, 0001564590-20-055077, 0001564590-21-008154
- 8-K exhibit: `https://www.sec.gov/Archives/edgar/data/1641489/000156459021008154/vtvt-ex991_6.htm`
- the disclosures researcher alone on this sample, with every quote checked word for word: `runs/disclosures_s1_discrepancy.json` (`uv run python scripts/run_disclosures.py s1`)

**What the no-tools model says is wrong:** it gives the registry reason as "terminated early due to the COVID-19 pandemic" (the registry says "for business reasons"), says vTv halted enrollment in May 2020 because of COVID-19 (the 8-K of 2020-11-05 says enrollment concluded at the end of September and gives no reason), and concludes "Yes, they match". It does get the efficacy result and the discontinuation right.

<details>
<summary>Same model, no tools and no system prompt (<code>baseline/s1_discrepancy.md</code>), verbatim</summary>

Based on the public disclosures, SEC filings, and the ClinicalTrials.gov registry for the Phase 2 Elevage trial of azeliragon (NCT03980730), here is how the reasons provided by vTv Therapeutics compare:

### 1. The Reason Given to the Registry (ClinicalTrials.gov)
On ClinicalTrials.gov, the official status of the Elevage trial is listed as **Terminated**. 
* **The official reason provided in the registry is:** *"The study was terminated early due to the COVID-19 pandemic."*

### 2. The Reason Told to Investors
vTv Therapeutics provided a two-step explanation to its investors through press releases and SEC filings (such as their 10-Q and 10-K filings):
* **May 2020 (Operational Decision):** vTv announced to investors that it was halting enrollment in the Elevage study early due to the challenges of the COVID-19 pandemic (specifically citing patient safety concerns and disruptions at clinical trial sites). Because enrollment was stopped early, the company decided to clean the database and perform an early/interim analysis on the patient cohort that had already been randomized (approximately 43 patients out of the originally planned 110).
* **December 2020 (Clinical Outcome):** vTv announced the top-line results from this shortened trial. They informed investors that azeliragon **did not meet its primary objective** of demonstrating a statistically significant improvement in cognitive function (measured by ADAS-Cog14) compared to the placebo. Consequently, they discontinued the development of azeliragon for Alzheimer’s disease.

### 3. Do the Two Match?
**Yes, they match.** 

There is no material contradiction between the registry and investor communications:
* **The Registry** lists the *operational* reason the trial was stopped short of its original design: the COVID-19 pandemic prevented full enrollment. 
* **Investor Communications** provided the same operational reason (COVID-19) for stopping enrollment in mid-2020, but added the *clinical* outcome (the drug failed to show efficacy in the patients who did complete the trial), which explained why the program was permanently shelved rather than paused or restarted post-pandemic.

</details>

<details>
<summary>Our agent (<code>runs/s1_discrepancy_latest.md</code>, full trace in <code>runs/20261105-1208_s1_discrepancy.json</code>), verbatim</summary>

## Answer
The records do not show whether vTv Therapeutics intended to mislead anyone by using different terms, but they do reveal a discrepancy between the registry and investor disclosures. [1][2] The registry says the trial was terminated for business reasons. [1] The 8-K says the phase 2 Elevage study did not meet its primary objective, and development of azeliragon for Alzheimer's disease was discontinued. [2]

## Timeline
Trial NCT03980730 started on 2019-06-27 and reached primary completion on 2020-12-01. vTv Therapeutics disclosed the end of enrollment in an 8-K on 2020-11-05, and later reported the trial's failure and discontinuation in an 8-K on 2021-02-24. Results were due on 2021-12-01 and posted on 2022-01-21, and no publications in the linked PubMed records report the trial results.

## Evidence
- The clinical trials registry lists the status of trial NCT03980730 as terminated with 43 patients enrolled. [1]
- The registry lists the reason for termination as for business reasons. [1]
- The 8-K filed on November 5, 2020, says the company decided to conclude enrollment in the study at the end of September. [3]
- The 8-K filed on February 24, 2021, says the Elevage study did not meet its primary objective and the company discontinued development of azeliragon for Alzheimer's disease. [2]
- Trial NCT03980730 started on 2019-06-27, reached primary completion on 2020-12-01, and completed on 2021-01-29. [1]
- The registry says the results were due on 2021-12-01 and were posted on 2022-01-21, making them 51 days late. [1]
- The Drugs@FDA database contains no applications or approvals for azeliragon. [4]
- PubMed lists five reviews mentioning the trial or drug between 2025 and 2026, but none of these articles report the specific trial results or explain the termination. [5][6][7][8][9]

## Where the stories differ
- There is a discrepancy between the registry and investor communications regarding why the research stopped. [1][2]
- The registry says the trial was terminated for business reasons, which is classified as business or strategic. [1]
- The 8-K says the trial did not meet its primary objective and development was discontinued, which represents an efficacy or scientific failure. [2]

## What the data can't tell us
- We cannot tell the real reason for termination beyond the stated text in the registry or the investor filings.
- A discrepancy between these sources is not proof of intent to deceive or mislead.
- The results due date is an approximation of the FDAAA deadline, which only applies to applicable clinical trials, so this delay is not proof that the sponsor broke the law.
- Results published in conference abstracts, non-indexed journals, or company websites may have been missed.
- We also cannot tell if the research stopped early because of the time budget.

## Sources
1. Study of Azeliragon in Patients With Mild Alzheimer's Disease and Impaired Glucose Tolerance. ClinicalTrials.gov registry record. https://clinicaltrials.gov/study/NCT03980730
2. SEC 8-K 0001564590-21-008154. SEC EDGAR filing. https://www.sec.gov/Archives/edgar/data/1641489/000156459021008154/vtvt-ex991_6.htm
3. SEC 8-K 0001564590-20-051429. SEC EDGAR filing. https://www.sec.gov/Archives/edgar/data/1641489/000156459020051429/vtvt-ex991_6.htm
4. Drugs@FDA search for azeliragon: no application. Drugs@FDA application. https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=BasicSearch.process&searchterm=azeliragon
5. Conventional and Emerging Drug Targeting Sites in Alzheimer's Disease and the Role of Translational Informatics in its Diagnosis and Management.. PubMed article. https://pubmed.ncbi.nlm.nih.gov/40207764/
6. Revisiting the therapeutic landscape of tauopathies: assessing the current pipeline and clinical trials.. PubMed article. https://pubmed.ncbi.nlm.nih.gov/40462159/
7. Extracellular Matrix Signaling Cues: Biological Functions, Diseases, and Therapeutic Targets.. PubMed article. https://pubmed.ncbi.nlm.nih.gov/40686923/
8. Tau-Targeted Therapeutic Strategies: Mechanistic Targets, Clinical Pipelines, and Analysis of Failures.. PubMed article. https://pubmed.ncbi.nlm.nih.gov/41090735/
9. Deconstructing the RAGE signaling maze: the molecular key to opening a new dimension of ovarian anti-aging.. PubMed article. https://pubmed.ncbi.nlm.nih.gov/42009954/

_Snapshot date: 2026-11-05. Research rounds: 1. citations_checked: 20, removed: 0._

_83 s, 26 tool calls_

</details>

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

## Evals

Scores from 2026-11-05 (details, misses and rerun commands in `evals/RESULTS.md`). Small samples, so the margin is roughly ±1/sqrt(n).

| Eval | n | Score |
|---|---|---|
| Lead gate: clarify, refuse or research (`evals/task.py@gate`) | 30 | 28/30 (0.93, ±0.18) |
| Full pipeline vs. gold SQL answers, judged by a model (`evals/task.py@facts --limit 10`) | 10 | 10/10; all cited, all with "What the data can't tell us" |
| Citation Checker on 10 planted errors and 10 correct controls (`evals/planted_claims.py`) | 20 | rules only 9/10 caught; rules + model 10/10 caught; 0/10 controls changed either way |
| Disclosures researcher quotes on the three samples (`scripts/run_disclosures.py`) | 6 quotes | 6/6 word for word in the cited record |

The two gate misses are intent questions ("Do biotech companies lie to investors?") that we labelled clarify. The Lead refused them instead, saying what the tool can check.

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
