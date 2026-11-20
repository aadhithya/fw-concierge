"""The worker process: claims submitted jobs and runs them. Same image as the API, different command."""

import asyncio
import logging

log = logging.getLogger("worker")


async def main() -> None:
    log.info("worker started (no jobs registered yet)")
    await asyncio.Event().wait()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
