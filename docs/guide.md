# Guide

How the pieces work. Read it next to the code: each section names the file.

## The chat agent (`chat.py`)

`Concierge` is a featherweight `StreamingAgent`. The endpoint is the standard three lines: `agui.parse_request`, `runner.stream`,
`agui.encode`. featherweight streams the words, the step events and the tool calls to the browser as AG-UI events, so the app builds
no events by hand. The client sends the whole conversation each turn; featherweight keeps none.

The typed intake is a **background agent**: `background_agents = [research_providers]`. The framework gives the model a
`start_background` tool and checks the model's input against the job's input model, `SearchRequest` (`domain.py`). A value that is
missing or invalid is refused with a message the model reads, and the model asks the user. When the input is valid the framework
submits the job to the queue and returns the job id at once, and the stream carries a `background_started` event. The chat does not
wait for the job.

### Waking the chat (`wake.py`, `frontend/src/wake.ts`)

The chat turn ends as soon as the research is started, and the job finishes seconds later, after the stream has closed.
featherweight emits `background_finished` only while the stream is open, and it **wakes nothing**: delivering the outcome to the chat
is the application's job (the "session that wakes itself" in the featherweight guide). Here it works like this:

1. The job response (`GET /api/jobs/{id}`) carries a `wake` field once the job is final. The server builds it:
   `runner.background_message(job_id)` (featherweight's message, with the job's status and output) plus, for a failure, the
   job's own progress notes. featherweight gives a failed child's status and error type but never the error text, so the notes
   are how the chat can say *what* went wrong.
2. The research card in the live conversation sees `wake`, and once the chat is idle it appends the message as the next user turn.
   assistant-ui posts the whole conversation to `/api/agui` as usual.
3. The concierge's prompt tells it how to treat a message that starts with `<background_result>`: summarise a success, report a
   failure and point to Retry. The thread shows a one-line notice instead of the raw message.

Guards, so it stays robust: only a card in the live thread wakes the chat (a card restored after a refresh, from "Last research",
never does); each job wakes the chat once (in memory and in `localStorage`, marked just before the message is appended); the
wake waits while the chat is running; and a failure to build the message never breaks the job view. A retried research is a new
job, so it wakes the chat again when it ends.

## The research job (`research.py`)

`research_providers` is plain async Python, started by a worker:

1. Save the request (first, so the app can show it while the job runs) and discover candidate providers from the catalogue.
2. `ctx.run_many(ProviderResearcher, ...)`: one agent per provider, **in parallel**. Each calls the `check_availability` tool, which
   goes through the `AvailabilityService` interface.
3. `ctx.run(Evaluator, ...)`: ranks the candidates.
4. Build the result **from application data**. The model only chose ids; the provider and slot data in the shortlist is read from the
   catalogue and the availability service. Only `reasons` and `summary` are model-written, and the UI labels them so.

Checks that a schema cannot express live in `check_output`: the evaluator may only return provider and slot ids that were in its
input, every pick needs a reason and one of its own slots, and a researcher run fails if its availability lookup failed. If nothing
fits, the shortlist is empty and the UI says so. Nothing is invented.

## The preparation job (`booking_prep.py`): failure and resume

Started by the **Prepare booking** button with `client.submit(prepare_booking, ..., resumable=True)`. Two agents run in order:
`BookingBriefer`, then `ConfirmationWriter`. With the demo outage switch on, the job raises *between* them.

Retry calls `client.submit(..., resume_from=<failed job>)`. featherweight creates a new job; agent runs that already succeeded with
the same agent and input are reused (no model call, zero tokens), and the rest run. Rules this relies on: the failed job must have
been `resumable`, and the code between the agents must be deterministic. The outage check reads a demo switch, which is the point of
the demo, not a pattern to copy.

Booking itself is **not** an agent decision. `POST /api/bookings` is a plain transaction: it locks the slot row, and a unique
idempotency key makes a repeated confirmation return the same booking. A second key for the same slot gets a 409.

## Job lifecycle

| State shown | featherweight status | Meaning |
|---|---|---|
| `queued` | `INIT` | Submitted, waiting for a worker |
| `running` | `RUNNING` | A worker holds the job |
| `completed` | `SUCCESS` | Done; the result is in the app tables |
| `failed` | `FAILED` | An error, or the job timed out |
| `cancelled` | `CANCELLED` | Cancelled |

`GET /api/jobs/{id}` and `GET /api/preparations/{id}` return the state, progress and result, so a page refresh or a new client sees
the same thing. `GET /api/jobs/{id}/stream` is the live view: server-sent events, one `progress` event per line and one `state` event
per change, resumable with `Last-Event-ID`. The progress lines are the application's own (`app.job_progress`), written by the jobs.

## Delivery and idempotency

`PostgresQueue` (`fw_adapters.py`) delivers **at least once**. A worker holds a lease on a message (60 s) and renews it; if the worker
dies, the lease ends, another worker takes the message, and featherweight takes the job over. After 3 deliveries a message is
dead-lettered and its job fails (`DeadLettered`). So every job must be safe to run twice: writes are upserts, and the booking is
idempotent. There is no exactly-once execution. The queue and the result store pass featherweight's conformance kits
(`check_queue`, `check_result_store`) in `backend/tests/test_adapters.py`.

## Tracing

The API and the worker each configure OpenTelemetry (`telemetry.py`) and export to Jaeger; featherweight's `OTelObserver` emits the
spans. The trace context travels in the queue message, so a job joins the trace of whatever submitted it. A trace of one research,
as recorded in Jaeger:

```
POST /api/agui                                  [api]
  invoke_agent concierge                        [api]
    chat <model>
    execute_tool start_background              [api]
      invoke_workflow research_providers        [worker]
        invoke_agent provider_researcher  (x6)  [worker]
          chat <model>
          execute_tool check_availability       [worker]
        invoke_agent evaluator                  [worker]
          chat <model>
```

And a **resumed** preparation: the briefer is marked reused and has no model call under it.

```
POST /api/preparations/{job_id}/retry           [api]
  invoke_workflow prepare_booking               [worker]
    invoke_agent booking_briefer   (ftw.reused)
    invoke_agent confirmation_writer
      chat <model>
```

**Gaps:** database calls are not instrumented; the ASGI send/receive spans are switched off as noise; in demo mode the model spans
are named after the fake (`chat demo-rules`); Jaeger keeps traces in memory only.

## The frontend (`frontend/`)

Vite, React, [assistant-ui](https://www.assistant-ui.com) and shadcn, **dark only** (no light theme, no toggle). assistant-ui's
`useAgUiRuntime` consumes the AG-UI stream directly, so there is no adapter layer. The only custom piece is `ToolCall` in `App.tsx`:
it renders the `start_background` tool call as the research card and hides the chat's other tool calls. The booking pane
(`BookingPane.tsx`) applies the preparation job's SSE events as they arrive. The UI talks only to `/api/*`.

## Limitations

- Fictional providers and simulated bookings only. No authentication, payments, notifications, rescheduling or cancellation.
- Slot times are stored as UTC and read as Munich local time. The slots are a rolling 14 days, topped up on every start.
- The conversation is not stored: a refresh restores the last research and its booking from the API, not the chat text. For the same
  reason the chat is only woken while the page is open: with no conversation to continue, there is nothing to wake.
- The outage switch is global, not per user. Job progress reaches the stream by polling the database every half second.
- Live mode (Gemini) is untested here: the tests never call a real model, and the research fans out one call per provider at once
  without any rate-limit tuning.
- Jaeger keeps traces in memory, so `make restart` of Jaeger loses them.
