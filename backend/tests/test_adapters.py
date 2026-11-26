"""The Postgres queue and result store, checked with featherweight's own conformance kits.

They run in a database of their own, never the one the running stack uses: the stack's worker would take the kit's messages
off the queue. Its name carries a hash of the migrations, so a changed migration gets a fresh database. Run with `make test`.
"""

import hashlib
import os
from pathlib import Path

import psycopg
import pytest
from featherweight import PostgresDatabase, testing
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from concierge.fw_adapters import PostgresQueue, PostgresResultStore
from concierge.migrate import MIGRATIONS, migrate

ADMIN_DSN = os.environ.get("TEST_ADMIN_URL", "postgresql://concierge:concierge@localhost:5433/concierge")
_SCHEMA = hashlib.sha256(b"".join(f.read_bytes() for f in sorted(Path(MIGRATIONS).glob("*.sql")))).hexdigest()[:8]
TEST_DB = f"concierge_test_{_SCHEMA}"
DSN = ADMIN_DSN.rsplit("/", 1)[0] + "/" + TEST_DB


async def create_test_database() -> None:
    async with await psycopg.AsyncConnection.connect(ADMIN_DSN, autocommit=True) as admin:
        if not await (await admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))).fetchone():
            await admin.execute(f"CREATE DATABASE {TEST_DB}")
    await migrate(DSN)


@pytest.fixture
async def pool():
    await create_test_database()
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
