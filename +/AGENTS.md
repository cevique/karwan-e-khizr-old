# Karwan-e-Khizr — Repository Agent Instructions

This file governs the entire `karwan-e-khizr/` repository.

More-specific nested `AGENTS.md` files may add directory-specific instructions, but they MUST NOT override the ownership, safety, API-contract, or Git rules defined here.

---

## 1. PROJECT

Karwan-e-Khizr (کاروانِ خِضر) is a public-transit journey-planning and realtime-transit application for Islamabad/Rawalpindi.

Core user problem:

> "I need to get from X to Y. What transit option should I take?"

The product combines:

1. Realtime vehicle positions
2. Multi-leg journey planning
3. Intelligent journey recommendation

A journey may involve walking, buses, feeder routes, metro services, and additional walking.

The key differentiator is not merely showing buses on a map. It is helping the passenger choose the most useful journey using available realtime and journey information.

The project is a hackathon MVP. Prioritize a polished, reliable, demonstrable product over speculative enterprise architecture.

---

## 2. REPOSITORY STRUCTURE AND OWNERSHIP

```text
karwan-e-khizr/
├── AGENTS.md
├── opencode.json
├── backend/              # backend teammate, main branch
├── frontend/             # frontend developer, v0.1 branch
├── plans and queries/    # project/product notes
├── .obsidian/            # Obsidian vault configuration
└── ...
````

### Ownership

* `/backend` is owned by the backend teammate and is developed on `main`.
* `/frontend` is owned by the frontend developer and is developed on `v0.1`.
* This agent is primarily being used for frontend development.

### Absolute backend boundary

During frontend work, NEVER modify anything under `/backend` unless the user explicitly requests a backend change in that message.

This includes:

* refactoring
* cleanup
* dependency changes
* database changes
* migration changes
* API changes
* routing changes
* test changes
* configuration changes
* "fixes" discovered while inspecting the backend

If a backend change appears necessary:

1. Do not make the change.
2. Explain what is needed and why.
3. Wait for explicit approval.

Reading backend code for API integration and understanding the existing system is allowed and encouraged.

---

## 3. GIT SAFETY

The frontend developer works on branch `v0.1`.

The backend teammate works on `main`.

Rules:

* NEVER force-push.
* NEVER delete or overwrite another developer's commits.
* NEVER reset or rewrite shared history.
* NEVER assume uncommitted changes belong to the agent.
* Inspect `git status` before broad modifications.
* Inspect relevant `git diff` before modifying existing work.
* Keep frontend commits scoped primarily to `/frontend`.
* Changes to the root `AGENTS.md` are allowed only when explicitly requested.
* Do not switch branches unless explicitly requested.
* Do not merge, rebase, cherry-pick, or otherwise alter branch history unless explicitly requested.

Local history operations on the user's own branch are allowed only when explicitly requested or clearly required by the user's instruction.

---

## 4. OPENCODE CONFIGURATION

`opencode.json` is existing shared project configuration.

Current MCP servers include:

* `fetch`
* `postgres`
* `docker`

Do NOT remove, replace, simplify, or reconfigure existing MCP servers unless explicitly requested.

MCP access does NOT change repository ownership rules.

In particular:

> PostgreSQL or Docker access does NOT authorize modification of `/backend`.

Use only the tools necessary for the current task.

---

## 5. BACKEND — EXISTING SYSTEM

The backend is an existing FastAPI + PostgreSQL/PostGIS application.

Primary technologies:

* FastAPI
* SQLAlchemy 2.x async
* asyncpg
* PostgreSQL 16
* PostGIS
* Alembic
* JWT authentication
* pytest

The backend contains:

```text
backend/
├── api/
├── routing/
├── simulation/
├── db/
├── core/
├── users/
├── ticketing/
├── seeding/
├── data/
├── scripts/
├── tests/
└── docs/
```

Important architectural invariants:

* `routing/` contains routing logic and does not depend on FastAPI/SQLAlchemy.
* `simulation/` contains vehicle simulation and does not depend on FastAPI.
* `api/` is the HTTP boundary.
* External systems are accessed through provider/protocol abstractions.
* ORM models are not returned directly from API endpoints.
* API schemas are the client-facing contract.
* The routing graph is built at startup and is immutable during runtime unless explicitly rebuilt.
* Backend services manage transactions according to the existing architecture.
* Do not duplicate backend routing logic in the frontend.

For deeper backend information, inspect the actual backend implementation and documentation rather than relying on this summary.

---

## 6. BACKEND DATA REALITY

NEVER fabricate transit data.

Do not invent:

* coordinates
* stop names
* routes
* route geometry
* timetables
* vehicle positions
* API endpoints
* request parameters
* response fields
* realtime states

The backend currently contains known data gaps.

Many stops lack coordinates and many routes lack complete timetable/geometry information.

When real data is unavailable:

* show an appropriate loading state,
* show an empty/data-unavailable state,
* or use clearly-labelled demo/mock data during development.

Never present fabricated or simulated data as verified live information.

---

## 7. BACKEND API CONTRACT

Known API groups include:

### Transit

```text
GET /api/transit/agencies
GET /api/transit/routes
GET /api/transit/routes/{route_id}
GET /api/transit/stops
GET /api/transit/stops/{stop_id}
```

### Journey search

```text
POST /api/transit/journeys/search
```

### Realtime

```text
GET /api/transit/realtime/vehicles
GET /api/transit/realtime/vehicles/{vehicle_id}
GET /api/transit/realtime/routes/{route_id}/vehicles
GET /api/transit/realtime/trips/{trip_id}/vehicles
```

### Authentication

```text
POST /api/auth/register
POST /api/auth/login
GET  /api/auth/me
```

### Users

```text
GET /api/users/me
```

### Fares

```text
POST /api/fares/quote
```

### Tickets

```text
/api/tickets/*
```

These endpoint names are contextual references, NOT permission to assume their exact contracts.

### API integration rules

Before integrating an endpoint:

1. Inspect its actual backend router.
2. Inspect its request/response schema.
3. Check the running OpenAPI documentation when available.
4. Use the real field names and types.
5. Never invent missing fields.

Backend API schemas are the source of truth for frontend integration.

If the frontend design expects information that the backend does not provide, do not silently fabricate it. Identify the gap.

---

## 8. FRONTEND TECHNOLOGY

The frontend is a mobile-first application targeting:

* Android
* iOS
* Web

Technology:

* React Native
* Expo
* TypeScript
* Expo Router where appropriate
* React Native Web / Expo Web

Do not introduce another framework unless there is a concrete technical reason.

Every new dependency must have a clear purpose.

Do not install libraries merely because they are popular or because an AI agent suggests them.

Prefer the existing Expo/React Native ecosystem and platform capabilities where practical.

---

## 9. FRONTEND ARCHITECTURE

Prefer a clear separation of responsibilities.

A reasonable structure is:

```text
frontend/
├── app/                 # Expo Router screens/routes
├── components/          # reusable UI components
├── services/            # API/network layer
├── hooks/               # reusable state/data hooks
├── types/               # TypeScript models
├── constants/
├── assets/
├── mocks/               # clearly-labelled demo data
└── ...
```

Adapt this structure to the existing frontend scaffold rather than blindly creating duplicate directories.

### Data flow

Prefer:

```text
UI components
      ↓
hooks / state
      ↓
services
      ↓
backend API
```

UI components should NOT:

* scatter raw `fetch()` calls throughout the application
* hardcode backend URLs
* contain substantial networking logic
* duplicate routing algorithms

Centralize API communication in the service layer.

Centralize realtime polling/update behavior.

Keep API base URLs configurable.

---

## 10. FRONTEND/BACKEND INDEPENDENCE

The frontend should be developable independently of the backend whenever practical.

UI development may use mock/demo data when backend services are unavailable.

Mock data MUST:

* live in `frontend/mocks/` or an equivalent clearly-separated location
* follow the real API shape where known
* be easy to replace with live API calls
* never be represented as verified live transit data

Build the UI against realistic data structures so the eventual API integration does not require rewriting the screens.

---

## 11. REALTIME VEHICLE EXPERIENCE

Realtime vehicle information is a core product feature.

Frontend realtime behavior should:

* consume the existing realtime API
* use a centralized realtime service
* expose data through a reusable hook/state layer
* use configurable polling/update intervals
* correctly handle loading, stale, unavailable, and error states

Do not put realtime polling independently inside multiple components.

Do not fabricate vehicle positions.

Simulation data may be used for the hackathon demo when clearly treated as simulation/demo data.

---

## 12. MAPS AND GEOGRAPHIC DATA

Maps are important to the product, but geographic correctness is more important than visual completeness.

NEVER invent:

* stop coordinates
* route geometry
* vehicle coordinates
* geographic relationships

If geographic information is unavailable, represent the unavailable state honestly.

Do not create fake route lines merely to make a map look populated.

---

## 13. JOURNEY RECOMMENDATION

The core product experience is:

```text
Origin
   ↓
Destination
   ↓
Possible journeys
   ↓
Recommendation
   ↓
Clear explanation of why it is recommended
```

A journey may contain:

```text
Walk
 ↓
Bus
 ↓
Walk
 ↓
Metro / another service
 ↓
Walk
 ↓
Destination
```

Where available, the UI may communicate:

* total journey time
* walking time
* waiting time
* transit time
* transfers
* boarding stop
* alighting stop
* route/service
* realtime vehicle information
* delay/status
* recommendation reasoning

Recommendation reasoning should be understandable to an ordinary passenger.

Avoid unnecessary AI terminology in the user interface.

For example, prefer:

> "Recommended because it arrives sooner and requires less walking."

over:

> "AI confidence score: 0.87."

### Ownership of recommendation logic

There must be one clearly-defined owner for recommendation logic.

The frontend MUST NOT duplicate the backend routing engine inside UI components.

If recommendation intelligence is implemented as a separate service or backend layer, the frontend consumes its output.

If recommendation logic is later moved or expanded, update the integration boundary rather than embedding business logic into screens.

---

## 14. FIGMA AND UI DESIGN

Figma is the source of truth for visual design.

Implement the provided design faithfully, including:

* layout hierarchy
* spacing
* typography
* visual hierarchy
* navigation
* interactions
* component relationships
* responsive behavior
* platform-appropriate behavior

Do NOT replace the Figma design with generic AI-generated UI.

Do NOT redesign screens merely because another design seems prettier.

When a Figma feature cannot be implemented identically on Android, iOS, and Web:

1. Preserve the intended interaction and visual hierarchy.
2. Use the closest platform-appropriate implementation.
3. Do not silently change the product behavior.

### Conflicting sources

If Figma, backend APIs, or this document conflict:

* do not silently break the backend contract
* identify the conflict
* preserve API compatibility
* ask for approval before making a breaking change

---

## 15. RESPONSIVE / PLATFORM BEHAVIOR

The primary experience is mobile.

Android is the immediate hackathon demonstration target.

iOS and Web compatibility must be preserved while building the MVP.

Do not prematurely build three completely different applications.

Prefer shared React Native components and platform-specific code only where genuinely necessary.

Web layouts should adapt appropriately rather than simply stretching a phone screen across a desktop viewport.

---

## 16. HACKATHON PRIORITIES

Optimize implementation order around what can actually be demonstrated.

### P0 — MUST WORK

1. App launches reliably.
2. Core navigation works.
3. Origin/destination input works.
4. Journey search works.
5. Journey results are visually clear.
6. Recommendation is clearly presented.
7. Realtime vehicle display works.
8. Backend integration works.
9. Android demo works.
10. UI matches the Figma design closely.

### P1 — SHOULD WORK

* Journey details
* Interactive map
* Realtime refresh
* Loading states
* Error states
* Empty states
* Web compatibility
* iOS compatibility
* polished transitions and interactions

### P2 — ONLY IF TIME REMAINS

* Authentication
* Saved journeys
* Ticketing
* Payments
* Advanced personalization
* advanced ML/prediction
* analytics
* non-essential settings

Do NOT build P2 features while P0 functionality is incomplete.

---

## 17. DEMO-FIRST ENGINEERING

This is a time-constrained hackathon.

Prefer:

* working features
* visual polish
* obvious user value
* fast iteration
* reliable demo flows
* maintainable code

Avoid:

* speculative enterprise architecture
* excessive abstraction
* unnecessary state-management systems
* unnecessary dependencies
* premature optimization
* features that cannot be demonstrated
* rewriting existing working systems

The best implementation is the smallest implementation that reliably demonstrates the product's core value.

---

## 18. OPEN CODE / AGENT BEHAVIOR

Before modifying code:

1. Inspect the relevant existing files.
2. Understand the existing architecture.
3. Check current Git state when the change is broad.
4. Identify whether the requested change belongs to frontend or backend.
5. Check the actual API contract when integration is involved.

When implementing:

* Make the smallest coherent change.
* Reuse existing components and utilities where appropriate.
* Do not rewrite working code without a reason.
* Do not create duplicate systems.
* Do not invent APIs or data.
* Do not introduce unnecessary dependencies.
* Keep code readable and appropriately typed.

After implementing:

* Run the relevant typecheck/lint/tests/build checks available for the frontend.
* Verify the affected screen or flow.
* Report what changed.
* Report verification results.
* Clearly identify anything that could not be verified.

Do not claim something works if it was not actually tested.

Once requirements are clear, implement rather than producing unnecessary planning documents.

If the user explicitly asks for planning only, do not modify code.

---

## 19. IMPORTANT FILES

Before making substantial changes, inspect relevant existing files.

Useful project documentation includes:

```text
README.md
backend/plan.md
backend/docs/
plans and queries/
```

The backend documentation and research files contain the source material for transit data and backend architecture.

Do not treat aspirational documentation as proof that a feature exists in code.

When documentation and implementation disagree:

> The implementation/API schema is the source of truth for integration.

---

## 20. FINAL SAFETY RULE

When uncertain, prefer:

```text
inspect → understand → implement minimally → verify
```

over:

```text
assume → rewrite → hope
```
