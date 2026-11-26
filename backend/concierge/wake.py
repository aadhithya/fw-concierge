"""Waking the chat when a background research ends.

featherweight wakes nothing: a chat turn ends as soon as the research is started, and the job finishes later. When it does, the
application must give the chat the result as the next turn. featherweight builds the message (`runner.background_message`); this
module adds what the application knows, the job view in api.py hands it to the browser, and the browser starts the turn.

There is one case where no wake is needed. If a research ends while the turn that started it is still working, and the model is
called again, featherweight gives that turn the result. It is in `run.new_messages` and not on the stream, so only the server
knows. `noting_delivered` records it, and the job view then offers no wake: otherwise the model would be told twice.
"""

import re
from collections.abc import AsyncIterator
from contextlib import aclosing

from featherweight import Status, StreamingRun

from concierge import deps

FINAL = ("completed", "failed", "cancelled")

# Jobs whose result a chat turn already received. Kept in this API process only (enough for a demo with one API): after a
# restart an open page could tell the model about such a job a second time.
delivered: set[str] = set()
RESULT_MESSAGE = re.compile(r'^<background_result job_id="([^"]+)"')


def delivered_in(run: StreamingRun) -> set[str]:
    """The jobs whose result is among the messages of this turn."""
    found = (RESULT_MESSAGE.match(str(m.content)) for m in run.new_messages if m.type == "human")
    return {match.group(1) for match in found if match}


async def noting_delivered(run: StreamingRun, pieces: AsyncIterator[str]) -> AsyncIterator[str]:
    """Pass the turn's stream through, and note the results the turn received. A result is noted before the next piece is sent, so
    the browser cannot see the turn end first. A turn that fails or is stopped does not count: the chat never answered it."""
    noted: set[str] = set()
    try:
        async with aclosing(pieces) as stream:  # a browser that goes away stops the run
            async for piece in stream:
                noted |= delivered_in(run)
                delivered.update(noted)
                yield piece
    finally:
        if run.status in (Status.FAILED, Status.CANCELLED):
            delivered.difference_update(noted)
        else:
            delivered.update(delivered_in(run))


async def wake_text(job_id: str, state: str) -> str:
    """The user-role message that tells the chat how its research ended. Only for a job that is final.

    featherweight's message carries the job's status and its output as JSON. For a failure it carries the status and the error
    type, never the error text, so the application appends its own progress notes (what the job reported) to say what went wrong.
    """
    message = await deps.runner.background_message(job_id)
    text = str(message.content)
    if state != "completed":
        notes = [p["message"] for p in await deps.repo.progress(job_id)]
        text += "\n\nProgress notes from the job:\n" + "\n".join(f"- {n}" for n in notes)
    return text
