# Getting started

## Requirements

Docker with Compose. Nothing else: the app, the frontend, the tests and the linters all run in containers. To commit, you also need
[pre-commit](https://pre-commit.com) (see Development).

## Run it

```
git clone <this repo> && cd fw-concierge
cp .env.example .env     # optional: demo mode needs no changes
make up                  # builds, starts, waits until healthy
open http://localhost:8000
```

The project runs on featherweight 0.2. **Coming from the featherweight 0.1 version of this project** (tag `v0.1.0`): run `make clean`
first. The queue table changed in place, and featherweight upgrades its own tables in a way 0.1 cannot read.

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
models may answer in JSON instead of calling a tool when an agent has both tools and a typed output. The research agent is such an
agent, and it forwards what its MCP tool returns: if Gemma skips the call, the result is rejected, retried up to three times, and the
research can fail. Run `make up` again after changing `.env`. Live mode has not been exercised in this repository's tests: they never
call a real model.

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
| `make test` | Run the tests in Docker (starts Postgres if needed; never calls a real model) |
| `make lint` | Lint the backend and the frontend, and type-check the frontend |
| `make fmt` / `make fmt-check` | Format the backend / check its formatting |
| `make check` | Lint, format check and tests: what the git hooks run |
| `make hooks` | Install the git hooks. Run once per clone |

## Development

Tests, linting and formatting run in a container (`Dockerfile.dev`, the `dev` service in `compose.yaml`) as your own user, so
nothing is installed on your machine. The container never reads `.env`: it always uses the demo models and has no API key.

Run `make hooks` once per clone. The pre-commit hooks then run `make lint`, `make fmt-check` and `make test` before each commit, and
check that the message is a conventional commit. There is no CI: these hooks are the checks. Docker must be running. The frontend has
a linter and a type check, but no formatter.

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
3. **Read the shortlist:** providers with open slots and why they fit, as the provider service returned them. The research agent forwards
   them; only the one-line summary is its own.
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
| `make test` fails to start | Docker must be running. The tests use the Compose Postgres, in a database of their own (`concierge_test_<hash of the migrations>`) |
| `column ... does not exist` after an update | A migration changed in place: `make clean`, then `make up` |
| Stale build after a change | `make build`, then `make up` |
