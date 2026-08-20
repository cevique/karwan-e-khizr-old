# Karwan-e-Khizr — Master Product & Implementation Blueprint
### (Bano Qabil × Alibaba Cloud AI Hackathon — kickoff-ready revision)

**Status of this document.** This fully replaces the previous
`backend/plan.md`. It is written to be handed to Alibaba Qoder (and the
team) at hackathon kickoff as the implementation blueprint. It
incorporates senior architecture feedback received after the prior
revision: (1) the voice layer must use a dedicated speech/NLP model, not
the main LLM doing double duty as both transcriber and reasoner; (2)
Qwen sits above that as a genuine conversational Journey Planner
agent — understanding intent, preferences, constraints, doing
clarification and tool selection — not a one-shot text→JSON converter;
(3) routing intelligence should be evaluated as a proper **geospatial
transit layer** (PostGIS/OSM/OSRM-based spatial reasoning), with
Dijkstra correctly understood as one implementation detail inside a
deterministic optimization stage, not the project's "AI story," and not
something to rip out and replace with an unproven neural router either.

**Preparation-period framing.** The current repository is a **verified
reference foundation**, built before the hackathon as preparation — not
a thing to keep extending indefinitely before kickoff. With
approximately two days of prep remaining, this document does not add new
pre-hackathon implementation phases; it re-ranks everything the
hackathon build should focus on, sequenced for a compelling working demo
built live during the event using Alibaba-provided resources and Qoder,
with this repository and this document as the starting reference.

**No code is written or changed by this document.** It is a plan
revision only.

---

## 1. Audit — What Changes From the Prior AI Revision, and Why

The prior revision (one turn ago) got the product framing right — AI
around a deterministic core, never replacing it — but had two structural
gaps the senior feedback correctly identifies:

1. **It collapsed "speech" and "reasoning" into one Qwen call in
   places.** Section 5.1 of the prior plan had Qwen doing intent
   extraction directly from a transcribed utterance with no clearly
   separated speech/NLP stage in between (ASR was treated as a
   preprocessing detail of §6, not an architectural layer in its own
   right feeding the planner). **This revision fixes that by making the
   Speech/NLP layer a first-class stage** (§4), with its own contract,
   sitting strictly below the Qwen Journey Planner and strictly above
   nothing — it never talks to the routing engine or the database
   directly.
2. **It undersold the geospatial layer.** The prior plan treated
   "location resolution" as a small sub-step of the conversational
   pipeline (§5.2) and geometry/PostGIS work as leftover data-quality
   tasks from the original six-phase plan. **This revision promotes
   geospatial reasoning to its own architectural layer** (§5) — spatial
   candidate generation, nearby-stop discovery, pedestrian/walking
   analysis, and route geometry, all backed by the *already-built and
   already-verified* PostGIS/OSRM/Nominatim infrastructure — sitting
   between the Qwen Journey Planner and the deterministic
   routing/optimization stage. This is real, demoable, and does not
   require new ML.

Neither fix requires touching `routing/graph.py`, `routing/search.py`,
`simulation/`, `ticketing/`, or `users/` — the deterministic backend
described in the prior plan's audit (§2, carried forward unchanged
below) needed no architectural correction. Only the AI-side layering
needed restructuring, and this document restructures it as a genuine
five-layer pipeline rather than appending a sixth phase onto a
four-layer one.

**Phases that are restructured, not merely appended to**, relative to
the prior plan:
- The prior "Phase B — Conversational AI Core" is split into three
  distinct layers with three distinct contracts: Speech/NLP (§4), Qwen
  Journey Planner (§6), and Geospatial Transit Intelligence (§5) — each
  independently buildable, independently testable, and independently
  swappable.
- The prior "Phase 0 — Research Spike" is kept but re-scoped: it no
  longer needs to resolve *whether* AI is architecturally sound (this
  document resolves that), only which specific Alibaba service
  instances are reachable on the hackathon account (§10).
- The prior ETA ML phase (Phase D) is **kept exactly as previously
  designed**, per explicit instruction — it was already a separate,
  correctly-staged component and needed no restructuring, only
  reaffirmation (§8).
- Route filtering, fares, ticketing, admin, map, and account sections
  are carried forward with no substantive change — reaffirmed in §9 for
  completeness, not re-litigated.

---

## 2. Already-Verified Foundation (unchanged — do not rebuild)

Everything in this section is implemented, tested (532 tests, 0 failed,
0 skipped, live-verified against Docker Postgres/PostGIS), and treated
as **the reference foundation Qoder should be told is done** at
kickoff.

- **Transit data**: agencies, routes, stops, route-stops, trips,
  stop-times — imported, idempotent, provenance-tracked.
- **Geospatial enrichment**: Nominatim-backed stop geocoding, 88 of 122
  stops located, provenance/confidence tracked, 34 stops still
  `UNKNOWN`.
- **Route geometry**: OSRM road-snap pipeline, verified working end to
  end; 0 real routes currently have a full located stop sequence, so 0
  currently have generated geometry (a data-coverage gap, not a pipeline
  defect).
- **Bus simulation**: deterministic, time-based, route-aware position
  interpolation (bearing, speed), falls back to straight-line without
  geometry.
- **Realtime/ETA REST APIs**: working; not yet source-labeled
  (`source: "simulated"` designed, not yet wired).
