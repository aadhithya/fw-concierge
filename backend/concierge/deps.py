"""The application services that the jobs, tools and endpoints use, in one place.

Each process fills in what it needs once at startup: the worker sets `catalog`, `availability` and `repo` (see worker.py),
the API sets `repo`, `client` and `runner` (see api.py). Tests can put fakes here.
"""

from featherweight import AgentRunner, JobClient

from concierge.domain import AvailabilityService, ProviderCatalog, Repository

catalog: ProviderCatalog
availability: AvailabilityService
repo: Repository
client: JobClient  # submits jobs (API only)
runner: AgentRunner  # runs the chat agent (API only)
