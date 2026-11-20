"""The web/API process: the AG-UI chat stream, job status and progress, retry, and booking.

The frontend talks only to these endpoints. It never touches Featherweight's run log, queue or agent classes.
"""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from ag_ui.core import (
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.encoder import EventEncoder
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel

from concierge.agents import IntakeAgent, IntakeInput
from concierge.config import STATIC_DIR
from concierge.domain import SlotTaken
from concierge.research import ResearchJobInput, research_providers
from concierge.services import runtime
from featherweight import BadRequest, RunStatus
from featherweight.adapters import agui

STATES = {  # Featherweight's job status -> the lifecycle the UI shows
    RunStatus.INIT: "queued", RunStatus.RUNNING: "running", RunStatus.SUCCESS: "completed",
    RunStatus.FAILED: "failed", RunStatus.CANCELLED: "cancelled",
}
FINAL = {"completed", "failed", "cancelled"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with runtime("concierge-api") as rt:
        app.state.rt = rt
        yield


app = FastAPI(title="Appointment Concierge (simulated)", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app, excluded_urls="/api/health", exclude_spans=["send", "receive"])


@app.exception_handler(BadRequest)
async def bad_request(request: Request, exc: BadRequest):
    return JSONResponse({"error": str(exc)}, status_code=422)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ------------------------------------------------------------------------------------------------------------------ chat


def conversation_text(chat_input) -> str:
    """The user's request and any follow-up, as plain lines. A finished research (a tool result) starts a new request."""
    messages = chat_input.messages
    last_tool = max((i for i, m in enumerate(messages) if m.role == "tool"), default=-1)
    lines = [f"{m.role}: {m.content}" for m in messages[last_tool + 1 :] if m.role in ("user", "assistant") and m.content]
    return "\n".join(lines)


def text_events(message_id: str, text: str):
    yield TextMessageStartEvent(message_id=message_id)
    words = text.split(" ")
    for i in range(0, len(words), 3):
        yield TextMessageContentEvent(message_id=message_id, delta=" ".join(words[i : i + 3]) + (" " if i + 3 < len(words) else ""))
    yield TextMessageEndEvent(message_id=message_id)


def describe(request) -> str:
    where = request.location if request.location == "Marlow Bay" else f"{request.location}, Marlow Bay"
    dates = f"{request.date_from:%a %d %b}" + (f" to {request.date_to:%a %d %b}" if request.date_to != request.date_from else "")
    prefs = f" Preferences: {', '.join(request.preferences)}." if request.preferences else ""
    return f"Here's what I understood: {request.service_category} in {where}, {dates}.{prefs} I'm starting the research now."


@app.post("/api/agui")
async def chat(request: Request):
    """AG-UI chat. Runs the typed intake agent, then either asks one focused question or submits a research job."""
    rt = request.app.state.rt
    chat_input = agui.parse_request(await request.body())
    outage = request.headers.get("x-demo-outage") == "1"  # demo: simulate provider outage
    encoder, run_id = EventEncoder(), uuid.uuid4().hex
    thread_id = chat_input.thread_id or uuid.uuid4().hex

    async def stream():
        yield encoder.encode(RunStartedEvent(thread_id=thread_id, run_id=run_id))
        intake = await rt.runner.run(IntakeAgent, IntakeInput(conversation=conversation_text(chat_input), today=date.today()))
        if intake.status != RunStatus.SUCCESS:
            yield encoder.encode(RunErrorEvent(message="I couldn't understand that request. Could you rephrase it?"))
            return
        message_id = uuid.uuid4().hex
        if intake.output.open_questions:  # a missing value is asked for, never invented
            for event in text_events(message_id, intake.output.open_questions[0]):
                yield encoder.encode(event)
        else:
            criteria = intake.output.to_request()
            for event in text_events(message_id, describe(criteria)):
                yield encoder.encode(event)
            request_id = await rt.repo.create_request(criteria)
            job_id = await rt.client.submit(
                research_providers,
                ResearchJobInput(request_id=request_id, request=criteria, simulate_outage=outage),
                resumable=True,  # keeps step outputs, so a failed job can be resumed
            )
            await rt.repo.attach_job(request_id, job_id)
            await rt.repo.add_progress(job_id, "Research job queued")
            call_id = uuid.uuid4().hex
            payload = {"job_id": job_id, "request_id": request_id, "criteria": criteria.model_dump(mode="json")}
            yield encoder.encode(ToolCallStartEvent(tool_call_id=call_id, tool_call_name="submit_research", parent_message_id=message_id))
            yield encoder.encode(ToolCallArgsEvent(tool_call_id=call_id, delta=json.dumps(payload["criteria"])))
            yield encoder.encode(ToolCallEndEvent(tool_call_id=call_id))
            yield encoder.encode(ToolCallResultEvent(message_id=uuid.uuid4().hex, tool_call_id=call_id, content=json.dumps(payload)))
        yield encoder.encode(RunFinishedEvent(thread_id=thread_id, run_id=run_id))

    return StreamingResponse(stream(), media_type=agui.CONTENT_TYPE, headers=agui.HEADERS)


# ------------------------------------------------------------------------------------------------------------------ jobs


async def job_view(rt, job_id: str) -> dict:
    try:
        row = await rt.client.status(job_id)
    except Exception:
        raise HTTPException(404, "No such job")
    req = await rt.repo.request_for_job(job_id)
    state = STATES[row.status]
    booking = await rt.repo.booking_for_job(job_id)
    return {
        "job_id": job_id,
        "state": state,
        "error": row.error_type,
        "request_id": req["id"] if req else None,
        "criteria": req["criteria"] if req else None,
        "result": await rt.repo.get_result(job_id) if state == "completed" else None,
        "booking": await booking_view(rt, booking) if booking else None,
        "progress": [{"seq": p["seq"], "message": p["message"]} for p in await rt.repo.progress(job_id)],
    }


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    return await job_view(request.app.state.rt, job_id)


def sse(event: str, data: dict, id: int | None = None) -> str:
    return (f"id: {id}\n" if id is not None else "") + f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/api/jobs/{job_id}/stream")
async def job_stream(job_id: str, request: Request):
    """Progress and state changes of one job as server-sent events. A reconnecting browser resumes from Last-Event-ID."""
    rt = request.app.state.rt
    after = int(request.headers.get("last-event-id", 0))
    await job_view(rt, job_id)  # 404 early

    async def events():
        nonlocal after
        last = None
        while True:
            state = STATES[(await rt.client.status(job_id)).status]  # read the state first, then the progress it explains
            for p in await rt.repo.progress(job_id, after):
                after = p["seq"]
                yield sse("progress", {"job_id": job_id, "message": p["message"]}, id=after)
            if state != last:
                last = state
                yield sse("state", {"job_id": job_id, "state": state})
            if state in FINAL:
                return
            if await request.is_disconnected():
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str, request: Request):
    """Resume a failed job as a new one: provider checks that already succeeded are reused, only the failed ones rerun."""
    rt = request.app.state.rt
    view = await job_view(rt, job_id)
    if view["state"] != "failed":
        raise HTTPException(409, "Only a failed job can be retried")
    criteria = view["criteria"]
    from concierge.domain import SearchRequest

    search = SearchRequest.model_validate(criteria)
    request_id = await rt.repo.create_request(search)
    new_id = await rt.client.submit(
        research_providers, ResearchJobInput(request_id=request_id, request=search), resumable=True, resume_from=job_id
    )
    await rt.repo.attach_job(request_id, new_id)
    await rt.repo.add_progress(new_id, f"Retrying job {job_id}: finished provider checks will be reused")
    return {"job_id": new_id, "request_id": request_id, "criteria": criteria}


# --------------------------------------------------------------------------------------------------------------- bookings


class BookingIn(BaseModel):
    job_id: str
    provider_id: str
    slot_id: str
    idempotency_key: str  # the same key always returns the same booking


async def booking_view(rt, booking: dict) -> dict:
    provider = await rt.catalog.get(booking["provider_id"])
    slot = await rt.availability.get(booking["slot_id"])
    return {
        "id": booking["id"],
        "status": "confirmed",
        "simulated": True,  # nothing here is real: all providers and appointments are fictional
        "provider": provider.model_dump(mode="json") if provider else None,
        "slot": slot.model_dump(mode="json") if slot else None,
        "job_id": booking["job_id"],
        "created_at": booking["created_at"].isoformat(),
    }


@app.post("/api/bookings")
async def create_booking(body: BookingIn, request: Request):
    """The only place a booking is created, and only on an explicit confirmation. A plain application operation: no agent."""
    rt = request.app.state.rt
    req = await rt.repo.request_for_job(body.job_id)
    if req is None:
        raise HTTPException(404, "No such job")
    try:
        booking, created = await rt.repo.book(
            idempotency_key=body.idempotency_key, request_id=req["id"], job_id=body.job_id,
            provider_id=body.provider_id, slot_id=body.slot_id,
        )
    except SlotTaken as exc:
        raise HTTPException(409, str(exc))
    return JSONResponse(await booking_view(rt, booking), status_code=201 if created else 200)


@app.get("/api/bookings/{booking_id}")
async def get_booking(booking_id: str, request: Request):
    rt = request.app.state.rt
    booking = await rt.repo.get_booking(booking_id)
    if booking is None:
        raise HTTPException(404, "No such booking")
    return await booking_view(rt, booking)


if Path(STATIC_DIR).is_dir():  # last: the API routes above win
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
