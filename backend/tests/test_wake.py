"""Waking the chat: the message the chat gets when a job ends, and how the chat answers it (demo models)."""

import json
import time
from datetime import date, timedelta

import pytest
from featherweight import ChatInput
from featherweight.adapters import agui
from langchain_core.messages import AIMessage, HumanMessage

from concierge import demo_models, deps
from concierge.booking_prep import PrepareInput, prepare_booking
from concierge.chat import Concierge
from concierge.client import provider_sleep
from concierge.research import Researcher, ResearchInput
from concierge.wake import delivered, noting_delivered, wake_text


async def research() -> str:
    request = ResearchInput(
        location="Haidhausen",
        date_from=date.today() + timedelta(1),
        date_to=date.today() + timedelta(7),
        provider_sleep_seconds=0,
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


@pytest.mark.parametrize("model_goes_on", [True, False])
async def test_no_second_wake_for_a_result_the_turn_already_got(stack, monkeypatch, model_goes_on):
    """The research ends while the chat turn is still working. If the model is called again, that turn receives the result and
    no wake may follow. If the turn ends with that reply, the turn never got it and the wake is still needed."""
    original = demo_models.chat

    def slow_chat(messages):
        if any(m.type == "human" and str(m.content).startswith("<background_result") for m in messages):
            return AIMessage(content="I already have the research result.")
        if messages[-1].type == "tool" and "job_id" in str(messages[-1].content):
            time.sleep(3)  # the model is busy for longer than the research takes
            if model_goes_on:  # ... and then makes another tool call, so it is called again
                return AIMessage(content="", tool_calls=[{"name": "current_date", "args": {}, "id": "again"}])
        if messages[-1].type == "tool" and messages[-1].name == "current_date":
            return AIMessage(content="Started.")
        return original(messages)

    monkeypatch.setattr(demo_models, "chat", slow_chat)
    provider_sleep.set(0)
    request = ChatInput.from_langchain([HumanMessage("Back pain, evening, Haidhausen next week")])
    run = deps.runner.stream(Concierge, request)
    events = [piece async for piece in noting_delivered(run, agui.encode(run))]
    sent = [json.loads(piece.removeprefix("data: ")) for piece in events]
    job_id = next(e["value"]["job_id"] for e in sent if e["type"] == "CUSTOM" and e["name"] == "background_started")
    assert (await deps.client.wait(job_id, timeout=30)).status.value == "SUCCESS"
    assert (job_id in delivered) is model_goes_on
