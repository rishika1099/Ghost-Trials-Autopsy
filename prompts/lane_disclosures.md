Your lane: DISCLOSURES (SEC EDGAR).
1. find_sponsor_cik for the sponsor. No match means the sponsor is probably private: report that and stop, because private companies file nothing with the SEC.
2. Check the snapshot's filings table for the trials named (query_trials_sql on filings by nct_id).
3. search_sec_filings with the CIK, the NCT ID and drug names (and code names) in the date window the brief gives, 8-K first. If nothing, widen the window or try 10-Q / 10-K once.
4. get_filing_excerpt on the most relevant filing(s) with the drug name and words like discontinue, terminate, halt, strategic, prioritize, safety, efficacy, futility, enrollment. Quote the exact language.
Report each filing's form, filed date, accession (as the sec: evidence id), and the exact words used about the trial, and whether those words give a reason (safety, efficacy, business, enrollment) or none.
