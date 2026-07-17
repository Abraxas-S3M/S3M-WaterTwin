# S3M-Core Quad-Engine Contract

> **Provenance.** This document was written by reading the real S3M-Core source
> at [`Abraxas-S3M/S3M-Core`](https://github.com/Abraxas-S3M/S3M-Core),
> specifically the `src/quad_engine/` package
> (`models.py`, `routes.py`, `audit_log.py`, plus `__init__.py` and
> `packet_router.py` for corroboration). It reflects the code as cloned, not a
> guess. S3M-Core is treated as read-only upstream; WaterTwin does **not** modify
> it. Where WaterTwin will diverge or extend, it is called out explicitly.

The Quad-Engine Orchestration layer receives an **operational packet**,
classifies and routes it to four advisory reasoning engines (tactical,
reasoning, planning, Arabic), and returns a **structured, commander-ready
result**. Every result is `human_review_required`; nothing in the contract
authorizes autonomous or kinetic action. WaterTwin adopts this same conductor
posture for the water domain.

---

## 1. HTTP API

All routes are mounted under the prefix **`/api/quad-engine`**
(`APIRouter(prefix="/api/quad-engine", tags=["Quad-Engine Orchestration"])`).

| Method | Path                              | Handler                  | Request body          | Response model        | Purpose |
|--------|-----------------------------------|--------------------------|-----------------------|-----------------------|---------|
| `POST` | `/api/quad-engine/packet`         | `quad_engine_packet`     | `OperationalPacket`   | `QuadEngineResult`    | Classify, route, and orchestrate a single packet. Returns structured output even with no local models present. |
| `GET`  | `/api/quad-engine/status`         | `quad_engine_status`     | –                     | `OrchestratorStatus`  | Report orchestration-layer status and safety posture. |
| `GET`  | `/api/quad-engine/engines`        | `quad_engine_engines`    | –                     | `{"engines": [EngineRecord...], "total": int}` | List the four engines and their current status. |
| `GET`  | `/api/quad-engine/results/{result_id}` | `quad_engine_result` | – (path param)        | `QuadEngineResult`    | Retrieve a previously produced result by id. `404` if not found. |
| `GET`  | `/api/quad-engine/audit`          | `quad_engine_audit`      | – (query: `limit=50`, `action`) | `{"logs": [...], "total": int}` | Return recent orchestration audit entries. |
| `POST` | `/api/quad-engine/demo/cop-brief` | `quad_engine_cop_brief`  | `CopBriefRequest` (optional) | `QuadEngineResult` | Deterministic commander brief from the Saudi MOD COP demo. |

**Accuracy notes vs. the task brief:**
- The result-retrieval path parameter is named **`{result_id}`** (the task brief
  abbreviated it as `/results/{id}`).
- `/audit` accepts optional query params `limit` (default `50`) and `action`
  (filter by action string).
- `POST /demo/cop-brief` is an additional endpoint present in the real code; it
  is not part of the core five but is documented here for completeness.

---

## 2. Schemas (`src/quad_engine/models.py`)

All schemas are Pydantic `BaseModel`s. Field defaults and validation constraints
below are taken verbatim from the source.

### 2.1 Enums

**`PacketType`** (`str, Enum`) — inbound packet classification:

| Value | Enum member |
|-------|-------------|
| `track_update` | `TRACK_UPDATE` |
| `alert` | `ALERT` |
| `decision_request` | `DECISION_REQUEST` |
| `feed` | `FEED` |
| `operator_note` | `OPERATOR_NOTE` |

**`EngineStatus`** (`str, Enum`) — operational status of a single engine:

| Value | Meaning |
|-------|---------|
| `live_local` | An on-device GGUF model produced the output. |
| `placeholder` | A deterministic, doctrine-shaped stand-in was used (the demo must never go blank). |
| `unavailable` | The engine could not contribute at all. |

**`EngineRole`** (`str, Enum`): `tactical`, `reasoning`, `planning`, `arabic`.

### 2.2 `OperationalPacket` (inbound / submit)

| Field | Type | Default | Constraints |
|-------|------|---------|-------------|
| `packet_id` | `str` | *required* | `min_length=1, max_length=128` |
| `source` | `str` | `"cop"` | `max_length=64` |
| `track` | `str` | `"saudi_mod"` | `max_length=64` |
| `packet_type` | `PacketType` | `PacketType.TRACK_UPDATE` | enum |
| `classification` | `str` | `"UNCLASSIFIED_DEMO"` | `max_length=64` |
| `payload` | `Dict[str, Any]` | `{}` (`default_factory=dict`) | |
| `requested_outputs` | `List[str]` | `["sitrep", "threat_assessment", "coa_options", "arabic_summary"]` (`DEFAULT_REQUESTED_OUTPUTS`) | |

### 2.3 `QuadEngineResult` (outbound / result)

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `result_id` | `str` | *required* | |
| `packet_id` | `str` | *required* | echoes the source packet |
| `route` | `RouteInfo` | *required* | **object, not a string** (see §2.5) |
| `outputs` | `Dict[str, Any]` | `{}` | keyed by output name (e.g. `sitrep`, `threat_assessment`, `coa_options`, `arabic_summary`) |
| `decision_cards` | `List[DecisionCard]` | `[]` | |
| `confidence` | `float` | `0.0` | `ge=0.0, le=1.0` |
| `human_review_required` | `bool` | `True` | safety default |
| `engine_status` | `Dict[str, EngineStatus]` | `{}` | per-engine `live_local` / `placeholder` / `unavailable` |
| `classification` | `str` | `"UNCLASSIFIED_DEMO"` | |
| `timestamp` | `str` | ISO-8601 UTC (`default_factory`) | |

### 2.4 `DecisionCard`

| Field | Type | Default |
|-------|------|---------|
| `title` | `str` | *required* |
| `summary` | `str` | *required* |
| `priority` | `str` | `"medium"` |
| `status` | `str` | `"human_review_required"` |
| `recommended_action` | `str` | `""` |

A decision card is a **recommendation surfaced to a commander, never an
autonomous action**. `status` defaults to `human_review_required`; the demo layer
never marks a card executed or authorizes kinetic effects.

### 2.5 Supporting schemas

**`RouteInfo`** (routing decision produced by the packet router):

| Field | Type | Default |
|-------|------|---------|
| `primary_engine` | `str` | *required* |
| `supporting_engines` | `List[str]` | `[]` |
| `reason` | `str` | `""` |
| `route_hint` | `str` | `"tactical"` |

**`CoaOption`**: `option_id`, `name`, `description`, `risk="medium"`,
`confidence: float (0.0–1.0)`.

**`EngineRecord`** (GUI-safe engine view): `engine_id`, `display_name`,
`role: EngineRole`, `status: EngineStatus`, `model_present=False`,
`max_tokens=512`, `description=""`.

**`ModelRegistryEntry`** (internal): `engine_id`, `display_name`, `model_file`
(bare filename only — resolved against a trusted models dir, never from user
input), `role`, `status=placeholder`, `max_tokens=512 (1–4096)`, `description`.

**`OrchestratorStatus`** (returned by `GET /status`): `status="operational"`,
`mode="demo"`, `local_llm_enabled=False`, `local_llm_available=False`,
`models_dir=""`, `engines: Dict[str, EngineStatus]`,
`autonomous_action_enabled=False`, `human_review_required=True`,
`external_apis_called=False`, `timestamp`.

---

## 3. Routing (`src/quad_engine/packet_router.py`)

Routing is **deterministic and offline** — it never calls a model, it only
decides which advisory engines the orchestrator consults. Canonical engine ids:
`tactical_engine`, `reasoning_engine`, `planning_engine`, `arabic_engine`.

| Packet type | Primary engine | Supporting engines |
|-------------|----------------|--------------------|
| `track_update` | `tactical_engine` | reasoning, planning, arabic |
| `alert` | `reasoning_engine` | tactical, planning, arabic |
| `decision_request` | `planning_engine` | reasoning, tactical, arabic |
| `feed` | `tactical_engine` | reasoning, arabic |
| `operator_note` | `tactical_engine` | reasoning, planning, arabic |

`route_hint` vocabulary shared with the COP event bus:
`tactical` / `reasoning` / `planning` / `arabic_nlp`. The router also appends
payload-aware context (e.g. `domain=…`, `affiliation=…`, and an
"elevated reasoning priority" note for hostile/suspect/unknown affiliation) to
the routing `reason` for the audit trail.

---

## 4. Audit log (`src/quad_engine/audit_log.py`) — and the WaterTwin gap

S3M-Core's `AuditLog` is a **thread-safe, bounded, in-memory ring buffer**
(`collections.deque(maxlen=max_entries)`, default `1000`). Each entry is:

```json
{ "id": "<12-hex>", "timestamp": "<iso8601-utc>", "action": "<str>", "details": {} }
```

It is accessed via a process-wide singleton (`get_audit_log()`) and exposes
`record`, `recent(limit, action)`, `count`, `clear`.

Explicitly by design in S3M-Core, the buffer:
- performs **no disk writes** (so it cannot leak classified payloads),
- performs **no network egress**, and
- **never records model paths or credentials**.

### ⚠️ The gap WaterTwin must close (Phase 5)

Because the S3M-Core audit log is **in-memory only**, it does **not survive a
process restart** and cannot serve as a durable, queryable system of record.
For the water domain, oversight and reversibility require a persistent trail.

**WaterTwin will add a durable Postgres-backed audit store in Phase 5**,
preserving the same append-only, human-in-the-loop semantics (recording that no
autonomous action was taken and that human review was required) while adding
durability, indexing, and long-horizon retention. The upstream in-memory buffer
remains untouched; WaterTwin adds its own persistence layer alongside it.

---

## 5. Safety doctrine baked into the contract

- Every `QuadEngineResult` carries `human_review_required=True`; every
  `DecisionCard` defaults to `status="human_review_required"`.
- `OrchestratorStatus` reports `autonomous_action_enabled=False` and
  `external_apis_called=False`.
- `engine_status` is reported per engine so a live model is never mistaken for a
  deterministic placeholder — the demo never goes blank, but it is always honest
  about provenance.
- No model paths, credentials, or vault keys are ever surfaced through the API;
  the GUI only ever receives recommendations / briefs / summaries.

WaterTwin inherits this doctrine: it is the **conductor** (routing, briefing,
audit, human-in-the-loop), not the physics engine, and it is strictly
advisory/read-only with respect to plant control (see
`docs/adr/ADR-0001-conductor-not-physics.md` and
`docs/security/control-boundaries.md`).
