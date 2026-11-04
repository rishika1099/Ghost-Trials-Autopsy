"""The evidence store: every record any tool returned in this run, keyed by a stable evidence_id.

The Writer may only cite ids in here, and the Citation Checker compares each cited sentence to the
record behind it. ids look like ctgov:NCT01234567, sec:0001193125-21-123456, pubmed:34567890,
fda:NDA021234, cik:0000320193, snapshot:stats or sql:1a2b3c4d.
"""

import json
import threading
from dataclasses import dataclass, field

SOURCE_TYPES = {
    "ctgov": "ClinicalTrials.gov registry record",
    "sec": "SEC EDGAR filing",
    "cik": "SEC company record",
    "pubmed": "PubMed article",
    "fda": "Drugs@FDA application",
    "snapshot": "Ghost Trials snapshot statistic",
    "sql": "Ghost Trials snapshot query",
}


@dataclass
class Evidence:
    evidence_id: str
    title: str
    source_url: str
    data: dict

    @property
    def source_type(self) -> str:
        return SOURCE_TYPES.get(self.evidence_id.split(":", 1)[0], "Source")

    def as_dict(self) -> dict:
        return {"evidence_id": self.evidence_id, "source_type": self.source_type, "title": self.title,
                "source_url": self.source_url, "data": self.data}


@dataclass
class EvidenceStore:
    records: dict[str, Evidence] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, evidence_id: str, title: str, source_url: str, data: dict) -> str:
        """Add a record, or merge new fields into the one already stored (a live refresh, an abstract)."""
        with self._lock:
            if evidence_id in self.records:
                old = self.records[evidence_id]
                old.data = {**old.data, **{k: v for k, v in data.items() if v not in (None, "", [])}}
                old.title = old.title or title
                old.source_url = old.source_url or source_url
            else:
                self.records[evidence_id] = Evidence(evidence_id, title, source_url, data)
        return evidence_id

    def __contains__(self, evidence_id: str) -> bool:
        return evidence_id in self.records

    def get(self, evidence_id: str) -> Evidence | None:
        return self.records.get(evidence_id)

    def compact(self, ids: list[str] | None = None, max_chars: int = 1500) -> str:
        """The records as JSON lines for a prompt, each trimmed so one long filing can't crowd the rest."""
        lines = []
        for evidence_id in ids if ids is not None else list(self.records):
            record = self.records.get(evidence_id)
            if record:
                text = json.dumps(record.as_dict(), default=str)
                lines.append(text if len(text) <= max_chars else text[:max_chars] + '..."}')
        return "\n".join(lines)
