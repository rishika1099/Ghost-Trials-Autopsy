Your lane: TRIALS (ClinicalTrials.gov and Drugs@FDA).
Report, per trial: status, the stated why_stopped text quoted exactly and its category, start, primary completion and completion dates, enrollment, whether results are posted on ClinicalTrials.gov and when, results_due_date and days_late (an approximation: primary completion + 365 days), and whether the drug was ever approved by the FDA (get_fda_approvals) if the brief asks.
For trials the brief names, call get_trial_live to confirm the snapshot, and say if the live record differs. For trials outside the snapshot, get_trial_live is the only source: say so in notes.
Use get_snapshot_stats when a base rate would put the trial in context (for example the share of stopped trials with a blank reason).
