"""The Postgres queue and result store, checked with Featherweight's own conformance kits.

Needs the Compose Postgres: `make up`, then `make test` (it uses localhost:5433).
"""

import os

import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from concierge.fw_adapters import PostgresQueue, PostgresResultStore
from featherweight import PostgresDatabase, testing

DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://concierge:concierge@localhost:5433/concierge")


@pytest.fixture
async def pool():
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
            await conn.execute("TRUNCATE fw_adapters.results")
        return PostgresResultStore(pool)

    await testing.check_result_store(make)
