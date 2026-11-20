"""One end-to-end smoke test of the demo flow, in-process, on the fake models (DEMO_MODE=1, the default). No real model call.

The chat starts the research as a background agent, a worker runs it, a resumable two-agent job fails after its first agent
and resumes, and booking is idempotent. Runs in its own database (`concierge_test`), like test_adapters.py.
"""

import pytest
from langchain_core.messages import HumanMessage

from concierge import deps
from concierge.booking_prep import PrepareInput, prepare_booking
from concierge.chat import Concierge
from featherweight import ChatInput


async def test_demo_flow(stack):
    # 1. The chat asks when something is missing, and starts the research (a background agent) when it has everything.
    async def say(text):
        return [e async for e in deps.runner.stream(Concierge, ChatInput.from_langchain([HumanMessage(text)]))]

    assert not any(e.type == "CUSTOM" for e in await say("I need a physio soon"))  # asked a question instead
    events = await say("Back pain, evening, Haidhausen next week")
    job_id = next(e.value["job_id"] for e in events if e.type == "CUSTOM" and e.name == "background_started")

    # 2. A worker runs it: a typed shortlist of verified providers and slots.
    assert (await deps.client.wait(job_id, timeout=30)).status.value == "SUCCESS"
    result = await deps.repo.get_result(job_id)
    pick = result["shortlist"][0]
    assert pick["provider"]["id"] and pick["slots"] and pick["reasons"]

    # 3. The preparation job fails after its first agent when the outage switch is on, and a retry RESUMES it.
    await deps.repo.set_outage(True)
    prepare = PrepareInput(research_job_id=job_id, provider_id=pick["provider"]["id"], slot_id=pick["slots"][0]["id"])
    failed = await deps.client.submit(prepare_booking, prepare, resumable=True)
    assert (await deps.client.wait(failed, timeout=30)).status.value == "FAILED"
    await deps.repo.set_outage(False)
    resumed = await deps.client.submit(prepare_booking, prepare, resumable=True, resume_from=failed)
    assert (await deps.client.wait(resumed, timeout=30)).status.value == "SUCCESS"
    assert "Briefing reused from the earlier attempt" in [p["message"] for p in await deps.repo.progress(resumed)]

    # 4. Booking is idempotent: the same key returns the same booking, and the slot can only be taken once.
    book = dict(job_id=job_id, provider_id=prepare.provider_id, slot_id=prepare.slot_id)
    first, created = await deps.repo.book(idempotency_key="k1", **book)
    again, created_again = await deps.repo.book(idempotency_key="k1", **book)
    assert created and not created_again and first["id"] == again["id"]
    with pytest.raises(Exception, match="taken"):
        await deps.repo.book(idempotency_key="k2", **book)
