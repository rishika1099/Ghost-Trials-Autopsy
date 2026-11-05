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
