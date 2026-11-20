"""Shared test setup: the whole stack in-process, on its own database (`concierge_test`), with the demo (fake) models."""

import asyncio

import psycopg
import pytest

from concierge import deps
from concierge.booking_prep import prepare_booking
from concierge.domain import Database, PgAvailability, PgCatalog, Repository
from concierge.fw_adapters import PostgresQueue, PostgresResultStore
from concierge.migrate import migrate
from concierge.research import research_providers
from concierge.seed import seed
from featherweight import AgentRunner, JobClient, JobWorker, PostgresDatabase
from tests.test_adapters import ADMIN_DSN, DSN


@pytest.fixture
async def stack():
    async with await psycopg.AsyncConnection.connect(ADMIN_DSN, autocommit=True) as admin:
        if not await (await admin.execute("SELECT 1 FROM pg_database WHERE datname = 'concierge_test'")).fetchone():
            await admin.execute("CREATE DATABASE concierge_test")
    await migrate(DSN)
    async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as conn:
        await conn.execute("TRUNCATE app.bookings, app.preparations, app.research_results, app.appointment_requests, app.job_progress, app.demo_settings, app.job_results, fw_adapters.job_queue CASCADE")
        await conn.execute("UPDATE app.availability_slots SET status = 'open'")
        await seed(conn)
    async with Database(DSN) as app_db, PostgresDatabase(DSN) as db:
        deps.repo, deps.catalog, deps.availability = Repository(app_db), PgCatalog(app_db), PgAvailability(app_db)
        queue, results = PostgresQueue(app_db.pool, db), PostgresResultStore(app_db.pool)
        deps.client = JobClient(db, queue, results)
        worker = JobWorker(db, queue, AgentRunner(db, results=results, retry_delay_s=0), jobs=[research_providers, prepare_booking], results=results)
        running = asyncio.create_task(worker.run())
        async with AgentRunner(db, results=results, background=deps.client) as runner:
            deps.runner = runner
            yield
        await worker.stop()
        await running
