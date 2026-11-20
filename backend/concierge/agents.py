"""The three typed agents of the pipeline. They propose; the validators and `check_output` have the last word."""

import contextvars
import json
from datetime import date
from typing import ClassVar, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from concierge.domain import NEIGHBOURHOODS, REGION, AvailabilityService, Provider, ProviderLookupError, SearchRequest
from concierge.models import model_for
from featherweight import AgentBase, AgentInput, AgentOutput, ModelSettings

# ---------------------------------------------------------------------------------------------------------------- intake


class IntakeInput(AgentInput):
    conversation: str  # the user's request, and any earlier question and answer
    today: date


class IntakeOutput(AgentOutput):  # also carries `open_questions`
    service_category: Literal["physiotherapy"] | None = None
    location: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    preferences: list[str] = []

    def to_request(self) -> SearchRequest:
        return SearchRequest.model_validate(self.model_dump(exclude={"open_questions"}))


class IntakeAgent(AgentBase):
    name: str = "intake"
    description: str = "Turns a natural-language appointment request into a typed search request"
    version: str = "1"
    prompt: str = (
        f"You book physiotherapy appointments in {REGION}, a fictional region with these neighbourhoods: "
        f"{', '.join(NEIGHBOURHOODS)}. From the conversation, extract the service category (physiotherapy only), the "
        f"location (a neighbourhood or '{REGION}' for anywhere), the date window (date_from and date_to, using `today` to "
        "resolve words such as 'next week') and preferences (short phrases such as 'back pain', 'evening', 'home visit'). "
        "NEVER invent a missing value. If the location or the date window is missing or unclear, leave it empty and ask one "
        "short, focused question in open_questions."
    )
    model: ModelSettings = Field(default_factory=lambda: model_for("intake"))
    input_model: ClassVar[type[AgentInput]] = IntakeInput
    output_model: ClassVar[type[AgentOutput]] = IntakeOutput
    allow_user_questions: bool = True

    def check_output(self, agent_input, output: IntakeOutput):
        if output.open_questions:
            return  # asking is a valid answer
        missing = [f for f in ("service_category", "location", "date_from", "date_to") if getattr(output, f) is None]
        if missing:
            raise ValueError(f"missing {missing}: ask a question in open_questions instead of leaving them empty")
        if output.location != REGION and output.location not in NEIGHBOURHOODS:
            raise ValueError(f"location must be {REGION!r} or one of {NEIGHBOURHOODS}")
        if output.date_to < output.date_from or output.date_from < agent_input.today:
            raise ValueError("the date window must start today or later and end after it starts")


# ------------------------------------------------------------------------------------------------------------ researcher

# A demo failure: with the outage flag on, these providers' availability lookups fail.
OUTAGE_PROVIDERS = {"p02", "p06"}
outage_flag: contextvars.ContextVar[bool] = contextvars.ContextVar("outage_flag", default=False)


class AvailabilityDeps:
    """Set once per process (worker); the tool reaches availability only through the service interface."""

    service: AvailabilityService | None = None


@tool
async def check_availability(provider_id: str, date_from: str, date_to: str) -> str:
    """List a provider's open appointment slots between two ISO dates (YYYY-MM-DD). One line per slot: '<slot_id> | <start>'."""
    if outage_flag.get() and provider_id in OUTAGE_PROVIDERS:
        raise ProviderLookupError(f"availability service unavailable for {provider_id}")
    assert AvailabilityDeps.service is not None, "availability service not configured"
    slots = await AvailabilityDeps.service.slots(provider_id, date.fromisoformat(date_from), date.fromisoformat(date_to))
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
        if not output.availability_checked:  # the run fails, the job sees it, and a resume reruns only this provider
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


def parse_slot_lines(text: str) -> list[str]:
    return [line.split("|")[0].strip() for line in text.splitlines() if "|" in line]


__all__ = ["IntakeAgent", "ProviderResearcher", "Evaluator", "json"]
