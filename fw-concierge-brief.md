# Capstone Brief: Appointment Concierge

**Project type:** Framework showcase\
**Primary purpose:** Demonstrate Featherweight in a realistic,
application-oriented agent system.\
**Target size:** A small local system that resembles a production
deployment, not a production booking platform.\
**Implementation approach:** Primarily AI-assisted development, guided
by this brief.

## 1. Problem statement

People often need help finding an appropriate service provider and
arranging an appointment. The information is spread across provider
listings, service descriptions, availability, and booking rules. A
conversational assistant can turn a natural-language request into a
shortlist of suitable providers and help the user make a booking.

Build a deliberately small appointment concierge for one fictional
service category (for example, physiotherapy). A user describes what
they need; the system gathers requirements, researches a small set of
providers, checks mock availability, presents options, and books only
after the user explicitly confirms.

The project is a showcase of Featherweight's agent execution and
application integration capabilities. It is not intended to be a real
marketplace or a general-purpose scheduling product.

## 2. Product boundaries

### In scope

-   One service category and one fictional city/region.
-   A small, seeded catalogue of approximately 10--20 providers.
-   Mock provider and availability data.
-   A conversational intake and shortlist experience.
-   A thin, usable web UI, implemented primarily with AI coding agents
    and existing component libraries rather than a bespoke design system.
-   Background research for requests that require comparing multiple
    providers.
-   Explicit user confirmation before a booking is created.
-   A locally runnable, multi-container Docker Compose deployment.
-   Basic persistence, job lifecycle visibility, and distributed
    tracing.

### Explicitly out of scope

-   Real provider integrations, real-world bookings, payments, insurance
    verification, or personal medical advice.
-   User registration, authentication, multi-tenancy, or role
    management.
-   A production-grade calendar, rescheduling workflow, reminders, or
    cancellation policy engine.
-   Mobile applications, a bespoke design system, or elaborate
    frontend polish.
-   Arbitrary web crawling or unrestricted browser automation.
-   Complex agent planning, autonomous booking, or agents making
    irreversible decisions.
-   Kubernetes, cloud deployment, high availability, autoscaling, or
    production security certification.
-   A general provider-management portal.

Use fictional data throughout. Make it clear in the UI and documentation
that appointments are simulated.

## 3. Primary user journey

1.  The user asks for an appointment in natural language, including any
    known preferences.
2.  The intake agent extracts a typed search request. If an essential
    detail is missing, the application asks a focused follow-up.
3.  The application submits a background research job.
4.  The worker discovers matching providers from the seeded catalogue
    and researches them in parallel.
5.  The system checks mock availability and evaluates the options
    against the user's requirements.
6.  The user sees a shortlist with concise explanations and available
    slots.
7.  The user selects a slot and explicitly confirms.
8.  The application creates a booking record and displays a
    confirmation.
9.  The user can inspect the research job's status and final result.

The research job may take long enough to demonstrate asynchronous
execution, but it should complete in a predictable, short local demo
(roughly tens of seconds, not hours).

The web UI should make the main user journey and background execution
easy to understand. UI implementation is expected to be AI-assisted:
prefer established chat components, templates, and design-system
primitives over building interaction patterns from scratch. AG-UI is
the default streaming protocol, so select components and adapters that
work with AG-UI directly where possible. If a library uses a different
streaming contract, keep any translation layer small and isolated.
Vercel's pre-built AI templates are also a valid starting point, provided
the chosen template can be connected cleanly to the application's
AG-UI-based backend.

## 4. Architecture constraints

Keep the deployment intentionally small:

-   **Web/API container:** Serves the user interface and API. It accepts
    requests, streams status/events, and reads persisted results.
-   **Worker container:** Runs submitted background research jobs. It
    uses the same application image with a different process/command.
-   **Postgres container:** Stores application records and the job/run
    persistence required by the chosen Featherweight adapters.
-   **Web UI:** A thin frontend that talks only to the application API
    and AG-UI stream. It should not depend on Featherweight internals.
-   **Optional mock-provider service:** Only add this if keeping
    provider APIs separate materially improves the demonstration.
    Otherwise, implement mock provider access as application services
    backed by seeded Postgres data.

Use Docker Compose to start the system. Do not add Redis merely because
it is common in production: use the queue implementation appropriate to
the Featherweight job design. Do not introduce extra infrastructure
unless a concrete feature requires it.

The web/API and worker should be separate processes and containers, but
can share one codebase and image. Configuration and secrets are supplied
through environment variables. Provide a `.env.example` with
placeholders, never real credentials.

The application owns its domain data. Featherweight owns agent execution
concerns. Keep those responsibilities visibly separate.

## 5. Functional features and definition of done

### F1. Appointment request intake

**Behaviour** - Accept a natural-language appointment request. - Extract
a typed request containing service category, location, date window, and
preferences. - Ask for clarification when a required field is missing. -
Show the interpreted request before or while starting research.

