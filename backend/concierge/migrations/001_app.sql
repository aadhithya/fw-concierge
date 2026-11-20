-- Application-owned domain data. Featherweight's run log lives in its own schema (`featherweight`), the queue and result
-- store in `fw_adapters`: nothing here is shared with them.
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

CREATE TABLE app.appointment_requests (
    id         text PRIMARY KEY,
    job_id     text UNIQUE,                 -- the Featherweight job that researches it (set after submit)
    criteria   jsonb NOT NULL,              -- the typed SearchRequest
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.research_results (
    job_id     text PRIMARY KEY,
    request_id text NOT NULL REFERENCES app.appointment_requests(id),
    result     jsonb NOT NULL,              -- the shortlist: verified data and model explanations kept apart
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.research_progress (
    seq        bigserial PRIMARY KEY,
    job_id     text NOT NULL,
    message    text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON app.research_progress (job_id, seq);

CREATE TABLE app.bookings (
    id              text PRIMARY KEY,
    idempotency_key text NOT NULL UNIQUE,   -- a repeated confirmation returns the same booking
    request_id      text NOT NULL REFERENCES app.appointment_requests(id),
    job_id          text NOT NULL,
    provider_id     text NOT NULL REFERENCES app.providers(id),
    slot_id         text NOT NULL UNIQUE REFERENCES app.availability_slots(id),  -- a slot is booked once
    created_at      timestamptz NOT NULL DEFAULT now()
);
