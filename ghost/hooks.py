"""Run hooks that turn what the agents do into the trace: tool calls (with an agent field) for /chat,
each researcher's first model input (to prove a fresh context), and every message list for the context panel."""

import json
import re

from agents import RunHooks

from ghost.context_panel import _plain, from_agents_sdk
from ghost.state import RunState

EVIDENCE_RE = re.compile(r'"evidence_ids?":\s*(\[[^\]]*\]|"[^"]+")')


def summarize(result) -> str:
    """A short summary of a tool result, so /chat responses stay small."""
    text = str(result)
    try:
        data = json.loads(text)
    except ValueError:
        return text[:200]
    if not isinstance(data, dict):
        return text[:200]
    if "error" in data:
        return f"error: {str(data['error'])[:180]}"
    for key in ("rows", "filings", "publications", "applications", "matches", "excerpts"):
        if key in data and isinstance(data[key], list):
            extra = f", {len(data.get('evidence_ids', []))} evidence ids" if data.get("evidence_ids") else ""
            note = f" ({data['note']})" if data.get("note") else ""
            return f"{len(data[key])} {key}{extra}{note}"[:240]
    if "record" in data:
        r = data["record"]
        return f"{r.get('nct_id')}: {r.get('overall_status')}, why_stopped={str(r.get('why_stopped'))[:80]!r}"
    if "abstract" in data:
        return f"PMID {data.get('pmid')}: {str(data.get('title'))[:120]}"
    if "overall" in data:
        return f"snapshot stats: {json.dumps(data['overall'], default=str)[:200]}"
    return text[:200]


class TraceHooks(RunHooks):
    def __init__(self, state: RunState, agent_name: str, context_key: str | None = None):
        self.state = state
        self.agent_name = agent_name
        self.key = context_key or agent_name
        self.evidence_seen: list[str] = []

    async def on_llm_start(self, context, agent, system_prompt, input_items):
        messages = from_agents_sdk(system_prompt, [_plain(i) for i in input_items])
        if self.key not in self.state.first_contexts:
            self.state.first_contexts[self.key] = {"agent": self.agent_name, "messages": messages}
        self.state.contexts.set(self.key, messages)
        self.state.emit({"type": "context", "agent": self.key})

    async def on_llm_end(self, context, agent, response):
        self.state.contexts.add(self.key, from_agents_sdk(None, [_plain(i) for i in response.output]))
        self.state.emit({"type": "context", "agent": self.key})

    async def on_tool_end(self, context, agent, tool, result):
        try:
            args = json.loads(getattr(context, "tool_arguments", None) or "{}")
        except ValueError:
            args = {"raw": getattr(context, "tool_arguments", "")}
        for match in EVIDENCE_RE.findall(str(result)):
            value = json.loads(match)
            self.evidence_seen.extend(value if isinstance(value, list) else [value])
        self.state.record_call(self.agent_name, tool.name, args, summarize(result))
