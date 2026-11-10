# Ghost Trials Autopsy

**What happened to the trials that stopped early?**

Ghost Trials Autopsy is a deep research agent for clinical trials that ended before they were supposed to.
Ask about a drug, a sponsor, a condition or a trial ID (NCT number), and a team of agents answers four questions:

1. **Why did the trial stop?** The registry status and the reason the sponsor gave (ClinicalTrials.gov).
2. **Were the results ever reported?** Results posted on ClinicalTrials.gov, a journal paper, and how late (PubMed, Europe PMC).
3. **What did the sponsor tell investors?** SEC 8-K filings near the stop date (SEC EDGAR).
4. **Do those stories match?** Registry reason vs. investor language vs. publication record.

**Who it's for:** health reporters, patient advocates and research-integrity people. A reporter covering a
mid-size biotech can ask "Did this company stop any trials without reporting results, and what did it tell
investors?" and get a cited answer in about two minutes.

**Why it matters:** people took risks in trials whose results were never shared, other researchers can't learn
from those failures, and the reason a company gave investors may not match what it told the registry.

**How to use it:** type a question or click an example chip. The trace panel shows the Lead planning, the
three Researchers working in parallel (with timing bars), then the Writer, the Citation Checker and the Skeptic, who flags what else could explain the finding and drafts questions for the sponsor. The report
has a timeline per trial (start, stop, results due, results posted or a red "never posted" marker, 8-K and
publication dates), citations you can click, and a "What the data can't tell us" box. A vague question gets
clarifying options instead of research.

No time to wait? The **ghost ledger** at the bottom of the page shows instant, no-AI views of the whole snapshot:
who goes silent, a report card for any sponsor, and every trial whose 8-K and registry tell different stories.

IEOR 4570 Project 2, Deep Research path. Team: Rishika (rm4318), Shreya (svs2148), Kshamaa (ks4423).

**Live app:** https://ghost-trials-autopsy-895402809785.us-central1.run.app

![Ghost Trials Autopsy architecture: the browser sends a question to FastAPI on Cloud Run; the Lead decides to clarify, refuse or research; three Researchers run in parallel in fresh contexts against the DuckDB snapshot and live APIs; findings and gaps return to the Lead for up to three rounds; the Writer drafts a cited report and the Citation Checker fixes or removes unsupported sentences](docs/architecture.svg)

## Sample queries

Every query below is in `samples.json` and works on the live app. Each report ends with "What the data can't
tell us" and a checker line (`citations_checked: n, removed: k`); the trace panel shows every tool call,
grouped by agent.

1. `vTv Therapeutics terminated its phase 2 Elevage trial of azeliragon (NCT03980730). What reason did it give the registry, what did it tell investors, and do the two match?`
   Expected: registry says "for business reasons", the 8-K says the trial "did not meet its primary objective". A discrepancy (details below).
2. `Sorrento Therapeutics terminated its phase 2 COVI-MSC trial NCT04903327. Why did it stop, and were the results ever posted or published?`
   Expected: slow enrollment; results never posted, 1,164 days past the approximate due date; no results paper (details below).
3. `Did Entero Therapeutics (formerly First Wave BioPharma) stop any phase 2 trials without posting results, and what reasons did it give?`
   Expected: three terminated trials with no posted results, two phase 2 (NCT04839575, NCT04243551) and one phase 1/2 (NCT03521232), each with a COVID-19 or enrollment reason; the nearby 8-Ks name the drugs but give no reason (details below).
4. `Which stopped trials in the snapshot have an 8-K that gives a different reason than the registry? Start with the ones checked by hand.`
   Expected: 43 trials labelled discrepancy, 5 of them checked by hand: vTv NCT03980730, Allakos NCT05528861, Lilly NCT02227784 and Summit NCT04802837 (registry gives a business reason, the 8-K an efficacy failure) and Arrowhead NCT02452528 (registry "Company decision", the 8-K an FDA clinical hold after a primate toxicology study). 37 others are keyword-rule leads whose 8-K names only the drug, and the report says they are not confirmed.
5. `Why do Alzheimer's trials fail?` Expected: **clarification**, no research (example below).
6. `Did Sorrento Therapeutics break the law by not posting results for its terminated COVID-19 trials?`
   Expected: a **qualified answer**: the facts on record, and a plain statement that the data can't show a legal violation (example below).

`uv run python scripts/run_samples.py` reruns them into `runs/`. `uv run python scripts/baseline.py` asks the
same model (`vertex_ai/gemini-3.5-flash`) the same question with no tools and no system prompt, into `baseline/`.

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

### Sponsor without posted results: Entero Therapeutics

**Query:** "Did Entero Therapeutics (formerly First Wave BioPharma) stop any phase 2 trials without posting results, and what reasons did it give?"

