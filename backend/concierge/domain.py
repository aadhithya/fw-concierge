"""The application's domain: models, the service interfaces the agents use, and the Postgres repositories behind them.

Everything here is fictional. Featherweight never sees these tables; agents reach providers and availability only through
`ProviderCatalog` and `AvailabilityService`, so the mock availability can be replaced without touching the orchestration.
"""

import json
import uuid
from datetime import date, datetime, time
from typing import Literal, Protocol

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

REGION = "Marlow Bay"  # a fictional region
NEIGHBOURHOODS = ["Harbourside", "Old Mill", "Kestrel Heights", "Lantern Quay", "Fernwick"]
NEARBY = {  # discovery for a neighbourhood includes the ones next to it
    "Harbourside": {"Lantern Quay", "Old Mill"},
    "Old Mill": {"Harbourside", "Fernwick"},
    "Kestrel Heights": {"Fernwick"},
    "Lantern Quay": {"Harbourside"},
    "Fernwick": {"Old Mill", "Kestrel Heights"},
}


class SearchRequest(BaseModel):
    """What the intake agent must produce. Required fields have no defaults, so an incomplete request cannot be built."""

    service_category: Literal["physiotherapy"]
    location: str  # REGION or one of NEIGHBOURHOODS
    date_from: date
    date_to: date
    preferences: list[str] = []


class Provider(BaseModel):
    id: str
    name: str
    neighbourhood: str
    tags: list[str]
    description: str
    price_band: int
    languages: list[str]
    accessible: bool
    home_visits: bool
    evenings: bool
    weekends: bool


class Slot(BaseModel):
    id: str
    provider_id: str
    starts_at: datetime
    duration_min: int
    status: str


class ProviderLookupError(RuntimeError):
    """A provider's availability could not be fetched."""


class ProviderCatalog(Protocol):
    async def discover(self, request: SearchRequest) -> list[Provider]: ...
    async def get(self, provider_id: str) -> Provider | None: ...


class AvailabilityService(Protocol):
    async def slots(self, provider_id: str, date_from: date, date_to: date) -> list[Slot]: ...


class Database:
    """One connection pool for all application repositories."""

    def __init__(self, dsn: str):
        self.pool = AsyncConnectionPool(dsn, kwargs={"row_factory": dict_row, "autocommit": True}, open=False, max_size=10)

    async def __aenter__(self):
        await self.pool.open()
        return self

    async def __aexit__(self, *exc):
        await self.pool.close()


class PgCatalog:
    def __init__(self, db: Database):
        self.db = db

    async def discover(self, request: SearchRequest) -> list[Provider]:
        async with self.db.pool.connection() as conn:
            rows = await (await conn.execute("SELECT * FROM app.providers ORDER BY id")).fetchall()
        providers = [Provider(**r) for r in rows]
        if request.location in NEARBY:
            near = {request.location} | NEARBY[request.location]
            providers = [p for p in providers if p.neighbourhood in near]
        return providers  # a region-wide request keeps everyone

    async def get(self, provider_id: str) -> Provider | None:
        async with self.db.pool.connection() as conn:
            row = await (await conn.execute("SELECT * FROM app.providers WHERE id = %s", (provider_id,))).fetchone()
        return Provider(**row) if row else None


class PgAvailability:
    """Mock availability from seeded Postgres data. Replace this class to change where slots come from."""

    def __init__(self, db: Database):
        self.db = db

    async def slots(self, provider_id: str, date_from: date, date_to: date) -> list[Slot]:
        start, end = datetime.combine(date_from, time.min), datetime.combine(date_to, time.max)
        async with self.db.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT * FROM app.availability_slots WHERE provider_id = %s AND status = 'open' "
                    "AND starts_at >= %s AND starts_at <= %s ORDER BY starts_at",
                    (provider_id, start, end),
                )
            ).fetchall()
        return [Slot(**r) for r in rows]

    async def get(self, slot_id: str) -> Slot | None:
        async with self.db.pool.connection() as conn:
            row = await (await conn.execute("SELECT * FROM app.availability_slots WHERE id = %s", (slot_id,))).fetchone()
        return Slot(**row) if row else None


