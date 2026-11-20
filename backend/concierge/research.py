"""The research agent: one agent, one MCP tool.

The chat starts this agent as a background agent (a worker runs it). Its only tool, `search_providers`, comes from an MCP server in
a container of its own (mcp.py): the tool takes a while and returns the matching providers with their open slots. The agent calls it
once and forwards what it returned as its result, which is what the research card shows.
"""

from typing import ClassVar

from pydantic import BaseModel, Field

from concierge.config import PROVIDER_SERVICE_URL
from concierge.domain import Provider, SearchRequest, Slot
from concierge.models import model_for
from featherweight import AgentBase, AgentInput, AgentOutput, HttpMCPServer, ModelSettings


class ResearchInput(AgentInput, SearchRequest):
    """What to research: the typed search request the chat extracted (location, dates, preferences), plus the demo delay."""


class ShortlistItem(BaseModel):
    rank: int
    provider: Provider
    slots: list[Slot]
    reasons: list[str]


class ResearchResult(AgentOutput):
    shortlist: list[ShortlistItem] = []  # the providers the tool returned, best first
    considered: int = 0  # how many providers the tool looked at
    summary: str = ""  # one sentence


class Researcher(AgentBase):
    name: str = "researcher"
    description: str = "Researches physiotherapy providers and their open slots for a search request, using the provider service"
    version: str = "1"
    prompt: str = (
        "Call providers_search_providers exactly once, with the request's location, date_from, date_to and preferences, and "
        "sleep_seconds set to provider_sleep_seconds from the input. It is slow: that is expected. Then return what it gave "
        "back as your result: shortlist is its providers, copied exactly with their slots and reasons; considered is its "
        "considered count; summary is one sentence. Never invent a provider or a slot. If it returned no providers, leave "
        "shortlist empty and say so in summary."
    )
    model: ModelSettings = Field(default_factory=lambda: model_for("researcher"))
    # An MCP server in a container of its own (mcp.py). Its one tool is bound to the model directly (discover=False).
    mcp_servers: list = [
        HttpMCPServer(
            name="providers",
            url=PROVIDER_SERVICE_URL,
            tools=("search_providers",),
            discover=False,
            timeout_s=45,
            description="The provider service: finds providers and their open slots",
        )
    ]
    input_model: ClassVar[type[AgentInput]] = ResearchInput
    output_model: ClassVar[type[AgentOutput]] = ResearchResult

    def check_output(self, agent_input, output: ResearchResult):
        if output.considered < 1:  # the tool always looks at some providers: a model that skipped it has nothing to forward
            raise ValueError("call providers_search_providers and return what it gave back")
        if len(output.shortlist) > 3 or any(not item.slots for item in output.shortlist):
            raise ValueError("shortlist is at most 3 providers, each with its slots, copied from the tool's answer")
