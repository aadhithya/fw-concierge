"""Postgres implementations of two featherweight interfaces: `JobQueue` and `ResultStore`.

featherweight ships a Postgres run log but only sqlite/memory queues, and leaves results to you. These two classes are the
glue that lets API and worker processes share one Postgres. Both pass featherweight's conformance kits (see tests/).
"""

import asyncio
import logging
import time

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from featherweight import Delivery, JobMessage, JobQueue, ResultKey, ResultStore
from featherweight.fingerprint import text_hash
from featherweight.queue import DEAD_LETTERED

log = logging.getLogger(__name__)


class PostgresQueue(JobQueue):
    """A table of messages. A claim is one `UPDATE ... FOR UPDATE SKIP LOCKED`: two workers never get the same message.
    A message not acked before its lease ends is claimed again with a higher `delivery_count`; after `max_deliveries`
    it is marked `dead` and its job fails (`DeadLettered`). Delivery is at-least-once, so a job must be safe to run twice."""

    POLL_START, POLL_MAX = 0.02, 0.5

    def __init__(self, pool: AsyncConnectionPool, db, *, lease: float = 60.0, max_deliveries: int = 3):
        self.pool, self.db, self.lease, self.max_deliveries = pool, db, lease, max_deliveries

    async def enqueue(self, message: JobMessage) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO fw_adapters.job_queue (job_id, job_name, input, trace_context) VALUES (%s, %s, %s, %s)",
                (message.job_id, message.job_name, Jsonb(message.input), Jsonb(message.trace_context)),
            )

    async def _claim(self) -> Delivery | None:
        async with self.pool.connection() as conn:
            dead = await (
                await conn.execute(
                    "UPDATE fw_adapters.job_queue SET state = 'dead', lease_expires_at = NULL "
                    "WHERE state = 'claimed' AND lease_expires_at <= clock_timestamp() AND delivery_count >= %s "
                    "RETURNING job_id",
                    (self.max_deliveries,),
                )
            ).fetchall()
            row = await (
                await conn.execute(
                    """WITH next AS (
                           SELECT seq FROM fw_adapters.job_queue
                           WHERE state = 'ready' OR (state = 'claimed' AND lease_expires_at <= clock_timestamp())
                           ORDER BY seq FOR UPDATE SKIP LOCKED LIMIT 1)
                       UPDATE fw_adapters.job_queue q
                       SET state = 'claimed', delivery_count = q.delivery_count + 1,
                           lease_expires_at = clock_timestamp() + make_interval(secs => %s)
                       FROM next WHERE q.seq = next.seq
                       RETURNING q.seq, q.job_id, q.job_name, q.input, q.trace_context, q.delivery_count""",
                    (self.lease,),
                )
            ).fetchone()
        for item in dead:  # its job will never run: end it
            log.warning("queue_message_dead job_id=%s", item["job_id"])
            await self.db.fail_queued_job(item["job_id"], DEAD_LETTERED, text_hash(DEAD_LETTERED))
        if row is None:
            return None
        message = JobMessage(
            job_id=row["job_id"], job_name=row["job_name"], input=row["input"], trace_context=row["trace_context"]
        )
        return Delivery(message=message, token=f"{row['seq']}:{row['delivery_count']}", delivery_count=row["delivery_count"])

    async def receive(self, timeout: float) -> Delivery | None:
        deadline, delay = time.monotonic() + timeout, self.POLL_START
        while True:
            delivery = await self._claim()
            if delivery is not None:
                return delivery
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(delay, remaining))
            delay = min(delay * 2, self.POLL_MAX)

    @staticmethod
    def _claim_of(delivery: Delivery) -> tuple[int, int]:  # the token names one claim, so a stale delivery changes nothing
        seq, count = delivery.token.split(":")
        return int(seq), int(count)

    async def ack(self, delivery: Delivery) -> None:
        seq, count = self._claim_of(delivery)
        async with self.pool.connection() as conn:
            await conn.execute(
                "DELETE FROM fw_adapters.job_queue WHERE seq = %s AND state = 'claimed' AND delivery_count = %s", (seq, count)
            )

    async def nack(self, delivery: Delivery, *, requeue: bool) -> None:
        seq, count = self._claim_of(delivery)
        where = "WHERE seq = %s AND state = 'claimed' AND delivery_count = %s"
        async with self.pool.connection() as conn:
            if requeue:  # back to ready, keeping its place in the order
                await conn.execute(f"UPDATE fw_adapters.job_queue SET state = 'ready', lease_expires_at = NULL {where}", (seq, count))
            else:
                await conn.execute(f"DELETE FROM fw_adapters.job_queue {where}", (seq, count))

    async def extend(self, delivery: Delivery) -> None:
        seq, count = self._claim_of(delivery)
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE fw_adapters.job_queue SET lease_expires_at = clock_timestamp() + make_interval(secs => %s) "
                "WHERE seq = %s AND state = 'claimed' AND delivery_count = %s",
                (self.lease, seq, count),
            )


class PostgresResultStore(ResultStore):
    """Job and agent outputs, behind featherweight's `ResultStore`. Application data: the table is `app.job_results`."""

    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool

    async def put(self, key: ResultKey, output: dict) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO app.job_results (job_id, agent_hash, input_hash, output) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (job_id, agent_hash, input_hash) DO UPDATE SET output = excluded.output, created_at = now()",
                (key.job_id, key.agent_hash, key.input_hash, Jsonb(output)),
            )

    async def get(self, key: ResultKey) -> dict | None:
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT output FROM app.job_results WHERE job_id = %s AND agent_hash = %s AND input_hash = %s",
                    (key.job_id, key.agent_hash, key.input_hash),
                )
            ).fetchone()
        return row["output"] if row else None

    async def delete_job(self, job_id: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute("DELETE FROM app.job_results WHERE job_id = %s", (job_id,))
