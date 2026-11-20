"""Which model an agent runs on. Live mode: Gemini flash-lite, nothing else. Demo mode: a deterministic offline fake."""

from typing import Any, ClassVar

from pydantic import Field

from concierge.config import DEMO_MODE
from featherweight import Gemini, ModelSettings


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
    return DemoSettings(role=role) if DEMO_MODE else Gemini(model="gemini-3.5-flash-lite", thinking="low")
