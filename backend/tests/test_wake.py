"""Waking the chat: the message the chat gets when its research ends, and how the chat answers it (demo models)."""

from langchain_core.messages import HumanMessage

from concierge import deps
from concierge.chat import Concierge
from concierge.domain import SearchRequest
from concierge.research import research_providers
from concierge.wake import wake_text
from featherweight import ChatInput
from datetime import date, timedelta


def request():
    return SearchRequest(location="Haidhausen", date_from=date.today() + timedelta(1), date_to=date.today() + timedelta(7))


async def reply(wake: str) -> str:
    run = deps.runner.stream(Concierge, ChatInput.from_langchain([HumanMessage(wake)]))
    return "".join([getattr(e, "delta", "") async for e in run if e.type == "TEXT_MESSAGE_CONTENT"])


async def test_chat_hears_a_finished_research(stack):
    job_id = await deps.client.submit(research_providers, request())
    assert (await deps.client.wait(job_id, timeout=30)).status.value == "SUCCESS"
    text = await wake_text(job_id, "completed")
    assert 'status="SUCCESS"' in text
    assert "The research finished" in await reply(text)


async def test_chat_hears_a_failed_research_and_what_the_job_reported(stack, monkeypatch):
    async def down(*args, **kwargs):
        raise RuntimeError("availability service is down")

    monkeypatch.setattr(deps.availability, "slots", down)  # every availability lookup fails: the job fails
    job_id = await deps.client.submit(research_providers, request())  # submitted the way "Retry" submits it
    assert (await deps.client.wait(job_id, timeout=60)).status.value == "FAILED"
    text = await wake_text(job_id, "failed")
    assert 'status="FAILED"' in text and "Progress notes from the job" in text and "Availability lookup failed" in text
    answer = await reply(text)
    assert "The research failed" in answer and "Retry" in answer
