# Getting started

## Requirements

Docker with Compose. For `make test` also [uv](https://docs.astral.sh/uv/) on the host. Nothing else: the frontend is built inside the image.

## Run it

```
git clone <this repo> && cd fw-concierge
cp .env.example .env     # optional: demo mode needs no changes
make up                  # builds, starts, waits until healthy
open http://localhost:8000
```

`make up` starts Postgres, runs the migrations and seeds the data, then starts the API and the worker. The Jaeger UI is at
http://localhost:16686 (`make traces`).

## Modes

| | Demo mode (default) | Live mode |
|---|---|---|
| Set | `DEMO_MODE=1` | `DEMO_MODE=0` and `GOOGLE_API_KEY=...` in `.env` |
| Models | Deterministic, rule-based fakes | `LLM=gemini` (default): Gemini `gemini-3.5-flash-lite`, low thinking. `LLM=gemma`: Gemma `gemma-4-31b-it`, thinking high (it follows tool instructions better) |
| Needs | Nothing, works offline | A key. **Real calls cost money** |
| Use it for | Repeatable demos and tests | Seeing real model behaviour |

**Gemma** is free with a Google API key, which makes it handy for trying live mode. featherweight's docs warn that the hosted Gemma
models may answer in JSON instead of calling a tool when an agent has both tools and a typed output. Here the research agent has one
MCP tool, but nothing depends on it: if Gemma skips the call, the research still succeeds, just without the network answer. The chat
agent has tools too, and Gemma has called them correctly there. Run `make up` again after changing `.env`. Live mode has not been exercised in this repository's tests: they never call a real model.

## Commands

| Command | Does |
|---|---|
| `make up` | Build and start everything (waits until healthy) |
| `make down` | Stop the services; the data is kept |
| `make restart` | Restart the API and the worker |
| `make logs` | Follow the logs of everything, starting with the last 100 lines (`make logs S=worker` for one service) |
| `make logs-api` | Follow the API logs: requests and the chat |
| `make logs-worker` | Follow the worker logs: jobs, agent runs, and why an attempt failed |
| `make ps` | Service status |
| `make build` | Build the image |
| `make reset-db` | Wipe the database and start again with fresh seed data |
| `make clean` | Stop and delete containers, the database volume and the built image |
| `make demo` | Run the scripted walkthrough against the running system |
| `make traces` | Open Jaeger |
| `make test` | Run the tests (needs `make up`; no real model calls) |

## Environment variables

`.env.example` lists them: `DEMO_MODE`, `LLM`, `GOOGLE_API_KEY` and `TRACE_CONTENT`. `TRACE_CONTENT=SPAN_ONLY` records the messages, tool
arguments and results on the Jaeger spans, which is handy for seeing what a model actually did; it holds whatever users typed, so it is
off by default. Compose sets the database URL, the OTLP endpoint and the MCP service URL itself. No real credentials are ever committed.

## Demo walkthrough

In the browser (demo mode), or run `make demo` for the same flow in the terminal:

1. **Ask for something vague:** "I need a physio soon". The assistant asks which area. It does not invent a location or dates.
2. **Complete it:** "Back pain, evening appointments in Haidhausen next week". The assistant tells you what it understood, and a
   **research card** appears in the right-hand pane: the interpreted criteria, then live progress lines as the worker runs the job
   (about 5 seconds: the research agent calls the MCP provider service, which is deliberately slow). When it ends, the chat tells you
   how it went without being asked.
3. **Read the shortlist:** providers with the model's reasons and open slots. Provider and slot data are read from the catalogue,
   and only the reasons are model-written.
4. **Pick a slot.** The right half shows the slot on a week calendar. Nothing is booked yet.
5. **Show the failure path:** in **Demo controls** (bottom of the right-hand pane) turn on **Fail the booking preparation**, then click
   **Prepare booking**. The job runs its first agent, then fails; the status shows `failed`. (The same card has a slider for how long
   the MCP provider service takes, 0–20 seconds, which applies to the next research.)
6. **Retry:** turn the control off and click **Retry**. This *resumes* the job: the log says "Briefing reused from the earlier
   attempt", only the second agent runs, and it completes.
7. **Confirm:** read the confirmation text and click **Confirm booking**. You get a booking reference, labelled simulated.
8. **Refresh the page.** The right-hand pane shows your recent researches (collapsed, the newest open) and any booking, loaded from the API.
9. **Look at the trace:** `make traces`, service `concierge-api`. One trace runs from the API request through the chat's
   `start_background` tool call into the worker's job, its agent and the MCP call.

## Troubleshooting

| Problem | Fix |
|---|---|
| `port is already allocated` | Another service uses 8000, 16686 or 5433. Stop it, or change the host port in `compose.yaml` |
| The page loads but the chat says nothing | `make logs-api`. In live mode check `GOOGLE_API_KEY` |
| A research stays `queued` | The worker is not running: `make ps`, `make logs-worker` |
| A research fails in live mode | `make logs-worker` shows each failed attempt and its reason. With `LLM=gemma` a model may skip a tool call: see the Gemma note under Modes |
| Slots look old or all taken | `make reset-db` reseeds the next 14 days of slots |
| `make test` cannot connect | Run `make up` first: the tests use the Postgres on `localhost:5433` and make their own `concierge_test` database |
| Stale build after a change | `make build`, then `make up` |
