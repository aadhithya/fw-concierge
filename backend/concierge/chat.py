"""The chat agent: the part of the system the user talks to.

It is a featherweight `StreamingAgent`. The framework streams its words and its tool calls to the browser as AG-UI events
(`runner.stream()` + `agui.encode()`), so nothing here builds events by hand.

The research is a *background agent*: the framework gives the chat a `start_background` tool, checks the typed input
against the job's schema (`SearchRequest`: a missing or invalid value is refused with a message the model reads, and it asks
the user), submits the job to the queue, and returns the job id at once. A worker runs the job; the chat does not wait.
"""

from datetime import date

from langchain_core.tools import tool
from pydantic import Field

from concierge.domain import NEIGHBOURHOODS, REGION
from concierge.models import model_for
from concierge.research import research_providers
from featherweight import ModelSettings, StreamingAgent


@tool
async def current_date() -> str:
    """Today's date (YYYY-MM-DD). Use it to turn words like 'next week' or 'tomorrow' into dates."""
    return date.today().isoformat()


class Concierge(StreamingAgent):
    name: str = "concierge"
    description: str = "Helps a user find and book a physiotherapy appointment"
    version: str = "1"
    prompt: str = (
        f"You are a friendly concierge that finds physiotherapy appointments in {REGION}, a demo with fictional providers. "
        f"Neighbourhoods: {', '.join(NEIGHBOURHOODS)}. Gather the user's location (a neighbourhood, or {REGION} for anywhere) "
        "and a date window, plus any preferences. Use current_date to resolve relative dates. If the location or the dates are "
        "missing or unclear, ask ONE short question and wait: never guess. When you have both, start the research with "
        "start_background, then tell the user briefly what you understood and that the research has started. You cannot "
        "book: booking happens on the confirmation screen. Medical advice is out of scope. "
        "Later, a user message that starts with <background_result> is not typed by the user: it is the outcome of the research "
        "you started, sent by the application. If its status is SUCCESS, tell the user in two or three sentences which options "
        "came out on top (names, area, why) and that they can pick a slot in the booking pane; use only what the result says. "
        "If it is FAILED or CANCELLED, say plainly that the research failed, say what the progress notes report, and tell the "
        "user to press Retry on the research card. Do not start the research again yourself, and never invent providers or slots."
    )
    model: ModelSettings = Field(default_factory=lambda: model_for("chat"))
    tools: list = [current_date]
    background_agents: list[type] = [research_providers]  # a job class: run by a worker, found by name
