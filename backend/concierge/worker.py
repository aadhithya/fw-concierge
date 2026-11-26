"""The worker process: takes submitted jobs from the queue and runs them. Same image as the API, different command."""

import asyncio

from featherweight import AgentRunner, JobWorker, PostgresDatabase

from concierge import deps
from concierge.booking_prep import prepare_booking
from concierge.config import DATABASE_URL
from concierge.domain import Database, PgAvailability, PgCatalog, Repository
from concierge.fw_adapters import PostgresQueue, PostgresResultStore
from concierge.research import Researcher
from concierge.telemetry import setup as setup_telemetry


async def main() -> None:
    observers = setup_telemetry("concierge-worker")
    async with Database(DATABASE_URL) as app_db, PostgresDatabase(DATABASE_URL) as db:
        deps.repo, deps.catalog, deps.availability = Repository(app_db), PgCatalog(app_db), PgAvailability(app_db)
        results = PostgresResultStore(app_db.pool)
        runner = AgentRunner(db, results=results, observers=observers)
        worker = JobWorker(db, PostgresQueue(app_db.pool, db), runner, jobs=[Researcher, prepare_booking], results=results)
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
