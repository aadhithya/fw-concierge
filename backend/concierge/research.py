"""The background research job: discover, research in parallel, evaluate, assemble the shortlist.

Plain async Python decides the order. Agents propose; this code verifies against application data and builds the result.
It must be safe to run twice (a queue delivers at least once): every write is an upsert.
"""

from datetime import date

from pydantic import BaseModel

from concierge import deps
from concierge.agents import (
    Candidate,
    EvalInput,
    Evaluator,
    ProviderResearcher,
    ResearchInput,
)
from concierge.domain import Provider, SearchRequest, Slot
from featherweight import JobContext, RunStatus, job


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
