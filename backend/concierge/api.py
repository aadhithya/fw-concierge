"""The web/API process: the chat stream, job status and progress, retry, and booking.

The frontend talks only to these endpoints. It never touches featherweight's run log, queue or agent classes.
The API has no worker in it: it submits jobs (inside the chat agent's tool), follows them and reads results.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from featherweight import AgentRunner, AttachmentLimitError, BadRequest, PostgresDatabase, Status
from featherweight.adapters import agui
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from concierge import deps
from concierge.booking_prep import PrepareInput, prepare_booking
from concierge.chat import Concierge
from concierge.client import ControlledJobClient, provider_sleep
from concierge.config import DATABASE_URL, STATIC_DIR
from concierge.domain import Database, PgAvailability, PgCatalog, Repository, SearchRequest, SlotTaken
from concierge.fw_adapters import PostgresQueue, PostgresResultStore
from concierge.research import Researcher, ResearchInput
from concierge.schemas import BookingIn, PrepareIn, RetryPreparationIn, RetryResearchIn
from concierge.telemetry import setup as setup_telemetry
from concierge.wake import FINAL, delivered, noting_delivered, wake_text


@asynccontextmanager
async def lifespan(app: FastAPI):
    observers = setup_telemetry("concierge-api")  # OpenTelemetry spans for jobs, agents, model calls and tools
    async with Database(DATABASE_URL) as app_db, PostgresDatabase(DATABASE_URL) as db:  # the app's data / featherweight's run log
        results = PostgresResultStore(app_db.pool)
        deps.repo, deps.catalog, deps.availability = Repository(app_db), PgCatalog(app_db), PgAvailability(app_db)
        deps.client = ControlledJobClient(db, PostgresQueue(app_db.pool, db), results, observers=observers)
        # background=client: the chat agent's `start_background` submits jobs to the queue, for a worker to run
        async with AgentRunner(db, results=results, observers=observers, background=deps.client) as deps.runner:
            yield


app = FastAPI(title="fw-concierge (simulated)", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app, excluded_urls="/api/health", exclude_spans=["send", "receive"])


@app.exception_handler(AttachmentLimitError)
async def attachment_refused(request: Request, exc: AttachmentLimitError):
    """A chat message with a file: the concierge takes text only. 413, as featherweight's guide suggests."""
    return JSONResponse({"error": str(exc)}, status_code=413)


@app.exception_handler(BadRequest)
async def bad_request(request: Request, exc: BadRequest):
    """A request body featherweight cannot read as a chat request (for example a system message) is answered with 422 and the reason."""
    return JSONResponse({"error": str(exc)}, status_code=422)


@app.get("/api/health")
async def health():
    """Liveness check, used by Docker Compose to wait until the API is up."""
    return {"status": "ok"}


@app.post("/api/agui")
async def agui_chat(request: Request):
    """POST /api/agui: one chat turn, streamed as AG-UI events.

    The browser sends the whole conversation (featherweight keeps none); `agui.parse_request` reads it, `runner.stream` runs the
    concierge agent, and `agui.encode` streams its words and events back. When the chat starts the research (a background job),
    the stream carries a `background_started` event with the job id. The `x-provider-sleep` header is a demo control (see below).
    """
    sleep = request.headers.get("x-provider-sleep")  # demo control: how long the mock provider service takes
    provider_sleep.set(min(max(float(sleep), 0), 20) if sleep else None)
    run = deps.runner.stream(Concierge, agui.parse_request(await request.body()))
    # noting_delivered: remembers a research result that this turn already received, so the chat is not woken for it (wake.py)
    stream = noting_delivered(run, agui.encode(run))
    return StreamingResponse(stream, headers=agui.HEADERS, media_type=agui.CONTENT_TYPE)


# ------------------------------------------------------------------------------------------------------------------ jobs

STATES = {  # featherweight's job status -> the lifecycle the UI shows
    Status.INIT: "queued",
    Status.RUNNING: "running",
    Status.SUCCESS: "completed",
    Status.FAILED: "failed",
    Status.CANCELLED: "cancelled",
}


async def research_result(job_id: str) -> dict | None:
    """What the research agent returned, read from the result store (featherweight's `client.result`)."""
    result = await deps.client.result(Researcher, job_id)
    return result.model_dump(mode="json", exclude={"open_questions"}) if result else None


async def job_view(job_id: str) -> dict:
    """Everything the UI needs to show a job again after a refresh. Built from the app's tables and the run log."""
    try:
        row = await deps.client.status(job_id)
    except Exception:
        raise HTTPException(404, "No such job") from None
    criteria = await deps.repo.get_request(job_id)
    state = STATES[row.status]
    booking = await deps.repo.booking_for_job(job_id)
    wake = None
    if (
        state in FINAL and job_id not in delivered
    ):  # what the chat must hear about this ending (see wake.py); the browser sends it as the next turn
        try:
            wake = await wake_text(job_id, state)
        except Exception:  # never let this break the job view: the card still shows the state
            logging.getLogger("api").warning("could not build the wake message for %s", job_id, exc_info=True)
    return {
        "job_id": job_id,
        "state": state,
        "error": row.error_type,
        "criteria": criteria,
        "result": await research_result(job_id) if state == "completed" else None,
        "booking": await booking_view(booking) if booking else None,
        "progress": [{"seq": p["seq"], "message": p["message"]} for p in await deps.repo.progress(job_id)],
        "wake": wake,
    }


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """GET /api/jobs/{id}: everything the UI needs to show a research again after a refresh: its state, the request as the chat understood
    it, the progress lines, the research agent's result once it has finished, any booking made from it, and `wake` (the message the chat should be told
    when the job has ended, see wake.py)."""
    return await job_view(job_id)


