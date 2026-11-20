"""The web/API process: the chat stream, job status and progress, retry, and booking.

The frontend talks only to these endpoints. It never touches featherweight's run log, queue or agent classes.
The API has no worker in it: it submits jobs (inside the chat agent's tool), follows them and reads results.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel

from concierge import deps
from concierge.chat import Concierge
from concierge.config import DATABASE_URL, STATIC_DIR
from concierge.domain import Database, PgAvailability, PgCatalog, Repository, SearchRequest, SlotTaken
from concierge.fw_adapters import PostgresQueue, PostgresResultStore
from concierge.booking_prep import PrepareInput, prepare_booking
from concierge.research import research_providers
from concierge.telemetry import setup as setup_telemetry
from featherweight import AgentRunner, BadRequest, JobClient, PostgresDatabase, RunStatus
from featherweight.adapters import agui


@asynccontextmanager
async def lifespan(app: FastAPI):
    observers = setup_telemetry("concierge-api")  # OpenTelemetry spans for jobs, agents, model calls and tools
    async with Database(DATABASE_URL) as app_db, PostgresDatabase(DATABASE_URL) as db:  # the app's data / featherweight's run log
        results = PostgresResultStore(app_db.pool)
        deps.repo, deps.catalog, deps.availability = Repository(app_db), PgCatalog(app_db), PgAvailability(app_db)
        deps.client = JobClient(db, PostgresQueue(app_db.pool, db), results, observers=observers)
        # background=client: the chat agent's `start_background` submits jobs to the queue, for a worker to run
        async with AgentRunner(db, results=results, observers=observers, background=deps.client) as deps.runner:
            yield


app = FastAPI(title="fw-concierge (simulated)", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app, excluded_urls="/api/health", exclude_spans=["send", "receive"])


@app.exception_handler(BadRequest)
async def bad_request(request: Request, exc: BadRequest):
    return JSONResponse({"error": str(exc)}, status_code=422)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/agui")
async def agui_chat(request: Request):
    """The chat. The client sends the whole conversation; featherweight keeps none."""
    run = deps.runner.stream(Concierge, agui.parse_request(await request.body()))
    return StreamingResponse(agui.encode(run), headers=agui.HEADERS, media_type=agui.CONTENT_TYPE)


# ------------------------------------------------------------------------------------------------------------------ jobs

STATES = {  # featherweight's job status -> the lifecycle the UI shows
    RunStatus.INIT: "queued", RunStatus.RUNNING: "running", RunStatus.SUCCESS: "completed",
    RunStatus.FAILED: "failed", RunStatus.CANCELLED: "cancelled",
}


async def job_view(job_id: str) -> dict:
    """Everything the UI needs to show a job again after a refresh. Built from the app's tables and the run log."""
    try:
        row = await deps.client.status(job_id)
    except Exception:
        raise HTTPException(404, "No such job")
    criteria = await deps.repo.get_request(job_id)
    state = STATES[row.status]
    booking = await deps.repo.booking_for_job(job_id)
    return {
        "job_id": job_id,
        "state": state,
        "error": row.error_type,
        "criteria": criteria,
        "result": await deps.repo.get_result(job_id) if state == "completed" else None,
        "booking": await booking_view(booking) if booking else None,
        "progress": [{"seq": p["seq"], "message": p["message"]} for p in await deps.repo.progress(job_id)],
    }


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    return await job_view(job_id)


def sse(event: str, data: dict, id: int | None = None) -> str:
    return (f"id: {id}\n" if id is not None else "") + f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/api/jobs/{job_id}/stream")
async def job_stream(job_id: str, request: Request):
    """Progress lines and state changes of ONE job (research or preparation), as server-sent events. A reconnecting browser resumes from Last-Event-ID."""
    after = int(request.headers.get("last-event-id", 0))
    try:
        await deps.client.status(job_id)  # 404 early
    except Exception:
        raise HTTPException(404, "No such job")

    async def events():
        nonlocal after
        last = None
        while True:
            state = STATES[(await deps.client.status(job_id)).status]  # read the state first, then the progress it explains
            for p in await deps.repo.progress(job_id, after):
                after = p["seq"]
                yield sse("progress", {"job_id": job_id, "message": p["message"]}, id=after)
            if state != last:
                last = state
                yield sse("state", {"job_id": job_id, "state": state})
            if state in ("completed", "failed", "cancelled") or await request.is_disconnected():
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str):
    """Retry a failed research: the same request, submitted as a new job."""
    view = await job_view(job_id)
    if view["state"] != "failed" or view["criteria"] is None:
        raise HTTPException(409, "Only a failed job can be retried")
    return {"job_id": await deps.client.submit(research_providers, SearchRequest.model_validate(view["criteria"]))}