**Definition of done** - A Pydantic model defines the search request and
validates required fields. - At least three representative
natural-language requests produce valid structured requests. - At least
one ambiguous request triggers a clarification rather than silently
inventing a value. - Invalid or incomplete model output is handled
through the normal Featherweight validation/error path. - The user can
see the interpreted criteria.

**Not required** - Complex conversational memory or multi-session
personalisation. - A general-purpose natural-language date parser beyond
the supported date window.

### F2. Provider catalogue and mock integrations

**Behaviour** - Provide a small, seeded catalogue of fictional
providers. - Each provider has a name, service tags, location, short
description, and relevant attributes. - Provide mock availability slots
through an application-owned interface.

**Definition of done** - At least 10 providers and a useful spread of
attributes are seeded automatically. - Provider and availability access
go through application service interfaces, not direct database access
from agent prompts. - The mock availability interface can be replaced
without changing the agent orchestration. - The README explains that all
providers and slots are fictional.

**Not required** - A provider onboarding UI or external provider API
integrations. - Live calendar synchronisation.

### F3. Background provider research

**Behaviour** - Submit a research job after intake. - Discover candidate
providers, investigate them, check availability, and produce a
shortlist. - Run independent provider research concurrently where
appropriate. - Keep the user-facing request responsive while the job
runs.

**Definition of done** - The API returns a job identifier without
waiting for the complete research pipeline. - A separate worker process
can claim and execute the job. - The application can retrieve job status
and the completed result after the original request has ended. - The
pipeline uses multiple typed Featherweight agents and demonstrates
parallel execution. - The job records progress through a small,
documented set of lifecycle states. - A deterministic demo mode makes
the complete flow repeatable. - At least one failure path is
demonstrated and documented (for example, a provider lookup failure
followed by a controlled retry or a visible failed job).

**Not required** - Multi-hour execution, distributed fan-out across many
machines, or sophisticated scheduling. - A generic workflow engine or
graph DSL. - Exactly-once job execution. Use the delivery and
idempotency guarantees actually provided by the queue implementation.

### F4. Provider evaluation and shortlist

**Behaviour** - Compare candidates against the user's stated criteria. -
Produce a concise, structured shortlist with reasons and available
slots. - Distinguish verified mock data from model-generated
explanation.

**Definition of done** - The evaluation agent returns a typed result. -
Each recommendation references a provider and one or more returned
availability slots. - The result includes concise reasons tied to known
provider attributes. - The UI can display the shortlist without parsing
free-form model prose. - If no suitable provider is found, the system
says so rather than fabricating one.

**Not required** - Sophisticated recommendation science, learned
ranking, or user-rating analytics.

### F5. Explicit booking confirmation

**Behaviour** - The user selects one offered slot. - The system presents
the selected provider, date, and time for confirmation. - Only an
explicit confirmation creates a booking.

**Definition of done** - Booking creation is a deterministic application
operation, not an unconstrained agent decision. - The confirmation
screen clearly identifies the exact slot. - No booking is created before
confirmation. - Repeated submission of the same confirmation does not
create duplicate bookings (use an idempotency key or equivalent). - The
resulting booking can be retrieved and displayed. - The UI states that
this is a simulated booking.

**Not required** - Payment, real provider confirmation, cancellation,
rescheduling, or reminder delivery.

### F6. Streaming and job status

**Behaviour** - Stream the immediate assistant response and expose
research progress. - Allow the user to return to a job and retrieve its
current state or final result.

**Definition of done** - The user sees that research has been submitted
and receives its job identifier or an equivalent visible reference. -
The UI can display queued, running, completed, and failed states. -
Progress updates are associated with the correct job. - The final result
remains retrievable after a page refresh or a new client connection. -
The demo does not depend on the original chat connection remaining open.

**Not required** - Real-time push notifications to email, SMS, or mobile
devices. - Elaborate event replay or a full conversation platform.

### F7. Thin web UI

**Behaviour** - Provide a small web interface for the appointment
journey. - Make assistant responses, research progress, provider
shortlists, slot selection, and explicit booking confirmation visible.
- Use AG-UI as the default streaming protocol.

**Definition of done** - The user can submit an appointment request,
see the assistant's streamed response, and follow the research job's
progress. - The completed shortlist is displayed using structured
provider and slot data rather than parsing free-form prose. - The user
can select a slot, review the exact booking details, and explicitly
confirm the simulated booking. - A user can revisit or refresh the page
and retrieve the job/booking state from the application API. - The
frontend communicates through application-owned HTTP endpoints and
the AG-UI stream; it does not access Featherweight run stores, queue
internals, or agent classes directly. - The implementation uses an
existing component library or starter template where practical. Any
adapter required to connect a component library to AG-UI is small,
documented, and isolated.

**Suggested screen structure**
- **Assistant:** Conversational request intake, interpreted criteria,
  research status, shortlist/provider cards, available slots, and
  confirmation.
