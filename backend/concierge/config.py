"""Configuration, from environment variables only."""

import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://concierge:concierge@localhost:5432/concierge")
DEMO_MODE = os.environ.get("DEMO_MODE", "1") == "1"  # 1: deterministic fake models, no API key. 0: live Gemini
LLM = os.environ.get("LLM", "gemini")  # live mode only: "gemini" (gemini-3.5-flash-lite) or "gemma" (gemma-4-31b-it)
OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
PROVIDER_SERVICE_URL = os.environ.get("PROVIDER_SERVICE_URL", "http://localhost:8001/mcp")  # the MCP server the research agent uses  # empty: tracing off
STATIC_DIR = os.environ.get("STATIC_DIR", "/app/static")
