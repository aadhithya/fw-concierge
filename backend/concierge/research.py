"""The background research job: discover, research in parallel, evaluate, assemble the shortlist.

Plain async Python decides the order. Agents propose; this code verifies against application data and builds the result.
It must be safe to run twice (a queue delivers at least once): every write is an upsert.
"""

from datetime import date

from pydantic import BaseModel

from concierge.agents import (
    AvailabilityDeps,
    Candidate,
    EvalInput,
    Evaluator,
    ProviderResearcher,
    ResearchInput,
    outage_flag,
)
from concierge.domain import AvailabilityService, Provider, ProviderCatalog, Repository, SearchRequest, Slot
from featherweight import JobContext, RunStatus, job


class Deps:
    """The application services the job uses, set once at startup by the worker (or a test)."""

    catalog: ProviderCatalog
    availability: AvailabilityService
    repo: Repository


class ResearchJobInput(BaseModel):
    request_id: str
    request: SearchRequest
    simulate_outage: bool = False  # demo: availability lookups fail for two fixed providers


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
    reused: int  # provider checks reused from an earlier attempt (a resumed job)


class ResearchFailed(RuntimeError):
    pass


def _window(request: SearchRequest) -> tuple[date, date]:
    return request.date_from, request.date_to


@job(timeout=180)
async def research_providers(ctx: JobContext, input: ResearchJobInput) -> ResearchResult:
    repo, request = Deps.repo, input.request
    note = lambda text: repo.add_progress(ctx.job_id, text)  # noqa: E731

    await note("Searching the provider catalogue")
    providers = await Deps.catalog.discover(request)
    await note(f"Found {len(providers)} candidate providers. Researching them in parallel")

    AvailabilityDeps.service = Deps.availability
    outage_flag.set(input.simulate_outage)
    results = await ctx.run_many(ProviderResearcher, [ResearchInput(request=request, provider=p) for p in providers])

    failed = [p for p, r in zip(providers, results) if r.status != RunStatus.SUCCESS]
    reused = sum(1 for r in results if r.reused)
    for p in failed:
        await note(f"Availability lookup failed for {p.name}")
    if reused:
        await note(f"Reused {reused} provider checks from the earlier attempt")
    if failed:  # the other providers' runs are kept: a resume reruns only these
        raise ResearchFailed(f"availability lookup failed for {', '.join(p.name for p in failed)}")
    await note("All providers checked. Evaluating")

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

    by_id = {c.provider_id: c for c in candidates}
    shortlist: list[ShortlistItem] = []
    for pid in out.ranked_provider_ids:  # hydrate from application data: the model only chose ids
        provider = await Deps.catalog.get(pid)
        open_slots = await Deps.availability.slots(pid, *_window(request))
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
    result = ResearchResult(request=request, shortlist=shortlist, summary=summary, considered=len(providers), reused=reused)
    await repo.save_result(ctx.job_id, input.request_id, result.model_dump(mode="json"))
    await note(f"Done: {len(shortlist)} providers shortlisted")
    return result
