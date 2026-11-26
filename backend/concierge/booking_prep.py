"""The "prepare booking" job: a second, resumable job, started by the user from a button.

Two agents run one after the other: the first works out how the chosen provider and slot fit the request, the second
turns that into the confirmation text shown before the user confirms. If the demo failure parameter is on, the job fails AFTER
the first agent. Retrying it is a *resume* (`resume_from`): the first agent's run is reused (no model call, zero tokens) and
only the second agent runs again. Booking itself is not here: it stays a plain application operation after an explicit confirm.
"""

from typing import ClassVar

from featherweight import AgentBase, AgentInput, AgentOutput, JobContext, ModelSettings, RunStatus, job
from pydantic import BaseModel, Field

from concierge import deps
from concierge.domain import Provider, SearchRequest, Slot
from concierge.models import model_for


class PrepareInput(BaseModel):
    research_job_id: str  # the research whose request and shortlist this belongs to
    provider_id: str
    slot_id: str
    simulate_failure: bool = False  # demo: fail after the first agent, so the retry can be shown as a resume


# ---------------------------------------------------------------------------------------------------------- agent 1: briefer


class BriefInput(AgentInput):
    request: SearchRequest
    provider: Provider
    slot: Slot


class Briefing(AgentOutput):  # flat lists, with defaults
    matches: list[str] = []  # how the choice meets the request
    concerns: list[str] = []  # where it does not
    before_you_go: list[str] = []  # short practical notes


class BookingBriefer(AgentBase):
    name: str = "booking_briefer"
    description: str = "Works out how a chosen provider and slot fit the user's request"
    version: str = "1"
    prompt: str = (
        "Compare the chosen provider and appointment slot with the user's request. List in `matches` what the choice meets and "
        "in `concerns` what it does not, using only the provider's known attributes. Add up to 3 short practical notes in "
        "before_you_go. Do not give medical advice."
    )
    model: ModelSettings = Field(default_factory=lambda: model_for("briefer"))
    input_model: ClassVar[type[AgentInput]] = BriefInput
    output_model: ClassVar[type[AgentOutput]] = Briefing

    def check_output(self, agent_input, output: Briefing):
        if not output.matches and not output.concerns:  # an empty comparison is not an answer
            raise ValueError("list at least one match or one concern")


# ------------------------------------------------------------------------------------------------------ agent 2: confirmation


class ConfirmInput(AgentInput):
    provider: Provider
    slot: Slot
    briefing: Briefing


class Confirmation(AgentOutput):
    text: str = ""  # two or three sentences for the user to read before confirming


class ConfirmationWriter(AgentBase):
    name: str = "confirmation_writer"
    description: str = "Writes the short confirmation text shown before a booking"
    version: str = "1"
    prompt: str = (
        "Write 2 or 3 plain sentences for the user to read before confirming: the provider's name, the day and time of the "
        "slot, and the most useful match or note from the briefing. Say that this is a simulated booking."
    )
    model: ModelSettings = Field(default_factory=lambda: model_for("writer"))
    input_model: ClassVar[type[AgentInput]] = ConfirmInput
    output_model: ClassVar[type[AgentOutput]] = Confirmation

    def check_output(self, agent_input: ConfirmInput, output: Confirmation):
        if agent_input.provider.name not in output.text:  # the text must be about the chosen provider
            raise ValueError("the text must name the provider")


# ----------------------------------------------------------------------------------------------------------------- the job


class Preparation(BaseModel):
    provider: Provider  # verified: read from the catalogue
    slot: Slot  # verified: read from the availability service
    briefing: Briefing  # model-written
    confirmation: str  # model-written


class PreparationFailed(RuntimeError):
    pass


@job(timeout=120)
async def prepare_booking(ctx: JobContext, input: PrepareInput) -> Preparation:
    """Prepare the booking of one chosen provider and slot: brief the choice, then write the confirmation text."""
    repo = deps.repo
    note = lambda text: repo.add_progress(ctx.job_id, text)  # noqa: E731  (the progress lines the UI shows)
    await repo.save_preparation_input(ctx.job_id, input.research_job_id, input.provider_id, input.slot_id)  # a retry reads this

    criteria = await repo.get_request(input.research_job_id)
    provider, slot = await deps.catalog.get(input.provider_id), await deps.availability.get(input.slot_id)
    if criteria is None or provider is None or slot is None:
        raise PreparationFailed("unknown request, provider or slot")
    request = SearchRequest.model_validate(criteria)

    await note("Checking the provider and slot against your request")
    briefing = await ctx.run(BookingBriefer, BriefInput(request=request, provider=provider, slot=slot))
    if briefing.status != RunStatus.SUCCESS:
        raise PreparationFailed("could not brief the choice")
    # `reused` is true when this is a resumed job and this step had already succeeded: nothing was run again.
    await note("Briefing reused from the earlier attempt" if briefing.reused else "Briefing ready")

    # Demo parameter: fail here, AFTER the first agent. A resumed job reuses the briefing and continues from this point.
    if input.simulate_failure:
        raise PreparationFailed("the confirmation service is unavailable")

    await note("Writing the confirmation")
    written = await ctx.run(ConfirmationWriter, ConfirmInput(provider=provider, slot=slot, briefing=briefing.output))
    if written.status != RunStatus.SUCCESS:
        raise PreparationFailed("could not write the confirmation")

    result = Preparation(provider=provider, slot=slot, briefing=briefing.output, confirmation=written.output.text)
    await repo.save_preparation_result(ctx.job_id, result.model_dump(mode="json"))
    await note("Ready for your confirmation")
    return result