**Expected answer (checked by hand against the snapshot and the 8-K text on 2026-11-07):**

- Entero stopped three phase 2 trials (one is phase 1/2) that enrolled patients and never posted results:

  | Trial | Drug, condition | Registry reason | Primary completion | Results due (approx.) | Days late on 2026-11-05 |
  |---|---|---|---|---|---|
  | NCT03521232 (phase 1/2) | niclosamide enemas, ulcerative proctitis | "Covid-19" | 2022-09-19 | 2023-09-19 | 1,143 |
  | NCT04839575 | latiglutenase, celiac disease with type 1 diabetes | "Covid-19 interruptions and enrollment challenges" | 2022-12-19 | 2023-12-19 | 1,052 |
  | NCT04243551 | latiglutenase, celiac disease | "Due to low enrollment related to Covid." | 2023-10-16 | 2024-10-15 | 751 |

- No results paper for any of them: every PubMed article linked to these NCT IDs is a Europe PMC mention (3, 4 and 5 articles).
- Entero (CIK 0001604191) 8-Ks near each stop name the drug but give no reason for stopping. Those filed 2022-10-12, 2022-11-22 and 2022-11-28 still say the company "is also advancing multiple programs involving niclosamide, including FW-UP for ulcerative proctitis", after NCT03521232's primary completion. A discrepancy in tone, not proof of intent: the text is boilerplate. The `discrepancies` table marks these rows `no_reason_in_8k`.
- Also in the snapshot, but not "stopped without posting results": two phase 2 niclosamide COVID-19 trials (NCT04436458, NCT04542434) were withdrawn before enrolling anyone ("Sponsor asset acquired by another pharma company"), so no results were due; and NCT04858425 was terminated for lack of efficacy and did post results.

**Source:**

- `https://clinicaltrials.gov/api/v2/studies/NCT03521232`, `.../NCT04839575`, `.../NCT04243551`
- tables `trials` and `trial_derived`: `SELECT * FROM trials JOIN trial_derived USING (nct_id) WHERE sponsor IN ('Entero Therapeutics', 'AzurRx SAS')`
- table `sponsor_cik`, `sponsor = 'Entero Therapeutics'` (CIK 0001604191)
- table `filings`: EDGAR accessions 0001104659-22-107922, 0001104659-22-121003, 0001104659-22-122476 (NCT03521232); 0001104659-23-126593, 0001104659-23-129426, 0001104659-24-084206 (NCT04243551); 0001104659-24-079101, 0001104659-24-084206, 0001104659-24-092491 (NCT04839575)
- table `publications`, `link_type = 'europepmc_mention'` for all three

**What the no-tools model says is wrong:** it names none of the three trials. The NCT IDs it does give belong to other sponsors: NCT04862416 is a Radboud University vaccine study, NCT04543188 a Pfizer cancer study, and NCT05711251 a physical activity study at a Turkish university. It also gives reasons ("capital conservation", "lack of efficacy") that are not the registry reasons for any of Entero's stopped trials without results.

<details>
<summary>Same model, no tools and no system prompt (<code>baseline/s3_sponsor.md</code>), verbatim</summary>

Entero Therapeutics (formerly known as **First Wave BioPharma**, and prior to that, **AzurRx BioPharma**) has gone through multiple strategic pivots, name changes, and mergers (most recently merging with ImmunogenX in early 2024). During these transitions, the company stopped or paused several clinical programs, particularly in its niclosamide and adrulipase pipelines. 

While the company frequently issued press releases with "top-line" data, some of these trials were discontinued, and full, detailed results were not formally published or posted to the ClinicalTrials.gov registry. 

Here is a breakdown of the Phase 2 trials they stopped, deprioritized, or paused, along with the reasons provided:

---

### 1. The Niclosamide Programs (FW-COV and FW-UP)
In **October 2022**, First Wave BioPharma announced a major strategic pivot to wind down or pause its niclosamide-based clinical programs. 

*   **FW-COV (Niclosamide for COVID-19 GI infections):** 
    *   **The Trial:** A Phase 2 trial (the "RESERVOIR" study, NCT04862416) evaluating an oral formulation of niclosamide for removing SARS-CoV-2 from the gastrointestinal tract.
    *   **What Happened:** The company reported some preliminary topline data in early 2022 but ultimately halted further development. 
    *   **Reasons Given:** First Wave cited **strategic reprioritization and capital conservation**. They decided to focus their limited financial resources and clinical focus entirely on their lead asset, adrulipase, for exocrine pancreatic insufficiency (EPI).
*   **FW-UP (Niclosamide for Ulcerative Proctitis):**
    *   **The Trial:** A Phase 2a trial (NCT04543188) evaluating a topical formulation of niclosamide for patients with active ulcerative proctitis. 
    *   **What Happened:** Although they announced topline data in June 2022 indicating the drug was safe, the clinical program was halted before advancing further.
    *   **Reasons Given:** Similar to FW-COV, the primary reasons were **capital preservation** and a corporate decision to deprioritize niclosamide in favor of adrulipase.

