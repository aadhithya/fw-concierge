"""The application's domain: models, the service interfaces the agents use, and the Postgres repositories behind them.

Everything here is fictional. featherweight never sees these tables; agents reach providers and availability only through
`ProviderCatalog` and `AvailabilityService`, so the mock availability can be replaced without touching the orchestration.
"""

import json
import uuid
from datetime import date, datetime, time
from typing import Literal, Protocol

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field, field_validator, model_validator

REGION = "Munich"  # providers are fictional; the city and its neighbourhoods are real
NEIGHBOURHOODS = ["Schwabing", "Maxvorstadt", "Haidhausen", "Sendling", "Giesing", "Neuhausen"]
NEARBY = {  # a search for a neighbourhood also includes the ones next to it
    "Schwabing": {"Maxvorstadt", "Neuhausen"},
    "Maxvorstadt": {"Schwabing", "Haidhausen", "Sendling"},
    "Haidhausen": {"Maxvorstadt", "Giesing"},
    "Sendling": {"Maxvorstadt", "Giesing"},
    "Giesing": {"Haidhausen", "Sendling"},
    "Neuhausen": {"Schwabing"},
}


class SearchRequest(BaseModel):
    """What the chat agent extracts from the conversation, and the input of the research job. Pydantic checks it, so an
    incomplete or invalid request is refused with a message the chat agent can read and ask the user about."""

    location: str  # REGION, or one of NEIGHBOURHOODS
    date_from: date
    date_to: date
    preferences: list[str] = []  # short phrases: 'back pain', 'evening', 'home visit'
    service_category: Literal["physiotherapy"] = "physiotherapy"
    # Demo control, not part of what the user wants: how long the mock provider service (an MCP server) takes. The UI sets it
    # (see api.py); leave it at the default.
    provider_sleep_seconds: float = Field(default=4, ge=0, le=20)

    @field_validator("location")
    @classmethod
    def _known_location(cls, value: str) -> str:
        if value != REGION and value not in NEIGHBOURHOODS:
            raise ValueError(f"location must be {REGION!r} or one of {NEIGHBOURHOODS}")
        return value

    @model_validator(mode="after")
    def _window_is_ordered(self) -> "SearchRequest":
        if self.date_to < self.date_from:
            raise ValueError("date_to must not be before date_from")
        return self


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


# A preference phrase that names an attribute of the provider: (the attribute, how it reads as a match)
ATTRIBUTE_PREFERENCES = {
    "evening": ("evenings", "evening appointments"),
    "weekend": ("weekends", "weekend appointments"),
    "home visit": ("home_visits", "home visits"),
    "accessible": ("accessible", "step-free access"),
}


def match_preferences(provider: Provider, preferences: list[str]) -> tuple[list[str], list[str]]:
    """Which of the user's preferences a provider meets, and which it does not. Plain comparison of known attributes."""
    matched, concerns = [], []
    for preference in preferences:
        wanted = preference.lower()
        attribute = next((v for k, v in ATTRIBUTE_PREFERENCES.items() if k in wanted), None)
        if attribute:
            ok, label = bool(getattr(provider, attribute[0])), attribute[1]
        else:  # otherwise it names a condition: compare with the provider's tags
            ok, label = any(wanted in tag or tag in wanted for tag in provider.tags), f"treats {wanted}"
        (matched if ok else concerns).append(label if ok else preference)
    return matched, concerns


class ProviderCatalog(Protocol):
    async def discover(self, request: SearchRequest) -> list[Provider]: ...
    async def get(self, provider_id: str) -> Provider | None: ...


