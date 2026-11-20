"""Waking the chat: the message the chat gets when a job ends, and how the chat answers it (demo models)."""

from datetime import date, timedelta

from langchain_core.messages import HumanMessage

from concierge import deps
from concierge.booking_prep import PrepareInput, prepare_booking
from concierge.chat import Concierge
from concierge.research import Researcher, ResearchInput
from concierge.wake import wake_text
from featherweight import ChatInput


async def research() -> str:
    request = ResearchInput(
        location="Haidhausen", date_from=date.today() + timedelta(1), date_to=date.today() + timedelta(7), provider_sleep_seconds=0
    )
    job_id = await deps.client.submit(Researcher, request)
    assert (await deps.client.wait(job_id, timeout=30)).status.value == "SUCCESS"
    return job_id


async def reply(wake: str) -> str:
    run = deps.runner.stream(Concierge, ChatInput.from_langchain([HumanMessage(wake)]))
    return "".join([getattr(e, "delta", "") async for e in run if e.type == "TEXT_MESSAGE_CONTENT"])


async def test_chat_hears_a_finished_research(stack):
    job_id = await research()
    text = await wake_text(job_id, "completed")
    assert 'status="SUCCESS"' in text
    assert "The research finished" in await reply(text)


async def test_chat_hears_a_failed_job_and_what_it_reported(stack):
    job_id = await research()
    result = (await deps.client.result(Researcher, job_id)).shortlist[0]
    prepare = PrepareInput(
        research_job_id=job_id, provider_id=result.provider.id, slot_id=result.slots[0].id, simulate_failure=True
    )
    failed = await deps.client.submit(prepare_booking, prepare, resumable=True)
    assert (await deps.client.wait(failed, timeout=30)).status.value == "FAILED"
    text = await wake_text(failed, "failed")
    assert 'status="FAILED"' in text and "Progress notes from the job" in text and "Briefing ready" in text
    answer = await reply(text)
    assert "The research failed" in answer and "Retry" in answer