---

### 2. Adrulipase (MS1819) for Cystic Fibrosis-Related EPI
Adrulipase was First Wave's lead yeast-derived lipase enzyme designed to treat exocrine pancreatic insufficiency (EPI) in patients with cystic fibrosis (CF). 

*   **The Trial:** Phase 2 clinical trial of a new *microgranule formulation* of adrulipase (NCT05711251), launched to improve the delivery and efficacy of the drug after a previous Phase 2b trial (OPTION-2) failed to meet its primary endpoint in 2021.
*   **What Happened:** In July 2023, First Wave announced that the Phase 2 microgranule trial **did not meet its primary efficacy endpoint** (the coefficient of fat absorption, or CFA, did not reach the therapeutic threshold compared to commercial pig-derived enzymes). 
*   **The Outcome:** Rather than starting new trials, the company effectively paused internal clinical development of adrulipase. 
*   **Reasons Given:** The company cited **lack of efficacy** (the microgranule formulation did not provide the necessary therapeutic benefit) and subsequently announced they were exploring "strategic alternatives" (such as licensing or selling the asset) to avoid spending further cash on it.

---

### 3. Shift to Latiglutenase (Entero Therapeutics Era)
Following the merger with ImmunogenX in early 2024, First Wave BioPharma rebranded as **Entero Therapeutics**. 

With this transition, the company shifted its primary focus to **Latiglutenase (IMGX003)**, an oral biotherapeutic degradation enzyme for celiac disease. Consequently, older Phase 2 assets from the First Wave/AzurRx portfolio (such as adrulipase and the remaining niclosamide programs) have been sidelined or quietly discontinued due to **strategic misalignment** with their new focus on GI-focused celiac treatments and lack of funding to pursue multiple pipelines simultaneously.

### Summary of Reasons
When Entero Therapeutics (First Wave) stopped or failed to progress these Phase 2 trials, the reasons fell into three main categories:
1.  **Clinical Failure / Lack of Efficacy:** Specifically for the adrulipase microgranule Phase 2 trial in 2023, which failed to meet its primary endpoint.
2.  **Strategic Reprioritization:** Shelving the niclosamide trials to focus solely on adrulipase (in 2022), and later shelving adrulipase to focus on latiglutenase (in 2024).
3.  **Capital Conservation:** As a micro-cap biotechnology firm, the company lacked the cash reserves to fund multiple late-stage clinical trials simultaneously and chose to preserve cash for their highest-conviction assets.

</details>

<details>
<summary>Our agent (<code>runs/s3_sponsor_latest.md</code>, full trace in <code>runs/20261107-2246_s3_sponsor.json</code>), verbatim</summary>

## Answer
Entero Therapeutics (formerly First Wave BioPharma) terminated three Phase 2 or Phase 1/2 clinical trials without posting results on ClinicalTrials.gov: NCT03521232, NCT04839575, and NCT04243551. [1][2][3] The reasons listed on the clinical trials registry for terminating these trials were related to COVID-19, specifically citing "Covid-19" for NCT03521232, "Covid-19 interruptions and enrollment challenges" for NCT04839575, and low enrollment related to COVID-19 for NCT04243551. [1][2][3] The sponsor's SEC 8-K filings mentioned the corresponding drug candidates but did not provide specific reasons for terminating these trials, and no results publications were found in PubMed. [4][5][6][7][8][9]

## Timeline
For NCT03521232, the trial started on 2018-05-15, reached primary completion on 2022-09-19, and results were due on 2023-09-19 but have not been posted, while 8-K filings in late 2022 mentioned the drug but not the stopping reason, and no results publication was found. For NCT04839575, the trial started on 2021-04-06, reached primary completion on 2022-12-19, and results were due on 2023-12-19 but have not been posted, while 8-K filings in 2024 discussed the drug pipeline without explaining the termination, and no results publication was found. For NCT04243551, the trial started on 2019-11-01, reached primary completion on 2023-10-16, and results were due on 2024-10-15 but have not been posted, while 8-K filings in late 2023 and mid-2024 mentioned pipeline changes without explaining the termination, and no results publication was found.

