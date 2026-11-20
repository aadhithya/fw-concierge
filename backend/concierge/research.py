"""The research pipeline: a job, and the two agents it runs.

The job (`research_providers`) is plain async Python that decides the order: discover the providers, research each one with
an agent in parallel, evaluate them with a second agent, then build the shortlist. The agents propose; this code verifies
everything against application data. A job must be safe to run twice (a queue delivers at least once): writes are upserts.
"""

from datetime import date
from typing import ClassVar, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from concierge import deps
from concierge.domain import Provider, SearchRequest, Slot
from concierge.models import model_for
from featherweight import AgentBase, AgentInput, AgentOutput, JobContext, ModelSettings, RunStatus, job

# ------------------------------------------------------------------------------------------------ agent 1: researcher

@tool
async def check_availability(provider_id: str, date_from: str, date_to: str) -> str:
    """List a provider's open appointment slots between two ISO dates (YYYY-MM-DD). One line per slot: '<slot_id> | <start>'."""
    # The agent reaches availability only through the AvailabilityService interface, never the database directly.
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


# ------------------------------------------------------------------------------------------------- agent 2: evaluator


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


# ----------------------------------------------------------------------------------------------------------- the job


class ShortlistItem(BaseModel):
    rank: int
    provider: Provider  # verified: read from the catalogue
    slots: list[Slot]  # verified: read from the availability service
    reasons: list[str]  # model-generated explanation, tied to the provider's attributes
    fit: str
    matched: list[str]
    concerns: list[str]


class ResearchResult(BaseModel):
    request: SearchRequest
    shortlist: list[ShortlistItem]
    summary: str  # model-generated
    considered: int


class ResearchFailed(RuntimeError):
    pass


def _window(request: SearchRequest) -> tuple[date, date]:
    return request.date_from, request.date_to


@job(timeout=180)
async def research_providers(ctx: JobContext, input: SearchRequest) -> ResearchResult:
    """Research the physiotherapy providers that fit a search request: check each one's availability and shortlist the best."""
    repo, request = deps.repo, input  # the input IS the typed search request
    note = lambda text: repo.add_progress(ctx.job_id, text)  # noqa: E731  (the progress lines the UI shows)

    await repo.save_request(ctx.job_id, request)  # first: the app can show the request while the job runs
    await note("Searching the provider catalogue")
    # Step 1: discovery is plain code over the catalogue service; no agent is needed to filter a list.
    providers = await deps.catalog.discover(request)
    await note(f"Found {len(providers)} candidate providers. Researching them in parallel")

    # Step 2: one researcher agent per provider, all at once. Their runs and traces belong to this job.
    results = await ctx.run_many(ProviderResearcher, [ResearchInput(request=request, provider=p) for p in providers])

    failed = [p for p, r in zip(providers, results) if r.status != RunStatus.SUCCESS]
    for p in failed:
        await note(f"Availability lookup failed for {p.name}")
    if failed:  # the job fails visibly, and says which providers
        raise ResearchFailed(f"availability lookup failed for {', '.join(p.name for p in failed)}")
    await note("All providers checked. Evaluating")

    # Step 3: one evaluator agent compares what the researchers found and ranks the providers.
    candidates = [
        Candidate(
            provider_id=p.id, name=p.name, price_band=p.price_band, fit=r.output.fit, matched=r.output.matched,
            concerns=r.output.concerns, slot_ids=r.output.slot_ids,
        )
        for p, r in zip(providers, results)
    ]
    evaluation = await ctx.run(Evaluator, EvalInput(request=request, candidates=candidates))
    if evaluation.status != RunStatus.SUCCESS:
        raise ResearchFailed("the evaluation did not produce a valid shortlist")
    out = evaluation.output

    # Step 4: the model only chose ids. The result is built from the catalogue and the availability service, so the
    # provider and slot data is verified, and only `reasons` and `summary` are model-written.
    by_id = {c.provider_id: c for c in candidates}
    shortlist: list[ShortlistItem] = []
    for pid in out.ranked_provider_ids:  # hydrate from application data: the model only chose ids
        provider = await deps.catalog.get(pid)
        open_slots = await deps.availability.slots(pid, *_window(request))
        offered = [s for s in open_slots if s.id in out.slot_ids]
        if provider and offered:
            c = by_id[pid]
            reasons = [r.split(": ", 1)[1] for r in out.reasons if r.startswith(f"{pid}: ")]
            shortlist.append(
                ShortlistItem(
                    rank=len(shortlist) + 1, provider=provider, slots=offered, reasons=reasons, fit=c.fit,
                    matched=c.matched, concerns=c.concerns,
                )
            )
    summary = out.summary if shortlist else "No suitable provider was found for this request."
    result = ResearchResult(request=request, shortlist=shortlist, summary=summary, considered=len(providers))
    await repo.save_result(ctx.job_id, result.model_dump(mode="json"))  # an upsert: a job must be safe to run twice
    await note(f"Done: {len(shortlist)} providers shortlisted")
    return result
