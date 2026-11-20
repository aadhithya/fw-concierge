"""The two typed agents of the research pipeline. They propose; the validators and `check_output` have the last word.
(The chat agent that talks to the user is in chat.py.)"""

from datetime import date
from typing import ClassVar, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from concierge import deps
from concierge.domain import Provider, ProviderLookupError, SearchRequest
from concierge.models import model_for
from featherweight import AgentBase, AgentInput, AgentOutput, ModelSettings

# ------------------------------------------------------------------------------------------------------------ researcher

# Demo failure: while the "simulate outage" switch is on (see the UI), availability lookups for these providers fail.
OUTAGE_PROVIDERS = {"p01", "p07"}


@tool
async def check_availability(provider_id: str, date_from: str, date_to: str) -> str:
    """List a provider's open appointment slots between two ISO dates (YYYY-MM-DD). One line per slot: '<slot_id> | <start>'."""
    # The agent reaches availability only through the AvailabilityService interface, never the database directly.
    if provider_id in OUTAGE_PROVIDERS and await deps.repo.outage():
        raise ProviderLookupError(f"availability service unavailable for {provider_id}")
    slots = await deps.availability.slots(provider_id, date.fromisoformat(date_from), date.fromisoformat(date_to))
    return "\n".join(f"{s.id} | {s.starts_at:%Y-%m-%d %H:%M}" for s in slots) or "no open slots"


class ResearchInput(AgentInput):
    request: SearchRequest
    provider: Provider


class Findings(AgentOutput):  # flat, with defaults
    fit: Literal["strong", "partial", "weak"] = "weak"
    matched: list[str] = []  # the user's preferences this provider meets, in plain words
    concerns: list[str] = []  # preferences it does not meet
    slot_ids: list[str] = []  # slot ids returned by check_availability, nothing else
    availability_checked: bool = False  # false if the lookup failed


class ProviderResearcher(AgentBase):
    name: str = "provider_researcher"
    description: str = "Checks one provider against the request and looks up its availability"
    version: str = "1"
    prompt: str = (
        "You research ONE physiotherapy provider for a request. Compare the provider's attributes (tags, evenings, weekends, "
        "home visits, accessibility, price band, languages) with the request's preferences, listing what matches in `matched` "
        "and what does not in `concerns`. Then call check_availability for the request's date window and copy the slot ids it "
        "returns into slot_ids (never make one up). Set availability_checked=true only if the lookup worked. fit is 'strong' "
        "when every preference is met, 'partial' when some are, 'weak' when none are or there are no slots."
    )
    model: ModelSettings = Field(default_factory=lambda: model_for("researcher"))
    tools: list = [check_availability]
    input_model: ClassVar[type[AgentInput]] = ResearchInput
    output_model: ClassVar[type[AgentOutput]] = Findings

    def check_output(self, agent_input, output: Findings):
        # A failed lookup must FAIL this run (not succeed with an empty answer), so the job can see which providers failed.
        if not output.availability_checked:
            raise ValueError("availability could not be checked")


# ------------------------------------------------------------------------------------------------------------- evaluator


class Candidate(BaseModel):
    provider_id: str
    name: str
    price_band: int
    fit: str
    matched: list[str]
    concerns: list[str]
    slot_ids: list[str]


class EvalInput(AgentInput):
    request: SearchRequest
    candidates: list[Candidate]


class Evaluation(AgentOutput):  # flat lists, with ids
    ranked_provider_ids: list[str] = []  # best first, at most 3
    reasons: list[str] = []  # each starts with '<provider_id>: ' and cites that provider's known attributes
    slot_ids: list[str] = []  # slots to offer, taken from that provider's candidate slots
    summary: str = ""


class Evaluator(AgentBase):
    name: str = "evaluator"
    description: str = "Ranks the researched providers and picks slots to offer"
    version: str = "1"
    prompt: str = (
        "Pick up to 3 providers from the candidates that best fit the request, best first (ranked_provider_ids). Skip weak "
        "fits. For each give at least one reason as '<provider_id>: <reason>', citing only attributes in the candidate, and "
        "up to 3 of ITS slot ids in slot_ids. Use only ids from the input. If nothing suits the request, return an empty "
        "ranking and say so in summary. Never invent a provider or a slot."
    )
    model: ModelSettings = Field(default_factory=lambda: model_for("evaluator"))
    input_model: ClassVar[type[AgentInput]] = EvalInput
    output_model: ClassVar[type[AgentOutput]] = Evaluation

    def check_output(self, agent_input: EvalInput, output: Evaluation):
        # The model only proposes: every id it returns must exist in the input, and every pick needs a reason and a slot.
        known = {c.provider_id: c for c in agent_input.candidates}
        if len(output.ranked_provider_ids) > 3 or any(p not in known for p in output.ranked_provider_ids):
            raise ValueError("ranked_provider_ids must be at most 3 ids from the candidates")
        for pid in output.ranked_provider_ids:
            if known[pid].fit == "weak" or not known[pid].slot_ids:
                raise ValueError(f"{pid} is a weak fit or has no slots")
            if not any(r.startswith(f"{pid}: ") for r in output.reasons):
                raise ValueError(f"{pid} needs a reason written as '{pid}: ...'")
            if not any(s in known[pid].slot_ids for s in output.slot_ids):
                raise ValueError(f"{pid} needs at least one of its own slot ids")
        allowed = {s for p in output.ranked_provider_ids for s in known[p].slot_ids}
        if any(s not in allowed for s in output.slot_ids):
            raise ValueError("slot_ids must come from the ranked providers' candidate slots")
        if any(r.split(":")[0] not in output.ranked_provider_ids for r in output.reasons):
            raise ValueError("a reason names a provider that is not ranked")
