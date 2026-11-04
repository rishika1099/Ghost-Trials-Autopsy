"""One request's state, shared by every agent and tool in it. The models never see it directly."""

import time
from dataclasses import dataclass, field
from typing import Callable

from ghost.config import REQUEST_BUDGET_S
from ghost.context_panel import AgentContexts
from ghost.evidence import EvidenceStore


@dataclass
class RunState:
    question: str
    emit: Callable[[dict], None] = lambda event: None
    store: EvidenceStore = field(default_factory=EvidenceStore)
    tool_calls: list[dict] = field(default_factory=list)  # every agent's calls, for /chat's tool_calls
    timings: list[dict] = field(default_factory=list)  # {agent, round, start, end}: proves researchers overlapped
    first_contexts: dict[str, dict] = field(default_factory=dict)  # each researcher's first model input: proves fresh contexts
    contexts: AgentContexts = field(default_factory=AgentContexts)  # every agent's message list, for the context panel
    rounds: int = 0
    notes: list[str] = field(default_factory=list)  # e.g. "budget reached: stopped after round 2"
    started: float = field(default_factory=time.monotonic)
    budget_s: float = REQUEST_BUDGET_S

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def remaining(self) -> float:
        return self.budget_s - self.elapsed()

    def record_call(self, agent: str, name: str, args: dict, result: str) -> None:
        call = {"name": name, "args": args, "result": result, "agent": agent}
        self.tool_calls.append(call)
        self.emit({"type": "tool", **call, "t": round(self.elapsed(), 2)})
