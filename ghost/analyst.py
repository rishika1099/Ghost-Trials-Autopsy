"""Ask the ledger: one quick agent that answers whole-snapshot questions with SQL (Text2SQL), for the Explore section.

The analyst writes and runs the SQL with the same read-only tools as the trials researcher. The table the page
shows is never copied from the model: the app reruns the analyst's final SELECT through the same guard and shows
those rows. Every number in the analyst's sentence is then checked against that table, and any number that isn't
there is flagged to the reader.
"""

import asyncio
import re
import time
from typing import Literal

from agents import Agent, MaxTurnsExceeded, Runner
from pydantic import BaseModel, Field

from ghost import config, db
from ghost.hooks import TraceHooks
from ghost.pipeline import SETTINGS, model, prompt
from ghost.state import RunState
from ghost.tools import find_discrepancies, get_enum_values, query_trials_sql

ANALYST_MAX_TURNS = 8
ANALYST_TIMEOUT_S = 90.0
MAX_QUESTION_CHARS = 500


class AnalystAnswer(BaseModel):
    sql: str = Field(description="The exact SELECT that produced the answer, or empty if the question is out of scope.")
    answer: str = Field(description="1 to 3 sentences using only numbers from the query result.")
    chart: Literal["bar", "none"] = "none"
    label_column: str = ""
    value_column: str = ""
    caveat: str = ""


def schema_text() -> str:
    """The tables, columns and enum values, in the prompt, so the analyst can write SQL on its first turn."""
    lines = []
    for t in db.mappings()["tables"]:
        lines.append(f"\nTable {t['table']}: {t['description']}")
        for c in t["columns"]:
            enum = f" Values: {', '.join(map(str, c['enum_values']))}." if c.get("enum_values") and len(c["enum_values"]) <= 12 else ""
            lines.append(f"- {c['name']} ({c['type']}): {c['description']}{enum}")
    return "\n".join(lines)


analyst = Agent(name="analyst", instructions=prompt("analyst") + "\n\nThe snapshot's tables (you do not need read_mappings):\n" + schema_text(),
                model=model(config.LEAD_MODEL), model_settings=SETTINGS,
                tools=[get_enum_values, query_trials_sql, find_discrepancies], output_type=AnalystAnswer)


DASH_RANGE = re.compile(r"(\d)\s*[\u2013\u2014]\s*(\d)")


def no_dashes(text: str) -> str:
    """The project's style rule, enforced on model output: no en or em dashes."""
    text = DASH_RANGE.sub(r"\1 to \2", text or "")
    return re.sub(r"\s*[\u2013\u2014]\s*", ", ", text)


async def run_analyst(state: RunState) -> AnalystAnswer:
    result = await Runner.run(analyst, state.question, context=state, hooks=TraceHooks(state, "analyst"), max_turns=ANALYST_MAX_TURNS)
    return result.final_output


NUMBER = re.compile(r"(?<![\w.\-])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w\-])")  # not the 19 in COVID-19


def _number_forms(value) -> set[str]:
    """How a table value may be written in a sentence: 2905, 2,905, 26.1, 26."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return set()
    forms = {f"{value:g}", f"{value:,.0f}" if float(value).is_integer() else f"{value:,}"}
    if isinstance(value, float):
        forms |= {f"{value:.1f}", f"{round(value):d}", f"{value:.0f}"}
    else:
        forms.add(str(value))
    return {f.replace(",", "") for f in forms}


def unverified_numbers(answer: str, rows: list[dict], sql: str) -> list[str]:
    """Numbers in the answer that appear neither in the result table nor in the SQL (a threshold such as 5,
    a year such as 2015). An empty list means every number checks out."""
    known = {f for row in rows for v in row.values() for f in _number_forms(v)}
    known |= {n.replace(",", "") for n in NUMBER.findall(sql)}
    known |= {str(len(rows))}
    words_ok = {"2", "3"}  # phase 2 and 3, named in the snapshot's scope
    out = []
    for match in NUMBER.findall(answer):
        plain = match.replace(",", "")
        if plain in known or plain in words_ok or re.fullmatch(r"20(1[5-9]|2[0-3])", plain):
            continue
        out.append(match)
    return out


def _plain(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return value


async def ask(question: str) -> dict:
    """Answer one question about the whole snapshot. Returns the answer, the SQL, the rerun table, checks and trace."""
    question = (question or "").strip()
    if not question:
        return {"ok": False, "answer": "Ask a question about the snapshot, for example: Which conditions have the most silent trials?"}
    if len(question) > MAX_QUESTION_CHARS:
        return {"ok": False, "answer": f"Please keep it under {MAX_QUESTION_CHARS} characters."}
    state = RunState(question=question)
    started = time.monotonic()
    try:
        out = await asyncio.wait_for(run_analyst(state), timeout=ANALYST_TIMEOUT_S)
    except (asyncio.TimeoutError, MaxTurnsExceeded):
        return {"ok": False, "answer": "That took too long to work out. Try a narrower question (one condition, sponsor or year).",
                "tool_calls": state.tool_calls, "elapsed_s": round(time.monotonic() - started, 1)}
    except Exception as e:
        return {"ok": False, "answer": f"The analyst failed: {type(e).__name__}: {str(e)[:200]}", "tool_calls": state.tool_calls,
                "elapsed_s": round(time.monotonic() - started, 1)}
    result = {"ok": True, "answer": no_dashes(out.answer.strip()), "sql": out.sql.strip(), "caveat": no_dashes(out.caveat.strip()), "columns": [], "rows": [],
              "truncated": False, "chart": "none", "unverified": [], "tool_calls": state.tool_calls, "snapshot_date": db.snapshot_date()}
    if result["sql"]:
        table = db.run_select(result["sql"], limit=50)
        if "error" in table:
            result.update(ok=False, sql_error=table["error"],
                          answer=f"{result['answer']} (The final query did not run again cleanly, so no table is shown: {table['error'][:160]})")
        else:
            rows = [{k: _plain(v) for k, v in row.items()} for row in table["rows"]]
            result.update(columns=table["columns"], rows=rows, truncated=table["truncated"])
            result["unverified"] = unverified_numbers(result["answer"], table["rows"], result["sql"])
            numeric = rows and out.value_column in table["columns"] and all(isinstance(r.get(out.value_column), (int, float)) for r in rows)
            if out.chart == "bar" and numeric and out.label_column in table["columns"] and len(rows) <= 25:
                result.update(chart="bar", label_column=out.label_column, value_column=out.value_column)
    result["elapsed_s"] = round(time.monotonic() - started, 1)
    return result
