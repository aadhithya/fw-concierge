"""Every agent must build with every model choice: featherweight checks models, efforts and output types when an agent is built.
It calls no model and needs no key (featherweight's migration guide asks for this test)."""

import pytest
from ag_ui.core import ImageInputContent, InputContentDataSource, TextInputContent, UserMessage
from featherweight import AgentRunner, AttachmentLimitError, ChatInput, SqliteDatabase

from concierge import models
from concierge.booking_prep import BookingBriefer, ConfirmationWriter
from concierge.chat import Concierge
from concierge.research import Researcher


@pytest.mark.parametrize("choice", ["demo", "gemini", "gemma"])
@pytest.mark.parametrize("agent", [Concierge, Researcher, BookingBriefer, ConfirmationWriter])
def test_the_agent_builds(agent, choice, monkeypatch):
    monkeypatch.setattr(models, "DEMO_MODE", choice == "demo")
    monkeypatch.setattr(models, "LLM", choice)
    assert agent().model


async def test_the_chat_refuses_a_file():
    """featherweight allows 10 files unless the agent says otherwise: a message with one must be refused before any model call."""
    image = ImageInputContent(source=InputContentDataSource(value="aGVsbG8=", mime_type="image/png"))
    message = UserMessage(id="1", content=[TextInputContent(text="Look at this"), image])
    async with SqliteDatabase(":memory:") as db:
        with pytest.raises(AttachmentLimitError):
            async for _ in AgentRunner(db).stream(Concierge, ChatInput(messages=[message])):
                pass
