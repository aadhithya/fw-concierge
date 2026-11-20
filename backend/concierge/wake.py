"""Waking the chat when a background research ends.

featherweight wakes nothing: a chat turn ends as soon as the research is started, and the job finishes later. When it does, the
application must give the chat the result as the next turn. featherweight builds the message (`runner.background_message`); this
module adds what the application knows, the job view in api.py hands it to the browser, and the browser starts the turn.
"""

from concierge import deps

FINAL = ("completed", "failed", "cancelled")


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
