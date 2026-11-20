"""Builds everything both processes need: the application services and the Featherweight runtime parts."""

from contextlib import asynccontextmanager
from dataclasses import dataclass

from concierge import research
from concierge.agents import AvailabilityDeps
from concierge.config import DATABASE_URL
from concierge.domain import Database, PgAvailability, PgCatalog, Repository
from concierge.fw_adapters import PostgresQueue, PostgresResultStore
from concierge.telemetry import setup as setup_telemetry
from featherweight import AgentRunner, JobClient, PostgresDatabase


@dataclass
class Runtime:
    repo: Repository
    catalog: PgCatalog
    availability: PgAvailability
    fw_db: PostgresDatabase  # Featherweight's run log
    queue: PostgresQueue
    results: PostgresResultStore
    runner: AgentRunner
    client: JobClient


@asynccontextmanager
async def runtime(service_name: str):
    """One connection pool for the application's and the adapters' tables; Featherweight's run log has its own connection."""
    observers = setup_telemetry(service_name)
    async with Database(DATABASE_URL) as app, PostgresDatabase(DATABASE_URL) as fw_db:
        repo, catalog, availability = Repository(app), PgCatalog(app), PgAvailability(app)
        research.Deps.repo, research.Deps.catalog, research.Deps.availability = repo, catalog, availability
        AvailabilityDeps.service = availability
        queue, results = PostgresQueue(app.pool, fw_db), PostgresResultStore(app.pool)
        runner = AgentRunner(fw_db, results=results, observers=observers)
        client = JobClient(fw_db, queue, results, observers=observers)
        yield Runtime(repo, catalog, availability, fw_db, queue, results, runner, client)
