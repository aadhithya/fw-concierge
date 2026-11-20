"""Shared test setup: the whole stack in-process, on its own database (`concierge_test`), with the demo (fake) models."""

import os

os.environ["PROVIDER_SERVICE_URL"] = "http://localhost:8011/mcp"  # before the agents are imported: the MCP server the tests start
os.environ["PROVIDER_SERVICE_LATENCY"] = "0.1"

import asyncio
import socket
import subprocess
import sys
import time

import psycopg
import pytest

from concierge import deps
from concierge.booking_prep import prepare_booking
from concierge.domain import Database, PgAvailability, PgCatalog, Repository
from concierge.fw_adapters import PostgresQueue, PostgresResultStore
from concierge.migrate import migrate
from concierge.research import Researcher
from concierge.seed import seed
from concierge.client import ControlledJobClient
from featherweight import AgentRunner, JobWorker, PostgresDatabase
from tests.test_adapters import ADMIN_DSN, DSN


@pytest.fixture(scope="session")
def provider_service():
    """The mock provider service (an MCP server), as a process of its own, as it runs in its container."""
    env = {**os.environ, "PORT": "8011", "DATABASE_URL": DSN}  # the service reads the test database
    process = subprocess.Popen([sys.executable, "-m", "concierge.mcp"], env=env, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(("localhost", 8011), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield
    process.terminate()


@pytest.fixture
async def stack(provider_service):
    async with await psycopg.AsyncConnection.connect(ADMIN_DSN, autocommit=True) as admin:
        if not await (await admin.execute("SELECT 1 FROM pg_database WHERE datname = 'concierge_test'")).fetchone():
            await admin.execute("CREATE DATABASE concierge_test")
    await migrate(DSN)
    async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as conn:
        await conn.execute("TRUNCATE app.bookings, app.preparations, app.appointment_requests, app.job_progress, app.job_results, fw_adapters.job_queue CASCADE")
        await conn.execute("UPDATE app.availability_slots SET status = 'open'")
        await seed(conn)
    async with Database(DSN) as app_db, PostgresDatabase(DSN) as db:
        deps.repo, deps.catalog, deps.availability = Repository(app_db), PgCatalog(app_db), PgAvailability(app_db)
        queue, results = PostgresQueue(app_db.pool, db), PostgresResultStore(app_db.pool)
        deps.client = ControlledJobClient(db, queue, results)
        worker = JobWorker(db, queue, AgentRunner(db, results=results, retry_delay_s=0), jobs=[Researcher, prepare_booking], results=results)
        running = asyncio.create_task(worker.run())
        async with AgentRunner(db, results=results, background=deps.client) as runner:
            deps.runner = runner
            yield
        await worker.stop()
        await running