- **Timetable-driven trip generation**: real canonical timetables for 4
  of ~22 known routes (FR-01/04/07/14); the rest have no stop-level
  schedule (headway-only or undocumented).
- **Frontend API contract**: CORS, route geometry embedded in journey
  legs — tested.
- **Journey planner (`routing/`)**: working MVP — static graph,
  Dijkstra, 3 objectives (fastest / fewest transfers / least walking),
  single result per request, no filters yet, `departure_time` accepted
  but currently inert.
- **Fares**: DB-driven `FareRule`, flat per-boarding formula, in-code
  default fallback — not hardcoded in the "scattered constants" sense,
  not distance-based.
- **Ticketing + QR**: full `ACTIVE → USED/EXPIRED/REVOKED` state
  machine, signed opaque QR payload, atomic validate-and-consume,
  ownership checks.
- **Payments**: scaffolded only (`PaymentProvider` Protocol,
  always-succeeds dev implementation) — by design.
- **User accounts**: register/login/JWT/bcrypt, two roles
  (`passenger`/`admin`). No password reset/refresh tokens yet.
- **Admin backend**: seed/import/graph-rebuild/trip-generation
  endpoints, correctly `ROLE_ADMIN`-gated. No stop/route/fare/user CRUD
  yet.
- **Security posture**: no rate limiting yet anywhere; realtime
  simulation *control* endpoints are deliberately unauthenticated today
  (fine for local dev, not for a hosted demo URL).

**Nothing above needs architectural change for the hackathon.** The
hackathon's job is to build the AI/geospatial/voice layers around it and
hand the combined system a real, judged demo.

---

## 3. Final Layered Architecture

```
                                    User
                                     │
                          ┌──────────┴──────────┐
                          │    Voice  /  Text     │
                          └──────────┬──────────┘
                                     │
                     ┌───────────────▼───────────────┐
                     │      LAYER 1 — Speech / NLP       │   deterministic-ish,
                     │  - ASR (dedicated speech model)    │   model-assisted,
                     │  - language detection               │   NOT the agent
                     │  - Urdu / Roman-Urdu / English       │
                     │    normalization to clean text        │
                     └───────────────┬───────────────┘
                                     │ normalized text + detected_language
                     ┌───────────────▼───────────────┐
                     │  LAYER 2 — Qwen Journey Planner    │   GENUINE AI:
                     │            (agent)                   │   reasoning,
                     │  - intent understanding               │   tool selection,
                     │  - preference/constraint extraction    │   clarification,
                     │  - clarification dialogue               │   multi-turn
                     │  - TOOL SELECTION (calls Layer 3/4)      │   context
                     │  - multi-turn context                     │
                     │  - grounded explanation of results          │
                     └───────────────┬───────────────┘
                          tool calls  │  ▲ tool results
                     ┌───────────────▼──┴────────────┐
                     │  LAYER 3 — Geospatial Transit      │   DETERMINISTIC,
                     │            Intelligence               │   PostGIS/OSM/OSRM-
                     │  - location/place-name resolution      │   backed. No LLM,
                     │  - PostGIS spatial candidate queries     │   no new ML.
                     │  - nearby-stop discovery                   │   Already mostly
                     │  - pedestrian/walking-distance analysis     │   built (§2).
                     │  - route geometry (OSRM)                      │
                     │  - transit candidate-set generation             │
                     └───────────────┬───────────────┘
                        stop/edge candidates
                     ┌───────────────▼───────────────┐
                     │  LAYER 4 — Deterministic Routing /  │   DETERMINISTIC.
                     │            Optimization               │   Dijkstra lives
                     │  - valid transit path search             │   here as an
                     │    (Dijkstra over the transit graph)       │   implementation
                     │  - transfers, walking, travel time           │   detail — see §7.
                     │  - route filtering / ranking                    │
                     │  - fare constraint application                    │
                     └───────────────┬───────────────┘
                                     │ authoritative JourneySearchResponse
                     ┌───────────────▼───────────────┐
                     │      Authoritative Journey Result   │
                     └───────────────┬───────────────┘
                                     │
                     ┌───────────────▼───────────────┐
                     │  LAYER 2 (return path) — Qwen        │   GENUINE AI:
                     │  grounded explanation                  │   narrates ONLY
                     │  (+ optional Layer 1 TTS on the way out) │   what Layer 4
                     └───────────────┬───────────────┘   returned.
                                     │
                          ┌──────────▼──────────┐
                          │   User + Interactive Map │
                          └──────────────────────┘


  Separate, parallel component (unchanged from prior plan, reaffirmed §8):

  simulation/history → ETA training data → ML model → Alibaba PAI-EAS → ML ETA
                                                                              │
                                          deterministic simulation ETA ──────┴──→ always-available fallback
```

**Five layers, five contracts, five owners:**

| Layer | What it is | Owner technology | New build for hackathon? |
|---|---|---|---|
| 1. Speech/NLP | ASR + language ID + text normalization | Dedicated Alibaba speech model(s) — NOT the Qwen chat/agent model | Yes — thin integration |
| 2. Qwen Journey Planner | Conversational agent: understands, clarifies, selects tools, explains | Qwen chat model via Model Studio, tool-calling mode | Yes — the core AI build |
| 3. Geospatial Transit Intelligence | Spatial reasoning: resolves places, finds candidate stops/edges, computes walking distance, supplies geometry | PostGIS + OSRM + Nominatim — **already built**, being exposed as callable tools | Mostly integration, not new engineering |
| 4. Deterministic Routing/Optimization | Finds valid paths, applies filters, computes fares | `routing/` package — **already built** (Dijkstra inside) | Extend with filters/multi-candidate (already scoped) |
| 5. Map/Realtime/Ticketing/Auth | Everything the user sees and transacts with | Existing APIs + frontend | Mostly integration |