class OutageIn(BaseModel):
    enabled: bool


# ------------------------------------------------------------------------------------------ prepare booking (resumable job)


class PrepareIn(BaseModel):
    job_id: str  # the research job whose shortlist the user picked from
    provider_id: str
    slot_id: str


@app.post("/api/preparations")
async def start_preparation(body: PrepareIn):
    """The "Prepare booking" button: submit the two-agent job. `resumable=True` keeps its steps, so a failure can be resumed."""
    if await deps.repo.get_request(body.job_id) is None:
        raise HTTPException(404, "No such research")
    prepare = PrepareInput(research_job_id=body.job_id, provider_id=body.provider_id, slot_id=body.slot_id)
    return {"job_id": await deps.client.submit(prepare_booking, prepare, resumable=True)}


@app.get("/api/preparations/{job_id}")
async def get_preparation(job_id: str):
    try:
        row = await deps.client.status(job_id)
    except Exception:
        raise HTTPException(404, "No such job")
    prep = await deps.repo.get_preparation(job_id)
    return {
        "job_id": job_id,
        "state": STATES[row.status],
        "error": row.error_type,
        "result": prep["result"] if prep else None,
        "progress": [{"seq": p["seq"], "message": p["message"]} for p in await deps.repo.progress(job_id)],
    }


@app.post("/api/preparations/{job_id}/retry")
async def retry_preparation(job_id: str):
    """Resume a failed preparation as a new job: the steps that succeeded (the first agent) are reused, the rest runs."""
    prep = await deps.repo.get_preparation(job_id)
    if prep is None or STATES[(await deps.client.status(job_id)).status] != "failed":
        raise HTTPException(409, "Only a failed preparation can be retried")
    again = PrepareInput(research_job_id=prep["research_job_id"], provider_id=prep["provider_id"], slot_id=prep["slot_id"])
    return {"job_id": await deps.client.submit(prepare_booking, again, resumable=True, resume_from=job_id)}


@app.get("/api/demo/outage")
async def get_outage():
    return {"enabled": await deps.repo.outage()}


@app.put("/api/demo/outage")
async def set_outage(body: OutageIn):
    """Demo switch: while on, a booking preparation fails after its first agent, so it can be retried (resumed)."""
    await deps.repo.set_outage(body.enabled)
    return body


# --------------------------------------------------------------------------------------------------------------- bookings


class BookingIn(BaseModel):
    job_id: str
    provider_id: str
    slot_id: str
    idempotency_key: str  # the same key always returns the same booking


async def booking_view(booking: dict) -> dict:
    provider, slot = await deps.catalog.get(booking["provider_id"]), await deps.availability.get(booking["slot_id"])
    return {
        "id": booking["id"],
        "status": "confirmed",
        "simulated": True,  # nothing here is real: every provider and appointment is fictional
        "provider": provider.model_dump(mode="json") if provider else None,
        "slot": slot.model_dump(mode="json") if slot else None,
        "job_id": booking["job_id"],
        "created_at": booking["created_at"].isoformat(),
    }


@app.post("/api/bookings")
async def create_booking(body: BookingIn):
    """The only place a booking is created, and only when the user explicitly confirms. Plain application code: no agent."""
    if await deps.repo.get_request(body.job_id) is None:
        raise HTTPException(404, "No such job")
    try:
        booking, created = await deps.repo.book(
            idempotency_key=body.idempotency_key, job_id=body.job_id,
            provider_id=body.provider_id, slot_id=body.slot_id,
        )
    except SlotTaken as exc:
        raise HTTPException(409, str(exc))
    return JSONResponse(await booking_view(booking), status_code=201 if created else 200)


@app.get("/api/bookings/{booking_id}")
async def get_booking(booking_id: str):
    booking = await deps.repo.get_booking(booking_id)
    if booking is None:
        raise HTTPException(404, "No such booking")
    return await booking_view(booking)


if Path(STATIC_DIR).is_dir():  # last, so the API routes above win
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
