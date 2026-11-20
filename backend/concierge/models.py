"""Which model an agent runs on. Demo mode: a deterministic offline fake. Live mode: Gemini flash-lite (default), or the
big hosted Gemma with LLM=gemma. Both use GOOGLE_API_KEY."""

from typing import Any, ClassVar

from pydantic import Field

from concierge.config import DEMO_MODE, LLM
from featherweight import Gemini, Gemma, ModelSettings


class DemoSettings(ModelSettings):
    """Model settings that build the rule-based fake in `demo_models.py`."""

    provider: ClassVar[str] = "demo"
    model: str = "demo-rules"
    role: str
    chat: Any = Field(default=None, exclude=True)

    def build(self):
        from concierge.demo_models import RuleModel

        return RuleModel(role=self.role)


def model_for(role: str) -> ModelSettings:
    if DEMO_MODE:
        return DemoSettings(role=role)
    if LLM == "gemma":
        return Gemma(model="gemma-4-31b-it", thinking="high")  # "high": it follows tool instructions better, and Gemma is free
    return Gemini(model="gemini-3.5-flash-lite", thinking="low")
