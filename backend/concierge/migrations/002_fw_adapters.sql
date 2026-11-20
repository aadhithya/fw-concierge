-- Storage behind Featherweight's two plug-in interfaces (JobQueue, ResultStore). Own schema: neither the app's
-- `app` tables nor Featherweight's own `featherweight` run-log tables.
CREATE SCHEMA IF NOT EXISTS fw_adapters;

CREATE TABLE fw_adapters.job_queue (
    seq              bigserial PRIMARY KEY,
    job_id           text NOT NULL,
    job_name         text NOT NULL,
    input            jsonb NOT NULL,
    trace_context    jsonb NOT NULL DEFAULT '{}',
    state            text NOT NULL DEFAULT 'ready' CHECK (state IN ('ready', 'claimed', 'dead')),
    delivery_count   int NOT NULL DEFAULT 0,
    lease_expires_at timestamptz
);
CREATE INDEX ON fw_adapters.job_queue (state, seq);

CREATE TABLE fw_adapters.results (
    job_id     text NOT NULL,
    agent_hash text NOT NULL,
    input_hash text NOT NULL,
    output     jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, agent_hash, input_hash)
);