## Evidence
- NCT03521232 was a Phase 1/2 trial that started on 2018-05-15, reached primary completion on 2022-09-19, and was terminated without results posted. [1]
- The clinical trials registry lists the reason for stopping NCT03521232 as "Covid-19". [1]
- NCT04839575 was a Phase 2 trial that started on 2021-04-06, reached primary completion on 2022-12-19, and was terminated without results posted. [2]
- The clinical trials registry lists the reason for stopping NCT04839575 as "Covid-19 interruptions and enrollment challenges". [2]
- NCT04243551 was a Phase 2 trial that started on 2019-11-01, reached primary completion on 2023-10-16, and was terminated without results posted. [3]
- The clinical trials registry lists the reason for stopping NCT04243551 as "Due to low enrollment related to Covid." [3]
- The sponsor filed 8-K forms discussing niclosamide in late 2022, but did not specify why NCT03521232 was stopped. [4][10][11]
- The sponsor filed 8-K forms discussing latiglutenase in 2023 and 2024, but did not specify why NCT04839575 or NCT04243551 were stopped. [12][5][6][13]
- No results publication for NCT03521232 was found in PubMed, though three articles only mention the trial. [7]
- No results publication for NCT04839575 was found in PubMed, though four articles only mention the trial. [8]
- No results publication for NCT04243551 was found in PubMed, though five articles only mention the trial. [9]

## Where the stories differ
- The clinical trials registry lists specific COVID-19 and enrollment-related reasons for terminating trials NCT03521232, NCT04839575, and NCT04243551, whereas the sponsor's SEC 8-K filings do not specify reasons for stopping these individual trials, only discussing general pipeline and corporate developments. [1][2][3][4][5][6]

## What the data can't tell us
- We cannot determine the real underlying reasons for terminating these trials beyond the brief explanations stated in the registry.
- The lack of detailed explanations in the investor disclosures does not prove any intent to mislead.
- The results due date (primary completion plus 365 days) only approximates the FDAAA deadline, which only applies to applicable clinical trials, so this is not evidence that the sponsor broke the law.
- Results published in conference abstracts, non-indexed journals, or directly on company websites may have been missed because we only searched PubMed and Europe PMC.
- No 10-K or 10-Q filings were available in the snapshot database, so we cannot tell if more detailed trial termination disclosures were made in those reports.

## Sources
1. A Study of Niclosamide Enemas in Subjects With Active Ulcerative Proctitis or Ulcerative Proctosigmoiditis. ClinicalTrials.gov registry record. https://clinicaltrials.gov/study/NCT03521232
2. Study of Latiglutenase in T1D/CD Patients. ClinicalTrials.gov registry record. https://clinicaltrials.gov/study/NCT04839575
3. Prospective, Randomized, Double-Blind, Placebo-Controlled, Crossover Study in Symptomatic CD Patients. ClinicalTrials.gov registry record. https://clinicaltrials.gov/study/NCT04243551
4. Entero Therapeutics 8-K filed 2022-10-12. SEC EDGAR filing. https://www.sec.gov/Archives/edgar/data/1604191/000110465922107922/tm2228013d1_ex99-2.htm
5. SEC filing 0001104659-24-084206. SEC EDGAR filing. https://www.sec.gov/Archives/edgar/data/1604191/000110465924084206/tm2420546d1_ex99-1.htm
6. Entero Therapeutics 8-K filed 2023-12-18. SEC EDGAR filing. https://www.sec.gov/Archives/edgar/data/1604191/000110465923126593/tm2333106d1_ex99-1.htm
7. No results publication found for NCT03521232 (3 article(s) only mention it). PubMed article. https://pubmed.ncbi.nlm.nih.gov/?term=NCT03521232%5Bsi%5D
8. No results publication found for NCT04839575 (4 article(s) only mention it). PubMed article. https://pubmed.ncbi.nlm.nih.gov/?term=NCT04839575%5Bsi%5D
9. No results publication found for NCT04243551 (5 article(s) only mention it). PubMed article. https://pubmed.ncbi.nlm.nih.gov/?term=NCT04243551%5Bsi%5D
10. SEC filing 0001104659-22-121003. SEC EDGAR filing. https://www.sec.gov/Archives/edgar/data/1604191/000110465922121003/tm2231091d1_ex99-1.htm
11. SEC filing 0001104659-22-122476. SEC EDGAR filing. https://www.sec.gov/Archives/edgar/data/1604191/000110465922122476/tm2231455d2_ex99-1.htm
12. Entero Therapeutics 8-K filed 2024-07-11. SEC EDGAR filing. https://www.sec.gov/Archives/edgar/data/1604191/000110465924079101/tm2419264d1_ex99-1.htm
13. SEC filing 0001104659-23-129426. SEC EDGAR filing. https://www.sec.gov/Archives/edgar/data/1604191/000110465923129426/tm2333743d1_ex99-1.htm

_Snapshot date: 2026-11-05. Research rounds: 2. citations_checked: 34, removed: 0._

_84 s, 37 tool calls_

</details>

### Vague question: clarification instead of research

