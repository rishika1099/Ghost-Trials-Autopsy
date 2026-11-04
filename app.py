"""Ghost Trials Autopsy: the web app.

    uv run app.py        then open http://localhost:8000

POST /chat     the Project 1 request and response shape: {message, session_id} -> {response, session_id, tool_calls}.
               Every tool call from every agent is in tool_calls, each with an `agent` field.
GET  /run      the same research, streamed as Server-Sent Events for the page's live trace.
GET  /health   200 and the snapshot date.
"""

import asyncio
import json
import os
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ghost import db
from ghost.pipeline import investigate

HERE = Path(__file__).parent
app = FastAPI(title="Ghost Trials Autopsy")

# session_id -> the question we asked a clarification about, so the user's reply can complete it.
pending_clarifications: dict[str, str] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: list[dict]


def with_clarification(session_id: str, message: str) -> str:
    """If the last answer in this session asked for clarification, treat this message as the reply to it."""
    earlier = pending_clarifications.pop(session_id, None)
    return f"{earlier}\nClarification from the user: {message}" if earlier else message


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


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    question = with_clarification(session_id, request.message)
    try:
        result = await investigate(question)
        response, tool_calls = result["markdown"], result["tool_calls"]
        if result["kind"] == "clarify":
            pending_clarifications[session_id] = question
    except Exception as e:
        # Auth, quota, a model that won't stop: show it in the chat, not as a 500.
        response, tool_calls = f"Research failed: {type(e).__name__}: {str(e)[:300]}", []
    return ChatResponse(response=response, session_id=session_id, tool_calls=tool_calls)


@app.get("/run")
async def run(question: str, session_id: str | None = None):
    """Research one question and stream what happens as Server-Sent Events."""
    session_id = session_id or str(uuid.uuid4())
    question = with_clarification(session_id, question)
    run_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: dict) -> None:
        queue.put_nowait(event)

    async def work():
        try:
            result = await investigate(question, emit=emit)
            if result["kind"] == "clarify":
                pending_clarifications[session_id] = question
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
