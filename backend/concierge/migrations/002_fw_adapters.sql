-- The job queue behind featherweight's `JobQueue` interface. Infrastructure, so it has its own schema: not the app's
-- `app` tables and not featherweight's own `featherweight` run-log tables.
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
