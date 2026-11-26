"""The Postgres queue and result store, checked with featherweight's own conformance kits.

They run in a database of their own (`concierge_test`), never the one the running stack uses: the stack's worker would
take the kit's messages off the queue. Needs the Compose Postgres: `make up`, then `make test`.
"""

import os

import psycopg
import pytest
from featherweight import PostgresDatabase, testing
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from concierge.fw_adapters import PostgresQueue, PostgresResultStore
from concierge.migrate import migrate

ADMIN_DSN = os.environ.get("TEST_ADMIN_URL", "postgresql://concierge:concierge@localhost:5433/concierge")
DSN = ADMIN_DSN.rsplit("/", 1)[0] + "/concierge_test"


@pytest.fixture
async def pool():
    async with await psycopg.AsyncConnection.connect(ADMIN_DSN, autocommit=True) as admin:
        if not await (await admin.execute("SELECT 1 FROM pg_database WHERE datname = 'concierge_test'")).fetchone():
            await admin.execute("CREATE DATABASE concierge_test")
    await migrate(DSN)
    async with AsyncConnectionPool(DSN, kwargs={"row_factory": dict_row, "autocommit": True}, open=False) as pool:
        yield pool


async def test_queue_follows_the_contract(pool):
    async with PostgresDatabase(DSN) as db:

        async def make(lease: float):
            async with pool.connection() as conn:
                await conn.execute("TRUNCATE fw_adapters.job_queue")
            return PostgresQueue(pool, db, lease=lease)

        await testing.check_queue(make)


async def test_result_store_follows_the_contract(pool):
    async def make():
        async with pool.connection() as conn:
            await conn.execute("TRUNCATE app.job_results")
        return PostgresResultStore(pool)

    await testing.check_result_store(make)