**Query:** "Why do Alzheimer's trials fail?" It names a condition but no scope, so the Lead asks before it
spends any research. No researcher runs (only the Lead's own look-ups appear in `tool_calls`).
Verbatim from `runs/vague_latest.md`:

> Which Alzheimer's disease trials or drug programs would you like to investigate?
>
> Try one of these:
> - A summary of all phase 2 and 3 Alzheimer's disease trials that stopped early between 2015 and 2023, grouped by their registry reasons.
> - Why Biogen stopped its phase 3 Aducanumab trials (NCT02477800 and NCT02484547) in 2019, and whether its SEC filings and registry reasons matched.
> - Why Axovant terminated its phase 3 Intepirdine trial (NCT02586909) in 2017, and how the results were reported.

Replying with one of the options (same `session_id`) runs the research on the original question plus the choice.

### Can't answer: "Did Sorrento break the law?"

**Query:** "Did Sorrento Therapeutics break the law by not posting results for its terminated COVID-19 trials?"
The agent reports what the records show (two terminated trials, results 1,324 and 1,164 days past the
approximate due date) and says plainly that this can't establish a legal violation. From
`runs/cant_answer_latest.md`, the first sentence of the answer and the limits section, verbatim:

> Whether Sorrento Therapeutics has reporting discrepancies by not posting results for its terminated COVID-19 trials is a determination that cannot be made from these records, but the clinical trial registry shows that the results are long overdue. [1][2]
>
> **What the data can't tell us**
> - The registry does not provide the real reason for stopping beyond the stated text.
> - A lack of clinical outcomes in SEC filings or publications is not proof of an intent to mislead.
> - The results due date is an approximation of the FDAAA deadline, which only applies to applicable clinical trials, a status that is not fully public, so the delayed reporting is not evidence that Sorrento Therapeutics broke the law.
> - Results published in conference abstracts, non-indexed journals, or company websites may have been missed.

A question that is entirely out of scope ("Is drug X safe for me?") gets a short refusal that says what the tool can do instead, in the same response shape.

## How the agents work

| Agent | Prompt | Job | Limits |
|---|---|---|---|
| **Lead** | `prompts/lead.md` | Gate (clarify, refuse or research), plan, dispatch, review findings for gaps | ≤3 research rounds (`MAX_RESEARCH_ROUNDS`) |
| **Researcher** ×3 | `prompts/researcher.md` + `prompts/lane_*.md` | One lane each: trials, disclosures, publications. Returns `[{claim, evidence_ids, confidence, notes}]` plus gaps | ≤8 turns each |
| **Writer** | `prompts/writer.md` | Report from the evidence store only: Answer, Timeline, Evidence, Where the stories differ, What the data can't tell us, Sources | ≤4 turns |
| **Citation Checker** | `prompts/checker.md` | Checks every `[n]`: the evidence id exists and the date, status, number or quote matches the record. Fixes or removes the sentence | ≤4 turns |
| **Skeptic** | `prompts/skeptic.md` | Reads the checked report like an editor before publication: how strong the finding is (strong, moderate, weak, and which records it rests on), 2 to 4 ordinary explanations the records can't rule out, and 2 to 4 questions a reporter could put to the sponsor. Its sentences cite nothing, so the Checker's rules screen each one against the whole evidence store (no invented date or quote, no "hid" or "misled") | ≤2 turns; skipped when under 25 s of budget is left |
| **Ledger Analyst** (Explore section) | `prompts/analyst.md` | Answers whole-snapshot questions with SQL ("which conditions have the most silent trials?"). The app reruns its final SELECT itself and shows that table, and checks every number in its answer against the table | ≤8 turns, 90 s |

- **Clarify gate.** A question is vague when it has no concrete target (drug, sponsor, NCT ID or condition)
  and no scope (phase, time window, or which of the four questions). The Lead then returns 2 to 4 concrete
  rewrites and does no research.
- **Parallel, fresh contexts.** `dispatch_researchers` starts every brief with `asyncio.gather`. Each
  Researcher gets a new message list holding only its system prompt and its brief, never the Lead's
  conversation or another Researcher's. Start and end times are logged and drawn as timing bars in the trace.
- **Going back for more.** The Lead lists gaps as structured JSON (for example "sponsor matched to a CIK but no
  8-K in the window") and dispatches only the lanes that can fill them, until no gaps remain or the round cap.
- **Budget.** The whole request has a 240 s wall clock budget (`REQUEST_BUDGET_S`). Near it, the Lead skips
  further rounds and the report says research stopped early.
- **Evidence ids.** Every tool record carries a `source_url` and a stable id: `ctgov:NCT03980730`,
  `sec:0001564590-21-008154`, `pubmed:34831101`, `fda:...`, or `sql:<hash>` for a snapshot aggregate.

## Tools

| Tool | Lane | Owner | What it does |
|---|---|---|---|
| `query_trials_sql` | Trials (all lanes read) | Rishika | Read-only SQL over the snapshot (one `SELECT`, `LIMIT` enforced) |
| `read_mappings` / `get_enum_values` | Trials (all lanes read) | Rishika | Table and column meanings, and the exact allowed values of enum columns |
| `get_trial_live` | Trials | Rishika | Live ClinicalTrials.gov record, to confirm or refresh the snapshot |
| `get_fda_approvals` | Trials | Rishika | Drugs@FDA lookup: was the drug ever approved, and when |
| `get_snapshot_stats` | Shared | Rishika | Counts and base rates (for example the share of stopped trials with a blank reason), to put a claim in context |
| `find_sponsor_cik` | Disclosures | Shreya | Sponsor name to SEC CIK (snapshot match, then live company tickers) |
| `get_trial_filings` | Disclosures | Shreya | 8-Ks within ±120 days of a trial's stop that mention it |
| `find_discrepancies` | Disclosures | Shreya | Trials whose 8-K reason differs from the registry, hand-checked rows first |
| `search_sec_filings` | Disclosures | Shreya | Live EDGAR full-text search by query, CIK, date range and form |
| `get_filing_excerpt` | Disclosures | Shreya | Only the filing paragraphs that match given keywords |
| `find_publications` | Publications | Kshamaa | Papers linked to an NCT ID (snapshot, then live PubMed and Europe PMC), each with a link strength |
| `get_abstract` | Publications | Kshamaa | One PubMed abstract, to tell a results paper from a review that just mentions the trial |

`POST /chat` takes `{message, session_id}` and returns `{response, session_id, tool_calls}`, the Project 1
shape. Every tool call from every agent is in `tool_calls` with an `agent` field (`lead`,
`researcher:trials`, `researcher:disclosures`, `researcher:publications`, `writer`, `checker`), its arguments
and a short result summary.

```bash
curl -s https://ghost-trials-autopsy-895402809785.us-central1.run.app/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "Sorrento Therapeutics terminated its phase 2 COVI-MSC trial NCT04903327. Why did it stop, and were the results ever posted or published?"}'
```

`GET /health` returns 200 and the snapshot date. `GET /run` streams the same research as Server-Sent Events for the page's live trace.

## Data

![Ghost Trials Autopsy snapshot: ClinicalTrials.gov feeds the trials table and its derived columns; SEC tickers match sponsors to CIKs, 8-Ks near each stop become filings, and filings that disagree with the registry become discrepancies; PubMed and Europe PMC articles are linked by NCT ID](docs/snapshot.svg)

Live APIs can be slow or down, and graders wait at most 5 minutes, so the agents work from a snapshot that ships
inside the image (`data/autopsy.duckdb`, built 2026-11-05) and use live APIs only to add detail.
Rebuild it with `uv run python scripts/build_snapshot.py`.

**Scope:** interventional, industry-sponsored, phase 2 or 3 trials (phase 1/2 and 2/3 included) with primary
completion from 2015-01-01 to 2023-12-31, every status (terminated, withdrawn, suspended, completed) so stopped
trials can be compared with the rest. 16,473 trials, 3,739 of them stopped, 1,731 of those with no results posted.

| Lane | Owner | Source | What we pull |
|---|---|---|---|
| A: Trials | Rishika (rm4318) | [ClinicalTrials.gov API v2](https://clinicaltrials.gov/data-api/api) `clinicaltrials.gov/api/v2/studies` | status, `whyStopped`, phase, sponsor, dates, `hasResults`, enrollment |
| A: Trials | Rishika (rm4318) | [openFDA Drugs@FDA](https://open.fda.gov/apis/drug/drugsfda/) `api.fda.gov/drug/drugsfda.json` | whether and when a drug was approved |
| B: Disclosures | Shreya (svs2148) | [SEC EDGAR full-text search](https://efts.sec.gov/LATEST/search-index) and the filings archive | 8-K language about the trial |
| B: Disclosures | Shreya (svs2148) | [SEC company tickers](https://www.sec.gov/files/company_tickers.json) | sponsor name to CIK |
| C: Publications | Kshamaa (ks4423) | [PubMed E-utilities](https://eutils.ncbi.nlm.nih.gov/entrez/eutils/) | articles linked to an NCT ID (`NCT01234567[si]`) |
| C: Publications | Kshamaa (ks4423) | [Europe PMC REST](https://www.ebi.ac.uk/europepmc/webservices/rest/search) | fallback publication search |

**Derived columns** (`trial_derived`):

- `results_due_date` is primary completion + 365 days, an approximation of the FDAAA deadline. It is NULL for
  trials that never enrolled anyone.
- `days_late` counts from that date to the posting date, or to the snapshot date if nothing was posted.
- `why_stopped_category` (`safety`, `efficacy`, `business/strategic`, `enrollment`, `other`, `blank`) comes from
  keyword rules first (`ghost/classify.py`), then one LLM pass for the rest; `why_stopped_method` records which.
  The rules skip phrases that only look like reasons, such as "Data Safety Monitoring Board", "not due to
  safety concerns" or "followed up for safety".

Every HTTP call has a timeout, up to 3 retries with backoff, and a disk cache. SEC calls send the
`SEC_USER_AGENT` contact string and stay under 10 requests a second; NCBI calls stay under 3.

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

## Explore the snapshot instantly (no AI)

A full investigation takes one to four minutes. The **ghost ledger** at the bottom of the page answers the
big-picture questions in under a second, straight from the snapshot with no model calls (`ghost/explore.py`,
`GET /api/ledger`, `/api/sponsor?name=`, `/api/differ`). Every number uses the same definitions as the agents'
`get_snapshot_stats` tool, and a test checks that they agree.

- **Who goes silent.** A trial is *silent* when it stopped after enrolling people and has no results on
  ClinicalTrials.gov and no linked paper (registry or PubMed link, published after the trial started). In the
  snapshot, **759 of 2,905** stopped trials that enrolled people are silent, and **62,849 people** took part in
  them. Broken down by the reason the sponsor gave, trials stopped for "other" reasons (35%) or too few patients
  (32%) go silent about twice as often as trials stopped because the drug didn't work (15%): a failed drug is
  more likely to be reported than a trial that quietly ran out of road. A year chart compares results posting for
  stopped and completed trials, and a leaderboard shows the sponsors at both ends (at least 5 stopped trials each),
  with a caveat that many non-US sponsors have no duty to post on ClinicalTrials.gov.
- **Sponsor report card.** Type any sponsor (with autocomplete) to see how many of its trials stopped, how many
  went silent and how many people were in them, how it ranks against the 92 sponsors with at least 5 stopped
  trials, its SEC CIK (or that it has none, so there are no investor filings to compare), how many of its trials
  have an 8-K that tells a different story, and a list of its stopped trials. Each trial has an "autopsy" button
  that sends the agents to investigate it, and the card has a button to investigate the whole sponsor.
- **Stories that differ.** The 43 stopped trials where an 8-K and the registry point different ways, with the
  registry reason and the 8-K sentence side by side. The five checked by hand come first, then the ones whose 8-K
  names the trial, then *leads* whose 8-K names only the drug. Each card opens a full case with the agents.
- **Ask the ledger (AI).** The one tab that uses a model: type a whole-snapshot question in plain English and the
  Ledger Analyst agent writes and runs the SQL, usually in 10 to 35 seconds. The page shows the analyst's answer,
  a bar chart when the result is a label and a number, the table, and the SQL it wrote. The table is the app
  rerunning that exact SELECT through the read-only guard, never the model's copy, and every number in the answer
  is checked against it: a number that isn't in the table (a sum the model did in its head, say) is flagged for
  the reader to check. Medical-advice or legal questions get a refusal with an example of what it can answer.
- **Shareable cases.** `?q=<question>` opens and runs a case and `?sponsor=<name>` opens a report card, so a
  reporter can send a colleague a link. A finished report can be downloaded as Markdown.

## What it can't tell you

The agent says so in every report ("What the data can't tell us"), specific to the question:

- **The real reason a trial stopped.** We only know what the sponsor wrote in the registry and in filings.
- **Intent.** A registry reason that differs from an 8-K is a discrepancy between sources, not proof that anyone meant to mislead.
- **Legal violations.** `results_due_date` is an approximation, and which trials legally have to post results (FDAAA "applicable clinical trial" status) is not fully public. The agent never says a sponsor broke the law.
- **Results published elsewhere.** Conference abstracts, journals PubMed doesn't index, and company websites can be missed.
- **Private sponsors.** They file nothing with the SEC, so there is no investor story to compare.
- **Trials outside the snapshot.** Other phases, non-industry sponsors or other years get a live lookup or an explicit "outside our data" note.
- **Medical advice.** It never says whether anyone should take a drug.

## Run locally

1. A GCP project with Vertex AI enabled (the course's *Setting up GCP and Gemini* guide), then `gcloud auth application-default login`.
2. `cp .env.example .env` and set `SEC_USER_AGENT` to a contact string with an email.
3. `uv run app.py`, then open http://localhost:8000

The snapshot is in the repo, so nothing has to be rebuilt to run it.

## Tests

- `uv run pytest`: 335 tests (315 offline; 20 call Gemini and run only with `LIVE=1 uv run pytest`). Among them:
  - Rubric proofs: the `/chat` shape and the `agent` field on every tool call (`test_shape.py`), researchers
    overlapping in time and starting from fresh message lists (`test_parallel.py`), the Lead's second round and
    round cap (`test_gap_loop.py`), clarification with no researcher calls (`test_clarify.py`), every `[n]`
    mapping to a stored source (`test_citations.py`), and the qualified answer to a legal question (`test_cant_answer.py`).
  - Each agent step on its own against Gemini (`test_steps_live.py`): the Lead's gate on research, clarify and
    refuse questions; each Researcher lane on a real trial, citing only ids its tools returned; the Writer filling
    every section; and the Checker rejecting a planted wrong fact.
  - Corner cases: the SQL guard and the read-only, no-file, no-network connection (`test_sql_guard.py`,
    `test_sql_sandbox.py`); each citation rule (`test_citecheck_rules.py`); every tool's bad input, and live APIs
    that fail (`test_tool_inputs.py`); a crashed researcher, a failed review, too many gaps, empty or huge
    questions, and a report with every claim removed (`test_pipeline_edges.py`); bad request bodies, the
    clarification follow-up and the live stream (`test_api_edges.py`); retries, time limits and the cache
    (`test_robustness.py`); and submission rules such as pinned dependencies and no em dashes (`test_repo_hygiene.py`).
  - The Skeptic (`test_skeptic.py`): invented dates and accusations are dropped, its section sits between "What
    the data can't tell us" and the sources, a failure or a short budget never costs the report, and no dashes.
    The Ledger Analyst (`test_analyst.py`): the table comes from rerunning its SQL, a non-SELECT is never run, an
    invented number is flagged, out-of-scope questions get no table, and a slow run is an answer, not an error.
  - The Explore section (`test_explore.py`): its numbers match the agents' `get_snapshot_stats`, the breakdowns
    add up, sample s2 shows as silent on Sorrento's report card, the five hand-checked discrepancies lead the
    wall, and sponsor names are bound parameters, never SQL text.
- `tests/test_deploy.sh`: curls the deployed `/health` and one sample query, and fails if it takes over 300 s.

## Evals

Scores from 2026-11-05 (details, misses and rerun commands in `evals/RESULTS.md`). Small samples, so the margin is roughly ±1/sqrt(n).

| Eval | n | Score |
|---|---|---|
| Lead gate: clarify, refuse or research (`evals/task.py@gate`) | 30 | 28/30 (0.93, ±0.18) |
| Full pipeline vs. gold SQL answers, judged by a model (`evals/task.py@facts --limit 10`) | 10 | 10/10; all cited, all with "What the data can't tell us" |
| Citation Checker on 10 planted errors and 10 correct controls (`evals/planted_claims.py`) | 20 | rules only 9/10 caught; rules + model 10/10 caught; 0/10 controls changed either way |
| Disclosures researcher quotes on the three samples (`scripts/run_disclosures.py`) | 6 quotes | 6/6 word for word in the cited record |

The two gate misses are intent questions ("Do biotech companies lie to investors?") that we labelled clarify. The Lead refused them instead, saying what the tool can check.

## Deploy

Cloud Run (`ghost-trials-autopsy`, us-central1) with continuous deploy from this repo: the Cloud Build trigger
`deploy-on-main` runs `cloudbuild.yaml` on every push to `main`, which builds the `Dockerfile` (`uv sync --frozen`,
listens on `$PORT`), pushes the image to Artifact Registry and deploys it.

Settings that matter for this app:
- **Request timeout: 600 s.** Graders wait up to 5 minutes; our own budget is 240 s.
- **Memory: 2 GiB.** The DuckDB snapshot is opened read-only inside the container.
- The service account needs **Vertex AI User** to call Gemini, so there is no API key. `SEC_USER_AGENT` comes from the Secret Manager secret `sec-user-agent` and is never committed. `min-instances=1` during grading, so there are no cold starts.

## Project layout

```
app.py              FastAPI: POST /chat (Project 1 shape), GET /run (live stream), GET /health, GET /api/* (Explore)
index.html          the frontend: header, example chips, agent trace, trial timelines, citations, Explore section
ghost/explore.py    the Explore section's SQL: ledger, sponsor report card, leaderboard, stories that differ
ghost/pipeline.py   Lead, Researchers, Writer, Checker, and the round loop
ghost/tools.py      the agents' tools, one section per lane
ghost/classify.py   why_stopped categories: keyword rules, then one LLM pass
ghost/http.py       timeouts, retries, per-host rate limits, disk cache
ghost/db.py         read-only DuckDB access and the SQL guardrails
prompts/            one system prompt per agent shape, plus one per lane
scripts/            build_snapshot.py, baseline.py, run_samples.py, per-lane runners
data/               autopsy.duckdb snapshot and mappings.json (table and column meanings)
runs/, baseline/    agent outputs and no-tools answers for the sample queries
evals/, tests/      Inspect evals; pytest suite and test_deploy.sh
docs/               architecture and snapshot diagrams (python3 docs/make_diagrams.py)
cloudbuild.yaml     continuous deploy
PROPOSAL.md         plan and who owns what; NOTES.md: decisions and rubric evidence
```
