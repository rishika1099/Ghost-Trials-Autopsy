"""Ghost Trials Autopsy: the web app.

    uv run app.py        then open http://localhost:8000

POST /chat     the Project 1 request and response shape: {message, session_id} -> {response, session_id, tool_calls}.
               Every tool call from every agent is in tool_calls, each with an `agent` field.
GET  /run      the same research, streamed as Server-Sent Events for the page's live trace.
GET  /health   200 and the snapshot date.
GET  /api/ledger (with the sponsor leaderboard), /api/differ, /api/sponsors?q=, /api/sponsor?name=
               instant views of the snapshot for the page's Explore section (SQL only, no model calls).
POST /api/ask  "Ask the ledger": one analyst agent answers a whole-snapshot question with SQL; the app reruns its query.
"""

import asyncio
import json
import os
import time
import uuid
from functools import lru_cache
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ghost import analyst, db, explore
from ghost.pipeline import investigate

HERE = Path(__file__).parent
app = FastAPI(title="Ghost Trials Autopsy")

# session_id -> (the question we asked a clarification about, when). The user's reply completes it.
# Entries expire after CLARIFY_TTL_S, and the map never holds more than CLARIFY_MAX entries.
CLARIFY_TTL_S = 30 * 60
CLARIFY_MAX = 500
pending_clarifications: dict[str, tuple[str, float]] = {}


def remember_clarification(session_id: str, question: str) -> None:
    now = time.monotonic()
    for key in [k for k, (_, at) in pending_clarifications.items() if now - at > CLARIFY_TTL_S]:
        del pending_clarifications[key]
    while len(pending_clarifications) >= CLARIFY_MAX:
        del pending_clarifications[next(iter(pending_clarifications))]  # oldest first
    pending_clarifications[session_id] = (question, now)


# Each investigation spends model credits, and the site is public. A few per visitor per window is plenty for
# grading and peer review; past that, the visitor is asked to wait. Per instance, in memory.
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", 12))  # investigations (/chat, /run) per visitor per window
ASK_RATE_LIMIT = int(os.environ.get("ASK_RATE_LIMIT", 30))  # /api/ask questions per visitor per window
RATE_WINDOW_S = float(os.environ.get("RATE_WINDOW_S", 600))
_hits: dict[tuple[str, str], list[float]] = {}


def visitor(request: Request) -> str:
    # Cloud Run puts the caller's address first in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def rate_limited(request: Request, bucket: str, limit: int) -> float | None:
    """None if this call is allowed (and counts it), else the seconds until the visitor may try again."""
    if limit <= 0:
        return None
    now = time.monotonic()
    key = (bucket, visitor(request))
    recent = [t for t in _hits.get(key, []) if now - t < RATE_WINDOW_S]
    if len(recent) >= limit:
        _hits[key] = recent
        return round(RATE_WINDOW_S - (now - recent[0]))
    recent.append(now)
    _hits[key] = recent
    if len(_hits) > 5000:  # forget visitors with no recent calls
        for k in [k for k, v in _hits.items() if not v or now - v[-1] >= RATE_WINDOW_S]:
            del _hits[k]
    return None


def limit_message(wait_s: float, limit: int) -> str:
    return (f"This site allows {limit} requests per visitor every {int(RATE_WINDOW_S // 60)} minutes, because each one spends "
            f"model credits. Please try again in about {max(1, round(wait_s / 60))} minutes. The ghost ledger's instant views "
            f"(no AI) still work in the meantime.")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: list[dict]


def with_clarification(session_id: str, message: str) -> str:
    """If the last answer in this session asked for clarification, treat this message as the reply to it."""
    entry = pending_clarifications.pop(session_id, None)
    if entry is None or time.monotonic() - entry[1] > CLARIFY_TTL_S:
        return message
    return f"{entry[0]}\nClarification from the user: {message}"