class AvailabilityService(Protocol):
    async def slots(self, provider_id: str, date_from: date, date_to: date) -> list[Slot]: ...
    async def get(self, slot_id: str) -> Slot | None: ...


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
    """Requests, results, progress, preparations, bookings and demo settings. Everything is keyed by the id of its job."""

    def __init__(self, db: Database):
        self.db = db

    async def save_request(self, job_id: str, request: SearchRequest) -> None:  # an upsert: a job may run twice
        async with self.db.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO app.appointment_requests (job_id, criteria) VALUES (%s, %s) "
                "ON CONFLICT (job_id) DO UPDATE SET criteria = excluded.criteria",
                (job_id, request.model_dump_json()),
            )

    async def get_request(self, job_id: str) -> dict | None:
        async with self.db.pool.connection() as conn:
            row = await (
                await conn.execute("SELECT criteria FROM app.appointment_requests WHERE job_id = %s", (job_id,))
            ).fetchone()
        return row["criteria"] if row else None

    async def add_progress(self, job_id: str, message: str) -> None:
        async with self.db.pool.connection() as conn:
            await conn.execute("INSERT INTO app.job_progress (job_id, message) VALUES (%s, %s)", (job_id, message))

    async def progress(self, job_id: str, after: int = 0) -> list[dict]:
        async with self.db.pool.connection() as conn:
            return await (
                await conn.execute(
                    "SELECT seq, message FROM app.job_progress WHERE job_id = %s AND seq > %s ORDER BY seq", (job_id, after)
                )
            ).fetchall()

    async def book(self, *, idempotency_key: str, job_id: str, provider_id: str, slot_id: str) -> tuple[dict, bool]:
        """Create the booking, or return the one made with the same key. Returns (booking, created).
        Raises `SlotTaken` when the slot is not open. A deterministic application operation, never an agent decision."""
        async with self.db.pool.connection() as conn, conn.transaction():  # one transaction: the slot and the booking agree
            existing = await (
                await conn.execute("SELECT * FROM app.bookings WHERE idempotency_key = %s", (idempotency_key,))
            ).fetchone()
            if existing:  # the same confirmation sent again: no second booking
                return existing, False
            slot = await (
                await conn.execute("SELECT status, provider_id FROM app.availability_slots WHERE id = %s FOR UPDATE", (slot_id,))
            ).fetchone()  # FOR UPDATE: two confirmations of one slot cannot both pass the check below
            if slot is None or slot["provider_id"] != provider_id:
                raise SlotTaken("no such slot for that provider")
            if slot["status"] != "open":
                raise SlotTaken("that slot has just been taken")
            await conn.execute("UPDATE app.availability_slots SET status = 'booked' WHERE id = %s", (slot_id,))
            booking = await (
                await conn.execute(
                    "INSERT INTO app.bookings (id, idempotency_key, job_id, provider_id, slot_id) VALUES (%s, %s, %s, %s, %s) RETURNING *",
                    (f"bk-{uuid.uuid4().hex[:8]}", idempotency_key, job_id, provider_id, slot_id),
                )
            ).fetchone()
        return booking, True

    async def get_booking(self, booking_id: str) -> dict | None:
        async with self.db.pool.connection() as conn:
            return await (await conn.execute("SELECT * FROM app.bookings WHERE id = %s", (booking_id,))).fetchone()

    async def booking_for_job(self, job_id: str) -> dict | None:
        async with self.db.pool.connection() as conn:
            return await (await conn.execute("SELECT * FROM app.bookings WHERE job_id = %s", (job_id,))).fetchone()

    async def save_preparation_input(self, job_id: str, research_job_id: str, provider_id: str, slot_id: str) -> None:
        async with self.db.pool.connection() as conn:  # an upsert: a job may run twice
            await conn.execute(
                "INSERT INTO app.preparations (job_id, research_job_id, provider_id, slot_id) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (job_id) DO NOTHING",
                (job_id, research_job_id, provider_id, slot_id),
            )

    async def save_preparation_result(self, job_id: str, result: dict) -> None:
        async with self.db.pool.connection() as conn:
            await conn.execute("UPDATE app.preparations SET result = %s WHERE job_id = %s", (json.dumps(result), job_id))

    async def get_preparation(self, job_id: str) -> dict | None:
        async with self.db.pool.connection() as conn:
            return await (await conn.execute("SELECT * FROM app.preparations WHERE job_id = %s", (job_id,))).fetchone()


class SlotTaken(Exception):
    pass
