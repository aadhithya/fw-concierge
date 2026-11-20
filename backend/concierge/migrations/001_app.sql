-- Application-owned data: the domain (providers, slots, requests, bookings) and the job results.
-- Featherweight's run log lives in its own schema (`featherweight`) and the queue in `fw_adapters`.
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE app.providers (
    id            text PRIMARY KEY,
    name          text NOT NULL,
    neighbourhood text NOT NULL,
    tags          text[] NOT NULL,          -- conditions treated
    description   text NOT NULL,
    price_band    int NOT NULL,             -- 1 (low) .. 3 (high)
    languages     text[] NOT NULL,
    accessible    boolean NOT NULL,
    home_visits   boolean NOT NULL,
    evenings      boolean NOT NULL,
    weekends      boolean NOT NULL
);

CREATE TABLE app.availability_slots (
    id          text PRIMARY KEY,           -- provider-yyyymmdd-hhmm, so seeding is repeatable
    provider_id text NOT NULL REFERENCES app.providers(id),
    starts_at   timestamptz NOT NULL,       -- UTC, treated as the region's local time
    duration_min int NOT NULL DEFAULT 45,
    status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'booked'))
);
CREATE INDEX ON app.availability_slots (provider_id, starts_at);

-- Everything about one research is keyed by the id of its Featherweight job. The job itself writes the request row first.
CREATE TABLE app.appointment_requests (
    job_id     text PRIMARY KEY,
    criteria   jsonb NOT NULL,              -- the typed SearchRequest the chat agent extracted
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.research_results (
    job_id     text PRIMARY KEY REFERENCES app.appointment_requests(job_id),
    result     jsonb NOT NULL,              -- the shortlist: verified data and model-written reasons kept apart
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Outputs of jobs and agents, behind Featherweight's `ResultStore`. This is application data (it holds user content, and
-- in a multi-tenant app it would be tenant-scoped), so it lives here, under the app's own retention and access rules.
CREATE TABLE app.job_results (
    job_id     text NOT NULL,
    agent_hash text NOT NULL,
    input_hash text NOT NULL,
    output     jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, agent_hash, input_hash)
);

-- Progress lines of any job (research or booking preparation), shown to the user as they happen.
CREATE TABLE app.job_progress (
    seq        bigserial PRIMARY KEY,
    job_id     text NOT NULL,
    message    text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON app.job_progress (job_id, seq);

-- The "prepare booking" job: what it was asked to prepare (so a retry can resume it) and what it produced.
CREATE TABLE app.preparations (
    job_id          text PRIMARY KEY,
    research_job_id text NOT NULL REFERENCES app.appointment_requests(job_id),
    provider_id     text NOT NULL REFERENCES app.providers(id),
    slot_id         text NOT NULL REFERENCES app.availability_slots(id),
    result          jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.bookings (
    id              text PRIMARY KEY,
    idempotency_key text NOT NULL UNIQUE,   -- a repeated confirmation returns the same booking
    job_id          text NOT NULL REFERENCES app.appointment_requests(job_id),
    provider_id     text NOT NULL REFERENCES app.providers(id),
    slot_id         text NOT NULL UNIQUE REFERENCES app.availability_slots(id),  -- a slot is booked once
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Demo switches, such as "simulate a provider outage". Read by the worker at the moment it looks availability up.
CREATE TABLE app.demo_settings (
    key   text PRIMARY KEY,
    value text NOT NULL
);
