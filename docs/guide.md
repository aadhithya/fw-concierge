# Guide

How the pieces work. Read it next to the code: each section names the file.

## The chat agent (`chat.py`)

`Concierge` is a featherweight `StreamingAgent`. The endpoint is the standard three lines: `agui.parse_request`, `runner.stream`,
`agui.encode`. featherweight streams the words, the step events and the tool calls to the browser as AG-UI events, so the app builds
no events by hand. The client sends the whole conversation each turn; featherweight keeps none.

**Text only.** featherweight 0.2 accepts files in a chat unless the agent says otherwise, and sends them to the model's provider. The
concierge sets `max_attachments = 0`: a message with a file is refused with a 413, and the composer has no attach button, drop zone or
paste of files.

The research is a **background job**: `background_jobs = [Researcher]`. The framework gives the model a
`start_background` tool and checks the model's input against the agent's input model, `ResearchInput` (the typed search request, built on
`SearchRequest` in `domain.py`). A value that is
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
2. The research card of the live conversation (in the right-hand pane) sees `wake`, and once the chat is idle it appends the message as the next user turn.
   assistant-ui posts the whole conversation to `/api/agui` as usual.
3. The concierge's prompt tells it how to treat a message that starts with `<background_result>`: summarise a success, report a
   failure and point to Retry. The thread shows a one-line notice instead of the raw message.

**When no wake is needed.** If the research ends while the turn that started it is still working, and the model is called again,
featherweight gives that turn the result. It is in `run.new_messages` but not on the stream, so the browser cannot tell. The API
passes the stream through `noting_delivered` (`wake.py`), which notes such results before sending the next piece, and the job response
then carries no `wake`. Right before waking, the browser reads the job again. If the research ends during the turn's last reply, the
turn did not get it and the wake is sent as usual. The note is kept in the API process only: after an API restart, an open page could
tell the model about such a job a second time. The browser's copy of the conversation does not hold a result delivered this way, only
the model's reply to it.

Guards, so it stays robust: only a card started in the live conversation wakes the chat (the card restored after a refresh never does); each job wakes the chat once (in memory and in `localStorage`, marked just before the message is appended); the
wake waits while the chat is running; and a failure to build the message never breaks the job view. A retried research is a new
job, so it wakes the chat again when it ends.

## The research agent (`research.py`, `mcp.py`)

The research is **one agent with one MCP tool**. The chat starts it as a background job, and a worker runs it (an agent class can be
a job: the worker lists `Researcher` in its `jobs`). Its input, `ResearchInput`, is the typed search request.

1. The agent calls its only tool, `providers_search_providers`, once, with the request's location, dates and preferences.
2. The tool lives in an MCP server in a container of its own (`provider-service`: the same image, another command, `mcp.py`, built
   with the MCP SDK's `FastMCP`). It sleeps for `sleep_seconds` to stand for a slow external service, then reads the seeded
   catalogue (read-only), picks the best matches and returns them as JSON: up to 3 providers, each with its open slots and the reasons
   it fits.
3. The agent forwards that answer as its typed result (`ResearchResult`: the shortlist, how many providers were considered, one summary
   sentence). That result is what the research card shows.

The agent is declared with `HttpMCPServer(name="providers", url=..., discover=False)`, so the tool is bound to the model directly.
`check_output` rejects an answer with no providers considered, which is how a model that skipped the tool is caught (the run then
retries). The hosted Gemma models often skip tools, so on `LLM=gemma` this agent can fail: that is the documented featherweight
limitation. The result is read back with `client.result(Researcher, job_id)` from the result store (`app.job_results`).

There is no wrapper job and no per-provider agent: fetching and selecting data is the tool's job, and an agent per provider would cost
a model call each to do what a loop does better. The research card shows no progress lines of its own beyond "Research started": the
agent is one step.

### The job client (`client.py`)

featherweight keeps no job input, and the chat's *model* builds the research input inside `start_background`, so no code of ours sees it.
`ControlledJobClient` is a small `JobClient` subclass that the API and the tests use. When a research is submitted it (1) sets
`provider_sleep_seconds` from the UI's delay control, and (2) saves the request in `app.appointment_requests` (and one progress line in
`app.job_progress`). The card shows the request, Retry resubmits it, and the booking preparation reads it from there.

### The demo controls (`frontend/src/controls.tsx`)

A small card at the bottom of the right-hand pane has two controls. Both are **plain parameters**: each is sent with the request that
starts the work it affects, and nothing about them is stored.

- **Provider service delay:** `provider_sleep_seconds` (0 to 20, default 4) is a field of `ResearchInput`. The agent passes it as `sleep_seconds`
  to the MCP tool. The UI sends it as the `x-provider-sleep` header on chat requests, and `ControlledJobClient` sets the field when the
  chat's `start_background` submits the research (the model cannot know the UI's value). The Retry button sends it in its body instead.
- **Fail the booking preparation:** `PrepareInput.simulate_failure`, sent in the body of "Prepare booking" and of its Retry.

## The preparation job (`booking_prep.py`): failure and resume

Started by the **Prepare booking** button with `client.submit(prepare_booking, ..., resumable=True)`. Two agents run in order:
`BookingBriefer`, then `ConfirmationWriter`. With the demo parameter `simulate_failure` on, the job raises *between* them.

Retry calls `client.submit(..., resume_from=<failed job>)`. featherweight creates a new job; agent runs that already succeeded with
the same agent and input are reused (no model call, zero tokens), and the rest run. Rules this relies on: the failed job must have
been `resumable`, and the code between the agents must be deterministic. The failure parameter is a demo device, not a pattern to copy.

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
      invoke_agent researcher                   [worker]
        chat <model>
        execute_tool providers_search_providers  [worker]  (about 4 s: the MCP service sleeps)
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
`useAgUiRuntime` consumes the AG-UI stream directly, so there is no adapter layer. The chat on the left shows only words: its tool calls
are hidden. The right-hand pane does not scroll itself: the research cards (collapsible, newest first and open, older ones collapse; Retry
adds a new card) and the booking flow each scroll inside their own area, and the demo controls are pinned to the bottom. The researches
of this browser are remembered in `localStorage` (the last 8) and restored after a refresh. The card comes from featherweight's
**`background_started`** event, which `App.tsx` subscribes to (`agent.subscribe({ onCustomEvent })`): it carries the job id and is emitted by
the framework whatever the model. (An earlier version rendered the card from the `start_background` tool call. That broke on Gemma,
whose streamed tool calls did not reach the browser as tool-call events, so no card appeared.) The booking pane (`BookingPane.tsx`)
applies the preparation job's SSE events as they arrive. The UI talks only to `/api/*`.

## Limitations

- The research is simpler than the brief's F3, which asks for several typed agents researching providers in parallel. Here it is one agent
  with one MCP tool, because an agent per provider costs a model call each and adds nothing a loop does not. The other job, the booking
  preparation, has two agents.
- Fictional providers and simulated bookings only. No authentication, payments, notifications, rescheduling or cancellation.
- Slot times are stored as UTC and read as Munich local time. The slots are a rolling 14 days, topped up on every start.
- The conversation is not stored: after a refresh the right-hand pane shows the last research and its booking, loaded from the API, but not the chat text. For the same
  reason the chat is only woken while the page is open: with no conversation to continue, there is nothing to wake.
- Job progress reaches the stream by polling the database every half second.
- Live mode (Gemini) is untested here: the tests never call a real model, and the research fans out one call per provider at once
  without any rate-limit tuning.
- Jaeger keeps traces in memory, so `make restart` of Jaeger loses them.