---

## 4. Layer 1 — Speech / NLP (dedicated, separate from the reasoning agent)

### 4.1 Why this is a separate layer

The senior feedback is architecturally correct and worth stating
plainly: **transcription and reasoning are different jobs.** A model
that is good at turning audio into accurate text is not the same model
that should be reasoning about travel preferences, and conflating them
either wastes the reasoning model's context budget on acoustic modeling
it isn't specialized for, or (worse) lets transcription noise get
silently "corrected" by an LLM guessing what the user probably meant —
which is exactly the kind of invisible hallucination risk this project
must avoid. Keeping ASR as its own layer with its own, inspectable
output (plain normalized text) means Layer 2's input is always a clean,
auditable string, and any transcription errors are visible and
debuggable independently of the reasoning layer.

### 4.2 Responsibilities (strictly bounded)

- **ASR**: audio → raw transcribed text. Dedicated Alibaba Cloud speech
  models (Qwen3-ASR / Fun-ASR / Paraformer via Model Studio — confirmed
  current product family, **not** the Qwen chat/LLM model used in Layer
  2). Real-time (WebSocket streaming) or file-based, per UX needs.
- **Language detection**: identify `en` / `ur` / `roman-ur` / `mixed`
  from the transcribed (or typed) text. This can be a lightweight
  classifier or a single fast Qwen call used strictly as a
  classification utility (not as the conversational agent) — an
  implementation choice made at kickoff, not fixed here, since either
  is cheap and fast.
