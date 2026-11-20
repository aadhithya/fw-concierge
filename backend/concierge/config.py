"""Configuration, from environment variables only."""

import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://concierge:concierge@localhost:5432/concierge")
DEMO_MODE = os.environ.get("DEMO_MODE", "1") == "1"  # 1: deterministic fake models, no API key. 0: live Gemini
OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")  # empty: tracing off
STATIC_DIR = os.environ.get("STATIC_DIR", "/app/static")
