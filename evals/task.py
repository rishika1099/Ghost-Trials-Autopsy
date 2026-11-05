"""Inspect evals for Ghost Trials Autopsy (adapted from the nyc-311-agent starter).

    uv run inspect eval evals/task.py@gate     # the Lead's clarify / refuse / research gate (fast)
    uv run inspect eval evals/task.py@facts    # full research runs, checked against gold SQL answers (slow)
    uv run inspect view

Scorers: deterministic checks (gate decision, citations resolve, limitations section present) and a
model judge with a golden reference (model_graded_fact against the gold_sql target).
"""

import os
import sys
from pathlib import Path

import google.auth
from inspect_ai import Task, task
from inspect_ai.dataset import json_dataset
from inspect_ai.model import ModelOutput
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, model_graded_fact, scorer, stderr
from inspect_ai.solver import Generate, TaskState, solver

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ghost import pipeline  # noqa: E402
from ghost.state import RunState  # noqa: E402

HERE = Path(__file__).resolve().parent
# Inspect's Vertex provider reads the project from the environment: the agent's VERTEX_PROJECT, else gcloud's.
if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
    os.environ["GOOGLE_CLOUD_PROJECT"] = os.environ.get("VERTEX_PROJECT") or google.auth.default()[1] or ""
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
JUDGE = "google/vertex/gemini-3.5-flash"


@solver
def lead_gate():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        plan = await pipeline.run_lead_plan(RunState(question=state.input_text))
        state.metadata["decision"] = plan.decision
        state.output = ModelOutput.from_content(model="ghost-lead", content=f"{plan.decision}: {plan.message or plan.plan}")
        return state

    return solve


@solver
def ghost_agent():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        result = await pipeline.investigate(state.input_text)
        state.metadata.update(decision=result["kind"], sources=result.get("sources", []), checker=result.get("checker"))
        state.output = ModelOutput.from_content(model="ghost-autopsy", content=result["markdown"])
        return state

    return solve


@scorer(metrics=[accuracy(), stderr()])
def gate_decision():
    async def score(state: TaskState, target: Target) -> Score:
        expected = state.metadata.get("expected", target.text)
        got = "research" if state.metadata.get("decision") == "report" else state.metadata.get("decision")
        return Score(value=CORRECT if got == expected else INCORRECT, answer=str(got), explanation=f"expected {expected}")

    return score


@scorer(metrics={"cited": [accuracy()], "has_limits": [accuracy()]})
def report_checks():
    async def score(state: TaskState, target: Target) -> Score:
        text = state.output.completion
        sources = state.metadata.get("sources") or []
        ok = lambda passed: CORRECT if passed else INCORRECT  # noqa: E731
        return Score(value={"cited": ok(bool(sources) and "[1]" in text),
                            "has_limits": ok("## What the data can't tell us" in text)}, answer=text[:500])

    return score


@task
def gate() -> Task:
    return Task(dataset=json_dataset(str(HERE / "gate.jsonl")), solver=lead_gate(), scorer=gate_decision(), model=JUDGE)


@task
def facts() -> Task:
    return Task(dataset=json_dataset(str(HERE / "facts.jsonl")), solver=ghost_agent(),
                scorer=[model_graded_fact(model=JUDGE), report_checks(), gate_decision()], model=JUDGE)
