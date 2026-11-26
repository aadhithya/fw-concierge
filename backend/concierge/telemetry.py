"""OpenTelemetry setup. featherweight emits spans through the OTel API (`OTelObserver`); this configures the SDK and exporter."""

import logging

from featherweight import OTelObserver
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from concierge.config import OTLP_ENDPOINT

log = logging.getLogger(__name__)


def setup(service_name: str) -> list[OTelObserver]:
    """Start exporting traces to the collector. Returns the observers to give the client and the runner (none if tracing is off)."""
    if not OTLP_ENDPOINT:
        return []
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{OTLP_ENDPOINT}/v1/traces")))
    trace.set_tracer_provider(provider)
    log.info("tracing to %s as %s", OTLP_ENDPOINT, service_name)
    return [OTelObserver()]
