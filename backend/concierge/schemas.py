"""The request bodies of the API's endpoints (api.py), as pydantic models. The API checks them before an endpoint runs."""

from pydantic import BaseModel, Field


class RetryResearchIn(BaseModel):
    """POST /api/jobs/{id}/retry. Optional: the UI's current provider-service delay for the new research."""

    provider_sleep_seconds: float | None = Field(default=None, ge=0, le=20)  # the demo control, as the UI has it now


class PrepareIn(BaseModel):
    """POST /api/preparations. The research the user picked from, the provider and slot they chose, and the demo failure flag."""

    job_id: str  # the research job whose shortlist the user picked from
    provider_id: str
    slot_id: str
    simulate_failure: bool = False  # demo: the job fails after its first agent


class RetryPreparationIn(BaseModel):
    """POST /api/preparations/{id}/retry. Optional: whether the resumed preparation should fail again (the UI's current flag)."""

    simulate_failure: bool = False


class BookingIn(BaseModel):
    """POST /api/bookings. The explicit confirmation: which research, provider and slot, with an idempotency key."""

    job_id: str
    provider_id: str
    slot_id: str
    idempotency_key: str  # the same key always returns the same booking
