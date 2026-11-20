"""The worker process: claims submitted jobs from the queue and runs them. Same image as the API, different command."""

import asyncio
import logging
import signal

from concierge.research import research_providers
from concierge.services import runtime
from featherweight import JobWorker, setup_logging

log = logging.getLogger("worker")


async def main() -> None:
    setup_logging()
    async with runtime("concierge-worker") as rt:
        worker = JobWorker(rt.fw_db, rt.queue, rt.runner, jobs=[research_providers], results=rt.results, concurrency=4)
        loop = asyncio.get_running_loop()
        stopping = asyncio.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stopping.set)
        task = asyncio.create_task(worker.run())
        log.info("worker started")
        await stopping.wait()
        await worker.stop(grace=20)  # unfinished jobs go back on the queue and run again elsewhere
        await task


if __name__ == "__main__":
    asyncio.run(main())
