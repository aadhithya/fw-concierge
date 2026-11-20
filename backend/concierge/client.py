"""The job client the application uses. A `JobClient` plus two things only the application can do."""

import contextvars

from concierge import deps
from concierge.domain import SearchRequest
from concierge.research import ResearchInput
from featherweight import JobClient

# The chat's model builds the job's input, so a demo control from the UI cannot come from the model. The chat endpoint notes it for
# this request, and this client applies it when the chat's `start_background` submits the research.
provider_sleep: contextvars.ContextVar[float | None] = contextvars.ContextVar("provider_sleep", default=None)


class ControlledJobClient(JobClient):
    """JobClient that also (1) applies the UI's delay control to a research the chat starts, and (2) keeps the request of a research.

    featherweight keeps no job input, so the application keeps the request (`app.appointment_requests`): the UI shows it, Retry
    resubmits it, and the booking preparation reads it.
    """

    async def submit(self, job, input, **kwargs):
        sleep = provider_sleep.get()
        if sleep is not None and isinstance(input, ResearchInput):
            input = input.model_copy(update={"provider_sleep_seconds": sleep})
        job_id = await super().submit(job, input, **kwargs)
        if isinstance(input, ResearchInput):
            await deps.repo.save_request(job_id, SearchRequest.model_validate(input.model_dump()))
            await deps.repo.add_progress(job_id, "Research started: the agent is asking the provider service")
        return job_id