def sse(event: str, data: dict, id: int | None = None) -> str:
    return (f"id: {id}\n" if id is not None else "") + f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/api/jobs/{job_id}/stream")
async def job_stream(job_id: str, request: Request):
    """GET /api/jobs/{id}/stream: live progress of ONE job (research or preparation) as server-sent events.

    One `progress` event per progress line the job writes and one `state` event per change (queued, running, completed, failed). It
    ends when the job does. A reconnecting browser resumes from its `Last-Event-ID`.
    """
    after = int(request.headers.get("last-event-id", 0))
    try:
        await deps.client.status(job_id)  # 404 early
    except Exception:
        raise HTTPException(404, "No such job") from None

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

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str, body: RetryResearchIn | None = None):
    """POST /api/jobs/{id}/retry: run a failed research again, with the same request, as a new job (not a resume). Returns the new job id."""
    view = await job_view(job_id)
    if view["state"] != "failed" or view["criteria"] is None:
        raise HTTPException(409, "Only a failed job can be retried")
    criteria = SearchRequest.model_validate(view["criteria"])
    if body and body.provider_sleep_seconds is not None:
        criteria = criteria.model_copy(update={"provider_sleep_seconds": body.provider_sleep_seconds})
    return {"job_id": await deps.client.submit(Researcher, ResearchInput.model_validate(criteria.model_dump()))}


# ------------------------------------------------------------------------------------------ prepare booking (resumable job)


@app.post("/api/preparations")
async def start_preparation(body: PrepareIn):
    """POST /api/preparations: the "Prepare booking" button. Submits the two-agent job for the chosen provider and slot.

    `resumable=True` keeps the steps' outputs, so if the job fails (the demo failure flag) a retry can resume it. Returns the job id.
    """
    if await deps.repo.get_request(body.job_id) is None:
        raise HTTPException(404, "No such research")
    prepare = PrepareInput(
        research_job_id=body.job_id, provider_id=body.provider_id, slot_id=body.slot_id, simulate_failure=body.simulate_failure
    )
    return {"job_id": await deps.client.submit(prepare_booking, prepare, resumable=True)}


@app.get("/api/preparations/{job_id}")
async def get_preparation(job_id: str):
    """GET /api/preparations/{id}: the state, progress lines and result (the confirmation text) of one preparation job."""
    try:
        row = await deps.client.status(job_id)
    except Exception:
        raise HTTPException(404, "No such job") from None
    prep = await deps.repo.get_preparation(job_id)
    return {
        "job_id": job_id,
        "state": STATES[row.status],
        "error": row.error_type,
        "result": prep["result"] if prep else None,
        "progress": [{"seq": p["seq"], "message": p["message"]} for p in await deps.repo.progress(job_id)],
    }


@app.post("/api/preparations/{job_id}/retry")
async def retry_preparation(job_id: str, body: RetryPreparationIn | None = None):
    """POST /api/preparations/{id}/retry: resume a failed preparation as a new job. The steps that succeeded (the first agent) are reused
    with no model call, and only the rest runs. Returns the new job id."""
    prep = await deps.repo.get_preparation(job_id)
    if prep is None or STATES[(await deps.client.status(job_id)).status] != "failed":
        raise HTTPException(409, "Only a failed preparation can be retried")
    again = PrepareInput(
        research_job_id=prep["research_job_id"],
        provider_id=prep["provider_id"],
        slot_id=prep["slot_id"],
        simulate_failure=bool(body and body.simulate_failure),
    )
    return {"job_id": await deps.client.submit(prepare_booking, again, resumable=True, resume_from=job_id)}


# --------------------------------------------------------------------------------------------------------------- bookings


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
    """POST /api/bookings: the explicit confirmation, and the only place a booking is created. Plain application code: no agent decides.

    Idempotent: the same `idempotency_key` returns the same booking (200) instead of making a second one (the first is 201). A slot
    that is not open any more is 409.
    """
    if await deps.repo.get_request(body.job_id) is None:
        raise HTTPException(404, "No such job")
    try:
        booking, created = await deps.repo.book(
            idempotency_key=body.idempotency_key,
            job_id=body.job_id,
            provider_id=body.provider_id,
            slot_id=body.slot_id,
        )
    except SlotTaken as exc:
        raise HTTPException(409, str(exc)) from exc
    return JSONResponse(await booking_view(booking), status_code=201 if created else 200)


@app.get("/api/bookings/{booking_id}")
async def get_booking(booking_id: str):
    """GET /api/bookings/{id}: a booking, with its provider and slot. Always marked simulated."""
    booking = await deps.repo.get_booking(booking_id)
    if booking is None:
        raise HTTPException(404, "No such booking")
    return await booking_view(booking)


if Path(STATIC_DIR).is_dir():  # last, so the API routes above win
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