- **Research activity:** A compact view of the current job state and
  progress, with access to the completed result. This can be part of
  the assistant screen rather than a separate route if that keeps the
  experience simpler.
- **Booking confirmation/details:** The selected provider, exact slot,
  and simulated booking reference/status.

**Implementation guidance** - Prefer libraries with an existing AG-UI
integration or a straightforward custom-runtime/transport integration.
Evaluate assistant-ui and compatible AG-UI adapters first. Vercel AI
SDK templates and pre-built examples are also candidates, but verify
their streaming protocol compatibility before adopting them; do not
assume a Vercel AI SDK data stream is interchangeable with AG-UI.
Choose one approach rather than combining multiple chat UI libraries.
Use a conventional component library (for example, shadcn/ui) for
non-chat elements if useful. Keep visual polish secondary to a complete,
clear user journey.

**Not required** - A bespoke design system, elaborate animation,
responsive mobile-app-level interactions, analytics dashboards, admin
screens, or custom chat components when an existing library is
adequate.

### F8. Persistence and application data model

**Behaviour** - Persist the minimum domain data needed for the demo:
providers, appointment requests, research jobs/results, availability
slots, and bookings.

**Definition of done** - Postgres is started by Docker Compose. - Schema
creation and seed data are automated. - Restarting the application
containers does not erase completed bookings or research results. -
Domain data access is kept in application repositories/services,
separate from Featherweight's run/job persistence. - The README
identifies which data belongs to the application and which belongs to
the framework runtime.

**Not required** - A generic repository framework, support for multiple
database engines, or a database administration UI.

### F9. OpenTelemetry observability

**Behaviour** - Trace a request through job submission, worker
execution, agent runs, model calls, and tools where instrumentation is
available.

**Definition of done** - The application exports OpenTelemetry traces to
a locally runnable collector or tracing backend. - A trace or linked
trace can be followed from the API request to the background job. -
Agent runs and meaningful tool calls appear as spans when supported by
the integrations. - Trace context or an explicit causal link is
propagated across the job boundary. - The README explains any
instrumentation gaps.

**Not required** - A full metrics/logging platform, alerting,
dashboards, or production SLOs.

### F10. Docker Compose developer experience

**Behaviour** - Start the complete application locally using Docker
Compose.

**Definition of done** - A fresh checkout can be started using
documented commands. - Compose starts Postgres, the API/web process, and
the worker. - Health checks or equivalent readiness handling prevent
avoidable startup races. - Environment variables are documented in
`.env.example`. - Database migrations and seed data run through a
documented process. - The README includes a complete demo walkthrough
and troubleshooting notes.

**Not required** - Kubernetes manifests, cloud deployment automation,
CI/CD pipelines, or production hardening.

## 6. Suggested minimal data model

Keep the domain model small:

-   `Provider`
-   `AvailabilitySlot`
-   `AppointmentRequest`
-   `ResearchResult` (or a result payload associated with the job)
-   `Booking`

Use the Featherweight job/run storage for execution lifecycle and
diagnostics rather than duplicating all runtime details in application
tables.

## 7. Demo acceptance checklist

The project is complete when a reviewer can:

1.  Start the system with Docker Compose.
2.  Submit a natural-language appointment request.
3.  See the typed interpretation of the request.
4.  Observe a background job being processed by the separate worker.
5.  See multiple agents contribute to provider research.
6.  Retrieve a shortlist with explanations and mock availability.
7.  Select a slot and explicitly confirm a simulated booking.
8.  Refresh the application and still retrieve the result and booking.
9.  Inspect a trace that connects the API request and background
    execution.
10. Trigger or inspect one documented failure scenario.

## 8. Scope-control rules

-   Prefer the smallest UI that makes the workflow understandable. A
    basic web page is sufficient.
-   Use one service category, one region, and a small seeded dataset.
-   Use mock provider integrations. Do not spend time negotiating real
    API access.
-   Use one model provider for the happy-path demo; additional providers
    are not a feature requirement.
-   Do not add authentication, payments, notifications, or a provider
    portal.
-   Do not add a general-purpose memory system or planning middleware.
-   Do not add Redis, a message broker, or another infrastructure
    service unless the chosen Featherweight queue implementation
    actually requires it.
-   If a feature does not help demonstrate a Featherweight capability or
    complete the primary user journey, leave it out.

## 9. Deliverables

-   Source code and Docker Compose configuration.
-   `.env.example`.
-   Seeded fictional provider data.
-   README with setup, architecture, demo steps, and limitations.
-   One architecture diagram.
-   One short recorded demo or a repeatable scripted walkthrough.
-   A short note showing representative OpenTelemetry traces.

**Success criterion:** A developer can understand Featherweight's role
in a realistic, multi-process agent application by running and
inspecting this project in approximately 10--15 minutes.