- **Normalization**: light cleanup (script normalization, removing ASR
  disfluency artifacts where the chosen model supports it, e.g.
  Paraformer's `disfluency_removal_enabled`) — text hygiene, not
  semantic interpretation.
- **Text-to-speech (optional output path)**: authoritative narration
  text (produced by Layer 2, grounded in Layer 4's output) → audio, via
  a dedicated Alibaba TTS model (CosyVoice/Qwen-TTS). Same
  separation-of-concerns logic applies in reverse: the TTS model's job
  is pronunciation and prosody, not deciding what to say.

**What Layer 1 explicitly does NOT do:** intent extraction, preference
interpretation, clarification, tool selection, or anything that requires
understanding *what the user wants* rather than *what the user said*.
That boundary is what makes Layer 2 genuinely an agent rather than a
rebranded string-processing step.

### 4.3 Contract with Layer 2

```
Layer 1 -> Layer 2 input:
{
  "normalized_text": string,       // clean, ASR/typed, post-normalization
  "detected_language": "en" | "ur" | "roman-ur" | "mixed",
  "input_modality": "voice" | "text",
  "asr_confidence"?: number        // if available from the ASR model, passed through for Layer 2 to factor into clarification decisions (e.g. low-confidence transcription -> ask for confirmation rather than acting on it)
}

Layer 2 -> Layer 1 (return path, TTS only):
{
  "text_to_speak": string,         // Layer 2's grounded explanation, verbatim
  "language": "en" | "ur" | "roman-ur"
}
```

### 4.4 What's confirmed vs. must be verified at kickoff

Unchanged from the prior revision's research findings (still accurate,
re-stated concisely here — full detail in §10):
- **Confirmed**: English ASR and TTS via Alibaba Cloud Model Studio
  (Qwen3-ASR, CosyVoice/Qwen-TTS).
- **Not confirmed in published language lists**: Urdu ASR/TTS. Roman
  Urdu is not a distinct "speech language" (it's Urdu speech
  transliterated at the text layer, not a different acoustic language),
  so native Roman-Urdu *speech* recognition is really "does Urdu speech
  recognition work" restated — the same open question.
- **Text-based Urdu/Roman-Urdu is unaffected by this gap** — it never
  touches Layer 1's ASR/TTS models at all when typed, and even when
  spoken-then-transcribed by a fallback (§4.5), the normalized text
  handed to Layer 2 is just text, which Qwen (Layer 2) handles
  natively and well regardless of ASR provenance.

### 4.5 Fallback (no feature is blocked on an unverified capability)

If Alibaba's Urdu ASR/TTS proves unavailable or low-quality at kickoff
verification (§10), the **client-side/browser speech APIs** (widely
available cross-platform, including Urdu on many devices) transcribe
locally and feed the **same** `normalized_text` contract into Layer 2 —
Layer 2 and everything downstream is completely unaware of which
transcription path produced its input. This is the single most important
resilience property of this architecture: **the Speech/NLP layer's
output contract is stable regardless of which underlying model produces
it**, so a kickoff-day finding about Urdu ASR support changes an
implementation detail inside Layer 1, never anything above it.

---

## 5. Layer 3 — Geospatial Transit Intelligence

### 5.1 Why this deserves to be its own layer, not a routing sub-step

This is the direct response to the senior's third point. The honest
technical evaluation:

**Does a genuine learned geospatial/routing model add enough value for
this hackathon to justify its complexity? No — and here's the reasoning,
not just an assertion:**

- The research on learned routing (graph neural networks predicting
  travel time / edge weights, e.g. recent work on GNN-based shortest-path
  approximation and dynamic-routing embeddings) is real and legitimate,
  but in every credible production and research design, **the learned
  component predicts edge weights or travel-time corrections that feed
  into a classical shortest-path algorithm — it does not replace
  pathfinding itself.** That is: even state-of-the-art systems keep
  Dijkstra/A\*-family search as the pathfinding mechanism and use
  learning only to improve the *cost function* the search operates over.
  This project already has exactly that shape planned — it's the ETA ML
  component (§8), which predicts travel-time/delay values that could, in
  a future iteration, feed back into edge costs. Building a *second*,
  redundant "geospatial routing model" would duplicate that role without
  adding a new capability.
- A GNN-based router would require substantial real historical
  trajectory/travel-time data to train meaningfully — this project has
  none yet (no real vehicle telemetry exists; see §2's realtime-data
  gap, unchanged from the prior plan) and would be training on synthetic
  simulation data at best, at which point it is not learning anything
  the deterministic simulation-derived cost function doesn't already
  encode directly and more transparently.
- Transit routing has a hard, non-negotiable correctness requirement
  this project must not compromise: **never invent a road, stop,
  transfer, route, walking distance, or timetable.** A neural router
  is a plausible-answer generator, not a constraint-satisfying one,
  making it fundamentally the wrong tool for this specific guarantee,
  regardless of how much data were available.

**What genuinely does add hackathon-relevant value, and is real
"geospatial intelligence" rather than a rebrand of existing code:**
treating the *already-built* PostGIS/OSRM/Nominatim capabilities as a
**distinct, explicit reasoning layer** that Qwen calls as tools — spatial
candidate generation (which stops are near a resolved location),
pedestrian-distance analysis (real walking distance/time via OSRM, not
straight-line), and route-geometry retrieval. This is legitimate
geospatial computation, it is demoable ("here's how we resolve 'Saddar'
to actual candidate boarding stops using real spatial queries, not string
matching"), and — critically — **most of the underlying capability
already exists and is already verified** (§2). The hackathon work is
packaging it as a clean, tool-callable layer with its own contract, not
building new geospatial ML.

**Decision, stated explicitly per the senior's request:** No learned
geospatial/neural routing model is included in this architecture. The
geospatial intelligence layer is a computational/deterministic layer
built on PostGIS/OSM/OSRM. This is not a consolation choice — it is the
technically correct one for a system that must remain constraint-safe,
and it is honestly a stronger demo story ("real spatial database queries
against real transit data" is impressive and true) than a neural router
would be if judges probed it.

### 5.2 Responsibilities

- **Location/place-name resolution**: turn a free-text place name
  (from Layer 2's extracted intent) into a coordinate/stop candidate
  set. Two-tier approach (already the right design from the prior
  revision, reaffirmed): (1) fast fuzzy match against known `Stop.name`
  values and curated landmark aliases — in-memory, instant, no external
  dependency; (2) fallback to live Nominatim geocoding (already
  integrated) for unmatched names.
- **PostGIS spatial candidate queries**: given a resolved coordinate,
  find candidate boarding/alighting stops within a configurable radius —
  this already exists as the walking-radius logic inside
  `routing/snapping.py`; Layer 3 exposes it as an independently callable
  operation rather than only as an internal step of a single monolithic
  journey search.
- **Nearby-stop discovery**: general "what's near this point" queries,
  useful both for journey planning and for answering conversational
  questions like "what stops are near me" without a full journey search.
- **Pedestrian/walking-distance analysis**: real walking distance/time
  between a point and a stop (already computed via the existing walking
  edge-cost provider in `routing/`), exposed as a Layer-3 operation.
- **OSM/OSRM route geometry retrieval**: existing `Route.path` /
  `route_geometry` data, exposed for both map rendering and for Qwen to
  reference when explaining a journey ("this follows the road via
  Murree Road").
- **Transit candidate-set generation**: the combination of the above —
  given an origin and destination, produce the candidate stop pairs and
  edges that Layer 4's optimizer will search over. This is the
  boundary: Layer 3 produces *candidates*, Layer 4 produces the
  *authoritative path*.

### 5.3 Contract with Layer 2 (tool interface) and Layer 4

Layer 3 is exposed to Qwen (Layer 2) as a small set of **callable
tools** (Model Studio's function-calling mechanism — see §6.3), each
with a strict, validated schema:

```
tool: resolve_location(text: string) 
  -> { candidates: [{stop_id, name, lat, lon, match_confidence, match_type: "exact_stop"|"fuzzy_stop"|"geocoded"}] }

tool: nearby_stops(lat: float, lon: float, radius_m: int)
  -> { stops: [{stop_id, name, lat, lon, distance_m}] }

tool: walking_distance(from_lat, from_lon, to_lat, to_lon)
  -> { distance_m: float, duration_s: float }

tool: route_geometry(route_id: string)
  -> GeoJSON LineString | null   // null if this route has no geometry yet — never fabricated
```

Layer 3's outputs feed **either** directly back to Qwen (for
conversational questions like "what stops are near NUST") **or**
into Layer 4 as part of the assembled `JourneySearchRequest` (for an
actual journey search) — Layer 2 decides which, per §6.3's tool-selection
responsibility. Layer 3 itself has no opinion about which stops end up
in a final journey; it only supplies candidates and measurements.

---

## 6. Layer 2 — Qwen Journey Planner (the genuine agent)

### 6.1 What "agent" means here, concretely

This is the layer the senior feedback wants elevated from "text-to-JSON
converter" to genuine agent. Concretely, that means Qwen (via Model
Studio's tool-calling / function-calling interface) is given:
- A system prompt describing its role, the available tools (Layer 3's
  geospatial tools, plus a `search_journeys` tool that wraps Layer 4),
  and the hard constraint that it must never state a fact not returned
  by a tool call.
- Multi-turn conversation state (prior turns' resolved requests and
  results, kept server-side per session).
- The ability to make **multiple tool calls across a turn** — e.g.
  resolve both origin and destination via `resolve_location`, then call
  `search_journeys`, rather than being handed a single pre-built request
  object to rubber-stamp. This is the concrete difference between
  "agent with tool selection" and "one-shot converter": the model
  decides *which* tools to call and *in what order*, based on what the
  user said and what's still missing.

### 6.2 Responsibilities

- **Intent understanding**: what does the user want — a journey search,
  a status question about an existing result ("is the bus late?"), a
  nearby-stops question, a fare question?
- **Preference/constraint extraction**: origin, destination, time
  constraints, routing objective, walking/transfer tolerance —
  classified into the fixed set of backend-supported filter values (see
  §9.3, unchanged from prior plan — Qwen classifies vague language into
  buckets, never invents an exact number the user didn't imply).
- **Clarification**: when `resolve_location` returns multiple ambiguous
  candidates, or a required field is missing, Qwen asks a clarifying
  question rather than guessing — this is a genuine agentic decision
  (interpreting tool output and deciding the conversation isn't ready to
  proceed), not just schema validation.
- **Tool selection**: deciding which Layer-3 tools and which Layer-4
  call are needed for a given turn, and in what sequence (see worked
  example, §6.4).
- **Multi-turn context**: resolving "which one has less walking" against
  the previous turn's `JourneySearchResponse` (already fetched, not
  re-derived from memory) — grounding every follow-up in real data
  already retrieved this session.
- **Grounded explanation**: after Layer 4 returns authoritative results,
  narrate them in the user's detected language, using only values
  present in the tool results (mechanically enforced — see §6.5).

### 6.3 Tool inventory (what Qwen can call)

| Tool | Layer | Returns |
|---|---|---|
| `resolve_location(text)` | 3 | candidate stops/coordinates |
| `nearby_stops(lat, lon, radius_m)` | 3 | nearby stop list |
| `walking_distance(from, to)` | 3 | distance/duration |
| `route_geometry(route_id)` | 3 | GeoJSON or null |
| `search_journeys(origin, destination, objective, max_walk_m?, max_transfers?, departure_time?)` | 4 (wraps the existing/extended `POST /transit/journeys/search`) | `JourneySearchResponse` — candidate journeys |
| `get_vehicle_eta(route_id or trip_id)` | 4/existing realtime API | scheduled + simulated ETA, delay |
| `get_fare_quote(ride_leg_count)` | existing fares API | fare amount |

Every tool call and its result is logged as part of the session's
structured trace — this is what makes the "grounded, not hallucinated"
property testable (§6.5) and what makes the system explainable to
judges: a judge can literally be shown "here is the sequence of tool
calls that produced this answer."

### 6.4 Worked example (agentic, multi-step — not a single conversion)

> User (voice, Roman Urdu): *"Yaar mujhe Saddar se NUST jana hai, kam se
> kam paidal chalna paray."*

1. Layer 1 → `{normalized_text: "Yaar mujhe Saddar se NUST jana hai, kam
   se kam paidal chalna paray.", detected_language: "roman-ur"}`
2. Layer 2 (Qwen) reasons: this is a journey request; origin "Saddar" and
   destination "NUST" both need resolving; preference is a walking
   constraint.
3. Layer 2 calls `resolve_location("Saddar")` → multiple candidates
   returned (e.g. "Saddar Bus Terminal", "Saddar Chowk") with different
   confidences.
4. Layer 2 decides: if the top candidate's confidence is high enough
   (a threshold set during hackathon tuning), proceed with it; if
   genuinely ambiguous, ask: *"Saddar Bus Terminal, ya Saddar Chowk?"* —
   a real clarification decision based on tool output, not a scripted
   branch.
5. Layer 2 calls `resolve_location("NUST")` → resolves cleanly (single
   strong match).
6. Layer 2 classifies "kam se kam paidal chalna paray" →
   `max_walking_distance_class: "strict"` (per §9.3's fixed bucket
   scheme — no invented number).
7. Layer 2 calls `search_journeys(origin=<resolved>, destination=
   <resolved>, objective="least_walking", max_walk_m=<strict bucket
   value>)`.
8. Layer 4 (existing deterministic engine, extended with filters)
   returns a `JourneySearchResponse`.
9. Layer 2 narrates the result in Roman Urdu, referencing only what
   came back in step 8.
10. Response returned as text (and, if TTS is wired and viable, as
    audio via Layer 1's return path).

This is a genuine multi-step agent trace — location resolution,
conditional clarification, preference classification, and a
routing-tool call — not a single "parse this sentence into a form"
operation, which is exactly the elevation the senior feedback asked for.

### 6.5 Enforcing groundedness mechanically (unchanged principle,
restated for the new layering)

- Every tool Qwen can call returns **schema-validated, backend-sourced
  data only** — there is no tool through which Qwen can write a fact
  into the system, only read authoritative facts out.
- The narration step's system prompt instructs the model to state only
  facts present in the tool-call trace for the current turn.
- **Testable, not just prompted**: automated tests sample narration
  outputs and check that every number/time/place mentioned traces back
  to a tool result in that turn's trace — the concrete, checkable version
  of "never invent a route, fare, ETA, walking distance, timetable, or
  delay," per the senior's explicit requirement.
- If a user's request needs a capability with no corresponding tool
  (e.g. "cheapest route" before fare-aware ranking exists in Layer 4),
  Qwen is instructed to say so honestly rather than approximate an
  answer — an explicit, testable "graceful refusal" behavior.

---

## 7. Layer 4 — Deterministic Routing / Optimization (Dijkstra's actual
role, decided explicitly)

### 7.1 Decision

**Dijkstra remains.** It is retained as the pathfinding algorithm inside
the deterministic routing/optimization layer, exactly where it already
lives (`routing/search.py`), because:
- It is correct, fast enough at this network's scale (a city-pair
  transit network, not a continental road graph), already implemented,
  already tested, and already the right tool for exact-shortest-path
  computation over a graph with well-defined edge costs.
- The senior feedback explicitly warns against blindly deleting it in
  favor of an unproven neural model — and §5.1's research-grounded
  evaluation confirms that warning was correct: nothing in the current
  data or timeline justifies replacing it.
- Its role in the product narrative changes, not its implementation:
  it is **not** presented to judges as "the AI." It is presented as one
  well-chosen component inside a layered system whose actual AI
  differentiators are Layers 1–3's language/geospatial reasoning and
  Layer 2's agentic orchestration, plus the separately-staged ETA ML
  (§8). This reframing costs nothing in code and fixes the "AI wrapper
  around Dijkstra" perception risk the senior flagged.

### 7.2 Responsibilities (unchanged from the prior plan's Phase A,
reaffirmed and now explicitly scoped as "Layer 4")

- Valid transit path search (Dijkstra, existing).
- Transfer computation, walking-leg computation, travel-time totals
  (existing).
- Route filtering: `objective`, `max_walking_distance`, `max_transfers`
  (existing objective selection; filters are the scoped-but-not-yet-built
  extension, carried forward from the prior plan's Phase A1 — see §12).
- Multi-candidate journey responses (carried forward, same scope).
- Fare-constraint application: filtering/annotating candidates by fare
  once `get_fare_quote` is available as a tool (existing fares service,
  no change needed — it's already callable).

### 7.3 Contract with Layer 3 and Layer 2

Layer 4's public contract is, and remains, the existing
`POST /transit/journeys/search` HTTP endpoint (extended per §12) —
**this is deliberate**: Layer 2 calls it the same way the manual
frontend form does, which is the mechanical proof that AI cannot bypass
the deterministic engine (unchanged, load-bearing principle from the
prior revision).

```
Input (from Layer 2's search_journeys tool call, itself built from
Layer 3's resolved candidates):
  JourneySearchRequest { origin, destination, objective, max_walk_m?,
    max_transfers?, departure_time? }

Output (authoritative, unchanged shape from existing API):
  JourneySearchResponse { journeys: [Journey { legs, total_duration_s,
    total_walk_m, transfer_count, route_geometry, ... }] }
```

---

## 8. ETA ML Component (unchanged, reaffirmed as a separate component per
explicit instruction)

Kept exactly as previously designed — this section restates it briefly
for completeness in this kickoff document, without re-deriving it:

```
simulation/history (existing simulation engine as a generator)
        ↓
ETA training data (synthetic, Stage 2 — generated from timetable +
                    simulation behavior, no real telemetry required)
        ↓
ML model (Stage 3 — gradient-boosted trees recommended; linear
          regression as an explainable baseline; neural models
          explicitly not recommended for this timeline/data volume)
        ↓
Alibaba PAI-EAS (Stage 3/4 — confirmed generic custom-model deployment
                  path; deploy the trained artifact behind a small
                  inference wrapper)
        ↓
ML ETA — returned ALONGSIDE (never replacing) the deterministic
         simulation ETA, which remains the permanent fallback and the
         value shown whenever the ML service is unavailable or has no
         coverage for the requested route/time.
```

This component is architecturally independent of Layers 1–4: it
augments `get_vehicle_eta`'s response (an existing/near-existing tool in
§6.3's inventory) with an optional `ml_refined_eta` field. It has no
dependency on the Speech/NLP or Journey Planner layers and can be built
and demoed in isolation.

**Priority note (re-ranked in §11 below, per the two-day-prep /
hackathon-timeline instruction):** this remains valuable but is
correctly ranked below the core five-layer pipeline for demo purposes —
a working conversational-voice-to-map journey is the demo's spine; ETA
ML is a strong enhancement on top of it, not a substitute for it.

---

## 9. Carried-Forward Product Components (reaffirmed, not re-litigated)

These sections are unchanged in substance from the prior revision.
Restated briefly for kickoff-document completeness; see their fuller
prior treatment for detail not repeated here.

### 9.1 Map
MapLibre + OSM/CARTO-derived vector tiles (Google Maps not recommended —
API-key/billing/lock-in concerns, no material benefit for this region).
Layer separation: basemap, transit-data overlay, route geometry, user
location, realtime vehicle layer. Backend emits lat/lng/GeoJSON only.

### 9.2 User location
Device/browser geolocation as primary origin source; manual entry as
fallback; **never** IP-based inference for routing origin.

### 9.3 Route filtering (Qwen-assisted classification, backend-owned
enforcement)
Fixed filter set only: `objective` (fastest/fewest_transfers/
least_walking), `max_walking_distance_class` (strict/moderate/relaxed,
or an explicit number if the user gave one), `max_transfers` (explicit
integer or unconstrained). Not implemented, and not to be claimed by
narration: cheapest-route optimization, earliest-arrival/
latest-departure solving (needs time-dependent routing — Phase A2,
carried forward), accessibility filters (no data field exists — not
fabricated).

### 9.4 Realtime + simulation
`VehicleLocationProvider` Protocol abstraction unchanged — simulation
today, real feed later, no caller changes required. Remaining backend
work: `source: "simulated"` labeling, optional map-snapshot endpoint.

### 9.5 Fares
DB-driven `FareRule`, server-computed, unchanged. AI boundary: figures
narrated by Qwen must be copied verbatim from a `get_fare_quote` tool
result, never estimated.

### 9.6 Ticketing + QR
Unchanged, fully working. A conversational journey result is the same
shape a manually-searched one is, so "buy a ticket for this journey"
requires no backend change regardless of how the journey was found.

### 9.7 User accounts
Unchanged. Register/login/JWT/bcrypt/roles already work; extensible
fields (saved routes, history) explicitly deferred past hackathon scope.

### 9.8 Admin dashboard
Backend admin API exists, auth-gated. Hackathon-relevant additions:
realtime/simulation status view, ticket inspection, data-quality view,
and (new, carried forward) an AI/ETA subsystem health panel — cheap to
build, demonstrates graceful degradation to judges.

---

## 10. Alibaba Services Requiring Kickoff Verification

Unchanged findings from the prior revision's research, consolidated
here as the concrete Day-1 checklist:

| Item | Status | Verification action |
|---|---|---|
| Model Studio access (Qwen chat, tool-calling) for the hackathon account | Documented and current; account-level access unconfirmed | Issue API key, make one successful tool-calling chat completion |
| Qwen3-ASR / Fun-ASR / Paraformer — English | Confirmed language support | One live transcription test |
| Qwen3-ASR / Fun-ASR / Paraformer — Urdu | **Not confirmed** in published language lists | Test against a real Urdu audio sample; record yes/no |
| CosyVoice / Qwen-TTS — English | Confirmed language support | One live synthesis test |
| CosyVoice / Qwen-TTS — Urdu | **Not confirmed** in published language lists | Test against Urdu text; record yes/no |
| Qwen3.5-Livetranslate / Omni family (broader language speech-to-speech) | Broader language claims, Urdu coverage specifically unconfirmed | Only worth testing if the above Urdu ASR/TTS tests fail and time permits |
| PAI-EAS custom model deployment | Documented generic-model deployment path confirmed | One trivial stub-endpoint deployment to validate the path before the real ETA model is trained |
| Hackathon-provided credits/quota specifics | Not published generally — organizer-specific | Confirm directly from onboarding materials, do not assume a figure |
| Qoder | Confirmed as a development tool (AI-native coding assistant), not a runtime architecture component | No verification needed — just don't design it into the product diagrams |

**Outcome of this checklist directly gates only Layer 1's ASR/TTS model
choice** (§4.5's fallback already absorbs a "no" on Urdu without
blocking anything else) — no other layer's design depends on how this
checklist resolves.

---

## 11. Hackathon Priority Ranking (re-ranked aggressively per the
two-day-prep / demo-focused instruction)

### P0 — must work for a credible demo
1. Real interactive map (MapLibre/OSM, existing geometry data)
2. Device live location
3. Real transit stops/routes (existing data foundation)
4. Route geometry rendering where available (existing, coverage-limited)
5. Geospatial location resolution (Layer 3 — mostly existing capability,
   newly exposed as tools)
6. Journey planning (Layer 4 — existing, extended with filters, Phase
   A1)
7. Route filtering (Layer 4 + Qwen classification, §9.3)
8. Conversational AI — **text first**, English + Urdu + Roman Urdu
   (Layer 2, built directly on Qwen's confirmed multilingual text
   capability — no Alibaba-speech dependency for this P0 item)
9. Voice input — **at minimum English**, via confirmed Alibaba ASR
   (Layer 1)
10. Qwen Journey Planner acting as an agent (tool selection,
    clarification — §6, not just parsing)
11. Simulation displayed on the map (existing)
12. ETA (deterministic baseline — existing; this is the P0 ETA, not the
    ML-refined one)
13. Ticket purchase + QR ticket (existing)
14. Authentication (existing)

**Note on sequencing within P0:** items 1–7 and 11–14 are almost
entirely *integration* of already-verified backend capability with a
frontend built during the hackathon — they are lower-risk than items
8–10, which are new build. Sequence the hackathon's early hours toward
getting 1–7/11–14 wired end-to-end (a fully working manual-form
version of the product) **before** layering the conversational pipeline
on top, so there is always a working, demoable product even if Layers
1–2 run into unexpected trouble.

### P1 — major differentiators, build if P0 is solid with time to spare
- Voice input/output for Urdu and Roman Urdu (native Alibaba path if
  §10 confirms it; otherwise the client-side fallback per §4.5 — either
  way this is P1, not P0, because P0's conversational requirement is
  already satisfied by text)
- Predictive ETA ML (§8) — strong differentiator, but correctly ranked
  below the core pipeline; a partial result (trained model without full
  PAI-EAS deployment, demoed via a local inference call) is an
  acceptable fallback demo if time runs short
- Multi-turn conversational follow-up ("which one has less walking?",
  "is the bus late?") — §6.2's multi-turn context
- TTS spoken responses (any language)
- Richer admin dashboard (AI/ETA health panel, data-quality view)
- Fare integration into conversational narration (low-cost once Layer 4
  filters land — likely achievable within P0/P1 boundary depending on
  time)

### P2 — stretch / explicitly future, not hackathon scope
- Native Alibaba Urdu speech-to-speech if §10 confirms viability but
  time doesn't allow full integration
- Per-user saved routes/favorites/history-informed suggestions
- Stage 4 real-observation ETA feedback loop (needs a real vehicle feed
  that does not exist)
- Additional transit operators/agencies, WebSocket realtime (decision
  gated per the prior plan, unchanged), production-scale hardening,
  full admin CRUD, advanced analytics

---

## 12. Implementation Notes for Qoder Handoff

This section exists specifically to make the blueprint actionable at
kickoff.

- **Give Qoder this repository as-is, plus this document, as the
  starting point.** The deterministic backend (§2) is reference code to
  build on top of and extend — not to be regenerated from scratch.
- **Build order recommendation** (supports the P0 sequencing note in
  §11): (1) extend `routing/` with filters + multi-candidate responses
  (small, well-scoped, existing code to extend — the prior plan's Phase
  A1); (2) stand up the frontend map + manual journey form against the
  existing/extended API, so a working non-AI product exists early; (3)
  build Layer 3 as a thin tool-exposing wrapper around existing
  `routing/snapping.py` and geocoding code — genuinely mostly
  integration; (4) build Layer 2 (Qwen + tool-calling) against Layers 3
  and 4's now-stable contracts; (5) build Layer 1 (ASR/TTS) last, since
  its contract (§4.3) is stable and simple regardless of which
  underlying model fulfills it, and its own internal choice (Alibaba vs.
  fallback) is the one item genuinely gated on §10's kickoff-day
  findings.
- **Every layer's contract in this document (§4.3, §5.3, §6.3, §7.3) is
  the interface Qoder should implement against** — treat them as fixed
  points that let different people/sessions build different layers in
  parallel once Layer 4's existing API and Layer 3's tool signatures are
  agreed, without waiting on Layer 2's internal prompt-engineering to
  stabilize first.
- **Do not let ETA ML (§8) block the core pipeline.** It is
  architecturally and practically independent; build it in parallel or
  after P0 lands, never as a prerequisite for the conversational journey
  flow.
- **Testing discipline carried forward, restated for kickoff:** the
  532 existing tests must not regress; new layers get groundedness tests
  per §6.5, not just happy-path demos — a hallucination caught in
  testing is far better than one caught by a judge.

---

## 13. Component Classification Summary (for quick reference)

| Component | Classification | Status |
|---|---|---|
| Agencies/routes/stops/timetables/import | Deterministic | Verified foundation |
| PostGIS spatial queries, Nominatim geocoding | Geospatial | Verified foundation, being exposed as tools |
| OSRM route geometry | Geospatial | Verified foundation, coverage-limited |
| Bus simulation engine | Deterministic | Verified foundation |
| Dijkstra / journey search | Deterministic | Verified foundation, extending with filters (P0) |
| Fares (`FareRule`) | Deterministic | Verified foundation |
| Ticketing + QR | Deterministic | Verified foundation |
| Authentication | Deterministic | Verified foundation |
| Admin API | Deterministic | Verified foundation, partial |
| ASR / TTS | AI/ML (dedicated speech model) | New build (P0 English / P1 Urdu) |
| Language detection/normalization | AI/ML (lightweight) or rule-based | New build, part of Layer 1 |
| Qwen Journey Planner (intent, clarification, tool selection, narration) | AI/ML (agent) | New build (P0) |
| Location/place resolution logic | Geospatial (exposed as a tool) | Mostly-existing, new packaging (P0) |
| ETA ML model | AI/ML | New build, staged (P1) |
| Map rendering, live location UI | Frontend | New build (P0), consumes existing/extended backend contracts |
| Realtime vehicle layer on map | Frontend + existing backend | New build (P0), consumes existing data |

---

## 14. Global Constraints (unchanged, restated as non-negotiable)

- The 532 existing tests must not regress.
- No part of the already-verified foundation (§2) is rebuilt without a
  concrete architectural reason — none exists at this time.
- AI (any layer) never produces an authoritative route, fare, ETA,
  walking distance, timetable, or delay value — it requests operations
  from deterministic/geospatial layers and explains their results.
- Every AI-dependent feature has a defined, working fallback so that
  Alibaba service unavailability during the live demo degrades
  gracefully rather than breaking the product.