class Repository:
    """Requests, research results, progress and bookings."""

    def __init__(self, db: Database):
        self.db = db

    async def create_request(self, criteria: SearchRequest) -> str:
        request_id = f"req-{uuid.uuid4().hex[:8]}"
        async with self.db.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO app.appointment_requests (id, criteria) VALUES (%s, %s)",
                (request_id, criteria.model_dump_json()),
            )
        return request_id

    async def attach_job(self, request_id: str, job_id: str) -> None:
        async with self.db.pool.connection() as conn:
            await conn.execute("UPDATE app.appointment_requests SET job_id = %s WHERE id = %s", (job_id, request_id))

    async def request_for_job(self, job_id: str) -> dict | None:
        async with self.db.pool.connection() as conn:
            return await (
                await conn.execute("SELECT id, job_id, criteria FROM app.appointment_requests WHERE job_id = %s", (job_id,))
            ).fetchone()

    async def save_result(self, job_id: str, request_id: str, result: dict) -> None:  # safe to run twice
        async with self.db.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO app.research_results (job_id, request_id, result) VALUES (%s, %s, %s) "
                "ON CONFLICT (job_id) DO UPDATE SET result = excluded.result",
                (job_id, request_id, json.dumps(result)),
            )

    async def get_result(self, job_id: str) -> dict | None:
        async with self.db.pool.connection() as conn:
            row = await (await conn.execute("SELECT result FROM app.research_results WHERE job_id = %s", (job_id,))).fetchone()
        return row["result"] if row else None

    async def add_progress(self, job_id: str, message: str) -> None:
        async with self.db.pool.connection() as conn:
            await conn.execute("INSERT INTO app.research_progress (job_id, message) VALUES (%s, %s)", (job_id, message))

    async def progress(self, job_id: str, after: int = 0) -> list[dict]:
        async with self.db.pool.connection() as conn:
            return await (
                await conn.execute(
                    "SELECT seq, message, created_at FROM app.research_progress WHERE job_id = %s AND seq > %s ORDER BY seq",
                    (job_id, after),
                )
            ).fetchall()

    async def book(self, *, idempotency_key: str, request_id: str, job_id: str, provider_id: str, slot_id: str) -> tuple[dict, bool]:
        """Create the booking, or return the one made with the same key. Returns (booking, created).
        Raises `SlotTaken` when the slot is not open. A deterministic application operation, never an agent decision."""
        async with self.db.pool.connection() as conn, conn.transaction():
            existing = await (
                await conn.execute("SELECT * FROM app.bookings WHERE idempotency_key = %s", (idempotency_key,))
            ).fetchone()
            if existing:
                return existing, False
            slot = await (
                await conn.execute(
                    "SELECT status, provider_id FROM app.availability_slots WHERE id = %s FOR UPDATE", (slot_id,)
                )
            ).fetchone()
            if slot is None or slot["provider_id"] != provider_id:
                raise SlotTaken("no such slot for that provider")
            if slot["status"] != "open":
                raise SlotTaken("that slot has just been taken")
            await conn.execute("UPDATE app.availability_slots SET status = 'booked' WHERE id = %s", (slot_id,))
            booking_id = f"bk-{uuid.uuid4().hex[:8]}"
            booking = await (
                await conn.execute(
                    "INSERT INTO app.bookings (id, idempotency_key, request_id, job_id, provider_id, slot_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
                    (booking_id, idempotency_key, request_id, job_id, provider_id, slot_id),
                )
            ).fetchone()
        return booking, True

    async def get_booking(self, booking_id: str) -> dict | None:
        async with self.db.pool.connection() as conn:
            return await (await conn.execute("SELECT * FROM app.bookings WHERE id = %s", (booking_id,))).fetchone()

    async def booking_for_job(self, job_id: str) -> dict | None:
        async with self.db.pool.connection() as conn:
            return await (await conn.execute("SELECT * FROM app.bookings WHERE job_id = %s", (job_id,))).fetchone()


class SlotTaken(Exception):
    pass
