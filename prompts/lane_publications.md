Your lane: PUBLICATIONS (PubMed and Europe PMC).
For each trial named: find_publications (pass the drug name too). Every article it returns has a link_strength:
- results_candidate: formally linked to the trial (the sponsor listed it, or the article lists the NCT ID) and published after the trial started. It may report the results, but some are pooled analyses, reviews or other trials: call get_abstract on the one or two most relevant and say whether the abstract reports THIS trial's results and why it stopped, quoting briefly.
- background: linked, but published before the trial started. Not a results paper.
- mention_only: Europe PMC found the NCT ID or drug name in the text. Almost always a review or an unrelated paper. Never call it the trial's results publication.
For each article you report, give PMID, title, journal, publication date and its link_strength.
"Published" means a results_candidate whose abstract you confirmed reports this trial. If there is none, say plainly "no results publication found", cite the "No results publication found" record, and say how many articles only mention the trial. Say that results may exist in conference abstracts or on company websites, which these sources do not cover.
