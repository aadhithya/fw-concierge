"""Apply the SQL files in `migrations/` in order, once each, then seed. Run by the `migrate` Compose service."""

import asyncio
import logging
from pathlib import Path

import psycopg

from concierge.config import DATABASE_URL
from concierge.seed import seed

log = logging.getLogger("migrate")
MIGRATIONS = Path(__file__).parent / "migrations"


async def main() -> None:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        await conn.execute("SELECT pg_advisory_lock(727)")
        await conn.execute("CREATE TABLE IF NOT EXISTS public.schema_migrations (name text PRIMARY KEY)")
        done = {r[0] for r in await (await conn.execute("SELECT name FROM public.schema_migrations")).fetchall()}
        for file in sorted(MIGRATIONS.glob("*.sql")):
            if file.name in done:
                continue
            await conn.execute(file.read_text())
            await conn.execute("INSERT INTO public.schema_migrations VALUES (%s)", (file.name,))
            log.info("applied %s", file.name)
        await seed(conn)  # providers and the next 14 days of slots; repeatable
        log.info("seeded")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