@app.get("/")
def index():
    # no-cache: browsers otherwise keep serving an old page after a redeploy
    return FileResponse(HERE / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health():
    return {"status": "ok", "snapshot_date": db.snapshot_date()}


@app.get("/api/meta")
def meta():
    """Snapshot date and row counts for the page header."""
    try:
        tables = db.run_select("SELECT table_name, row_count, built_at, scope FROM snapshot_meta").get("rows", [])
    except db.SnapshotMissing:
        tables = []
    return {"snapshot_date": db.snapshot_date(), "tables": tables}


# The snapshot is read-only, so the whole-snapshot views are computed once per process.
@lru_cache(maxsize=1)
def _ledger():
    return {**explore.ledger(), "leaderboard": explore.leaderboard()}


@lru_cache(maxsize=1)
def _differ():
    return explore.differ_wall()


def _snapshot_or_503(fn, *args):
    try:
        return fn(*args)
    except db.SnapshotMissing as e:
        raise HTTPException(503, str(e))


@app.get("/api/ledger")
def api_ledger():
    return _snapshot_or_503(_ledger)


@app.get("/api/differ")
def api_differ():
    return _snapshot_or_503(_differ)


@app.get("/api/sponsors")
def api_sponsors(q: str = ""):
    return {"sponsors": _snapshot_or_503(explore.sponsor_search, q[:120])}


@app.get("/api/sponsor")
def api_sponsor(name: str):
    card = _snapshot_or_503(explore.sponsor_card, name[:200])
    if card is None:
        raise HTTPException(404, f"No sponsor in the snapshot matches {name[:80]!r}.")
    return card


class AskRequest(BaseModel):
    question: str


@app.post("/api/ask")
async def api_ask(body: AskRequest, request: Request):
    wait = rate_limited(request, "ask", ASK_RATE_LIMIT)
    if wait is not None:
        return JSONResponse({"ok": False, "answer": limit_message(wait, ASK_RATE_LIMIT), "rate_limited": True}, status_code=429)
    return await analyst.ask(body.question)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http: Request):
    session_id = request.session_id or str(uuid.uuid4())
    wait = rate_limited(http, "research", RATE_LIMIT)
    if wait is not None:  # same response shape, with a 429 status
        body = ChatResponse(response=limit_message(wait, RATE_LIMIT), session_id=session_id, tool_calls=[])
        return JSONResponse(body.model_dump(), status_code=429)
    question = with_clarification(session_id, request.message)
    try:
        result = await investigate(question)
        response, tool_calls = result["markdown"], result["tool_calls"]
        if result["kind"] == "clarify":
            remember_clarification(session_id, question)
    except Exception as e:
        # Auth, quota, a model that won't stop: show it in the chat, not as a 500.
        response, tool_calls = f"Research failed: {type(e).__name__}: {str(e)[:300]}", []
    return ChatResponse(response=response, session_id=session_id, tool_calls=tool_calls)


@app.get("/run")
async def run(http: Request, question: str, session_id: str | None = None):
    """Research one question and stream what happens as Server-Sent Events."""
    session_id = session_id or str(uuid.uuid4())
    wait = rate_limited(http, "research", RATE_LIMIT)
    if wait is not None:
        message = json.dumps({"type": "error", "message": limit_message(wait, RATE_LIMIT)})

        async def limited():
            yield f"data: {message}\n\n"

        return StreamingResponse(limited(), media_type="text/event-stream")
    question = with_clarification(session_id, question)
    run_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: dict) -> None:
        queue.put_nowait(event)

    async def work():
        try:
            result = await investigate(question, emit=emit)
            if result["kind"] == "clarify":
                remember_clarification(session_id, question)
            result.pop("findings", None)
            queue.put_nowait({"type": "done", "session_id": session_id, **result})
        except Exception as e:
            queue.put_nowait({"type": "error", "message": f"{type(e).__name__}: {str(e)[:500]}"})

    task = asyncio.create_task(work())

    async def events():
        try:
            yield f"data: {json.dumps({'type': 'start', 'run_id': run_id, 'session_id': session_id})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # proxies close idle streams
                    continue
                if event.get("type") == "context":
                    continue  # the page doesn't need every message-list change
                yield f"data: {json.dumps(event, default=str)}\n\n"
                if event["type"] in ("done", "error"):
                    break
        finally:
            task.cancel()  # the page closed the stream: stop spending tokens

    return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
