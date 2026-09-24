# WORK I — Canonical Knowledge / Evidence Contract V1

- Document: `docs/work_i/WORK_I_CANONICAL_KNOWLEDGE_EVIDENCE_CONTRACT_V1.md`
- Task ID: TRADINGAI-WORK-I-CANONICAL-KNOWLEDGE-EVIDENCE-CONTRACT-AND-LEGACY-BRANCH-RECONCILIATION-RESUME-1
- Workstream: WORK I — AI Advisor / Supervisor Knowledge & Independent Operation
- Status: DESIGN / CONTRACT (frozen for implementation planning; no runtime effect)
- Base ref: `f553439ada1e9955242b643ef246986305a45a3f`
- Authority input: `tmp/chatgpt_reviews/TRADINGAI-WORK-I-ADVISOR-SUPERVISOR-KNOWLEDGE-AUTO-PERSISTENCE-AUDIT-1.md` (PASS)
- Scope: design-only. This document changes no application code, no DB, no runtime, no authority.

This contract is the single normative description of how TradingAI Knowledge and Trade/Decision
**Evidence** are identified, enveloped, stored, retrieved and consumed by the AI Advisor and the
Supervisor. It intentionally references existing single sources of truth rather than creating new
stores. The legacy branch `feature/ai-knowledge` is evaluated separately in
`docs/work_i/WORK_I_FEATURE_AI_KNOWLEDGE_RECONCILIATION_PLAN.md`.

---

## A. Authority Principles

1. **TradingAI is the Knowledge / Evidence Authority.** Canonical facts about what the system
   observed, decided and did originate in TradingAI runtime producers and their durable stores. The
   Advisor and Supervisor are consumers of evidence, never authors of it.
2. **Advisor is ADVISORY AUTHORITY only.** `ADVISOR_AUTHORITY = READ_ONLY`. Advisor output is
   information for the operator; it can never become a command, order, configuration change, LIVE
   arm, or execution trigger. Advisor chat never emits a write-side knowledge mutation.
3. **Supervisor does not replace existing MM / Governance / Execution Authority.** Supervisor is a
   read-only SHADOW oversight / analysis layer (`SUPERVISOR_AUTHORITY = READ_ONLY_ANALYSIS`). It
   observes and explains; it does not command.
4. **Frontend state is not authoritative.** Browser state (including `localStorage`) is presentation /
   draft only. It can never be the canonical source for configuration, revision, evidence, or
   authority. (See § I.6 re: dashboard Trade Settings `localStorage`.)
5. **PAPER and LIVE share one schema.** A single canonical envelope with `mode` / `scope` fields is
   used for both; mode-specific blocks are additive and optional.
6. **Runtime-only information is distinguished from persisted Evidence.** A field that exists only in
   an in-memory snapshot is labelled runtime-only and is never treated as restart-queryable evidence.
7. **UNKNOWN is never back-filled with a guess.** Missing evidence is represented explicitly
   (§ F); the system never invents a value (e.g. `0.5`, `1.0`) to fill a gap.
8. **Secrets are never stored.** No credentials, tokens, cookies, API keys, env var values, or raw
   exchange payload secrets enter any evidence store or prompt. Redaction metadata is recorded in the
   envelope.
9. **restart-queryable.** Every canonical evidence record must be retrievable after a process restart
   from a durable store; in-memory-only sources are not canonical evidence.
10. **idempotent.** Writing the same logical event/record twice must yield the same logical state
    (deterministic IDs, append-once, no duplicate side effects).
11. **provenance-preserving.** Every record carries where it came from, its truth layer, and its
    linkage. Provenance is never overwritten or flattened.

Truth hierarchy (never inverted), reused from the legacy `knowledge_core` design where applicable:

1. `CANONICAL_SPECIFICATION`  2. `CURRENT_SOURCE_RUNTIME`  3. `VALIDATED_KNOWLEDGE`
4. `OBSERVATION_FINDING`      5. `HYPOTHESIS`

Authority classes that this contract only *describes* (never assumes): `EXECUTION_AUTHORITY`,
`GOVERNANCE_AUTHORITY`, `CONFIGURATION_AUTHORITY`, `RECORDING_AUTHORITY`, `OBSERVATION_READ_ONLY`,
`RESEARCH_READ_ONLY`.

---

## B. Existing Single Sources of Truth

For each item: Producer → Writer → Store → Reader → Consumer, current gap, reuse decision.
("Reuse" = the canonical source this contract binds to; it is never re-implemented by WORK I.)

| # | Source of truth | Producer | Writer | Store | Reader | Consumer | Current gap | Reuse decision |
|---|---|---|---|---|---|---|---|---|
| B1 | Stage 13 completed-trade record | `execution_engine.py` close path (`:3132`) | `ParameterPerformanceStore.record_completed_trade` (`backend/runtime/parameter_performance.py:361`, `:482`) | `logs/runtime/parameter_performance.jsonl` (append+fsync) | `trade_history_read.py:252`; `parameter_performance_read.py:287` | `GET /api/trade-history`; perf endpoints | no dedup / primary-key enforcement; no decision/MM/governance/fee join | **CANONICAL.** Extend via versioned additive fields only. |
| B2 | Trade History (read model) | Stage 13 | — (derived) | — (derived) | `TradeHistoryService` (`backend/runtime/trade_history_read.py:197`) | `backend/api/trade_history.py:52,109` | filter by scope/mode only | **REUSE** as the canonical trade reader. |
| B3 | Parameter Performance | Stage 13 | derived | — | `compute_metrics` (`parameter_performance_read.py:69`) | `backend/api/parameter_settings.py:204,244` | revision-scoped only; no per-symbol/paper-vs-live in one endpoint | **REUSE** `compute_metrics`. |
| B4 | Parameter Revision | operator promotion (`promotion_service.py:447`) | `ParameterRevisionArchive` (`backend/strategy/parameters/revision_archive.py:80`) | `logs/runtime/strategy_parameters/rev-<n>.json` (immutable) | `revision_archive.py:95`; `store.py:399` | settings API | superseded/rollback relation not exposed | **CANONICAL.** Do not fork. |
| B5 | MM state / timeline | MM boundary | `loss_persistence_adapter.py:95`; `timeline.py:261`; `monitoring.py:95` | `loss_limit_state.json`; `money_management_timeline.jsonl`; `money_management_monitoring.json` | `loss_persistence_adapter.py:137`; `timeline.py:374`; `loss_http_api.py:546` | MM UI / status | no cycle linkage | **CANONICAL** for MM evidence. |
| B6 | Governance runtime | governance runtime | in-memory only (`governance_runtime.py:327`) | none (in-memory `governance_state`, `emergency_timeline` `:10,:36`) | `governance_runtime` | governance status API | **NOT durable**; not linked to trades | **DO NOT DUPLICATE.** Persist only via a separately-approved bounded task; never create a second governance authority. |
| B7 | Supervisor SQLite events | shadow evaluators | `SupervisorAuditStore.append` (`backend/supervisor/audit_store.py:27,66`) | `logs/runtime/supervisor_audit.sqlite3` | `audit_store.py:45,58,78,87` | history/replay routers | 5000-cap has no eviction; no trade/MM history reader | **CANONICAL** for supervisor events. |
| B8 | Advisor runtime reader | runtime authorities | — (read-only) | — (live) | `read_runtime_scalars` (`backend/ai_advisor/runtime_reader.py:380`) | `build_runtime_context` (`context_builder.py:235`) | runtime-only, not evidence | **REUSE** for current-runtime context; not canonical evidence. |
| B9 | Trading trace | engine stage emits | `TradingTraceStore.safe_record` (`backend/runtime/trading_trace.py:408,526`) | `logs/runtime/trading_e2e_trace.jsonl` (33.6 GB) | reader never reloads (`:373`) | `backend/api/trading_trace.py` | not restart-queryable; not joined to canonical record; size | **CANONICAL writer.** P0: make restart-safe (§ L). |
| B10 | PAPER account | paper engine | `paper_account_store.py:134,152` | `paper_account_state.json`; `paper_account_history.jsonl` | `paper_account_store.py:101` | account/status | PAPER-only; no LIVE counterpart snapshot | **REUSE** as PAPER capital evidence. |
| B11 | LIVE exchange evidence | exchange adapters + close path | embedded in Stage 13 `live_record` (`execution_engine.py:3210-3223`) | Stage 13 record | trade history | UI | no ACK/partial/reject/fee/slippage/latency fields | **CANONICAL** for LIVE fill evidence; extend via versioned fields. |
| B12 | Configuration / Parameter Settings baseline (NEW, `f553439`) | operator | `ParameterSettingsService.persist_baseline_if_missing` (`backend/strategy/parameters/settings_service.py`), endpoint `POST /api/parameter-settings/persist-baseline` (`backend/api/parameter_settings.py`) | `logs/runtime/strategy_parameters/*.json` + `rev-<n>.json` | settings store (`store.py:399`) | configuration API; START | baseline now persistable idempotently; snapshot↔cycle link still absent | **CANONICAL** configuration authority. WORK I references it; never re-implements. |
| B13 | Risk-percent authority (NEW, `f553439`) | MM config | `backend/money_management/risk_percent_authority.py` | derived from MM config + parameter store | `bot_manager` status/START/executability | status API; AMS | resolves MM-first; explicit `riskPercentSource`; fails closed | **CANONICAL.** Never invent `0.5`. |
| B14 | Spread unit classification (NEW, `f553439`) | contract constant | `backend/strategy/parameters/spread_unit_classification.py` | constant + store provenance | `settings_service._scope_provenance` | configuration API (`unitProvenance`) | LIVE percent interpretation explicitly blocked | **CANONICAL.** Reference only. |

---

## C. Canonical Identifiers

All evidence records use these identifiers. An identifier is either a present string or an explicit
availability state (§ F) — never a fabricated value.

| Identifier | Meaning | Primary producer |
|---|---|---|
| `cycle_id` | One trading cycle (Stage 0 → Stage 14) instance. | runtime cycle orchestration |
| `trade_id` | One completed/attempted trade. | Stage 13 record (`tradeId`) |
| `event_id` | One durable event (e.g. supervisor event, trace event). | supervisor audit / trace |
| `evidence_id` | Deterministic ID of one canonical evidence envelope. | evidence writer (this contract) |
| `correlation_id` | Groups all evidence emitted for one decision/execution attempt across subsystems. | evidence writer |
| `configuration_revision_id` | Configured revision from the settings store (scope-aware). | parameter settings store |
| `parameter_revision_id` | Immutable `rev-<n>` parameter revision. | parameter revision archive |
| `task_id` | Originating WORK/task identifier (provenance). | operator / pipeline |
| `acceptance_id` | Acceptance/verification identifier (provenance). | operator / pipeline |
| `commit_sha` | Git commit SHA associated with the code that produced the record. | build/runtime provenance |
| `parent_event_id` | The event that caused this event (causal chain). | producer |
| `source_record_id` | The primary-key/id of the upstream authoritative record joined into the envelope. | producer |

Rules: identifiers are opaque strings; no identifier is inferred from another unless the source
declares it; `configuration_revision_id` and `parameter_revision_id` are distinct concepts
(configured/effective vs immutable archive).

---

## D. Canonical Evidence Envelope

Every canonical evidence record is a JSON object with this envelope. Domain payloads live under
`payload` and are schema-versioned by `schema_version` + `evidence_type`.

| Field | Type | Description |
|---|---|---|
| `schema_version` | string | Envelope schema version (starts `evidence-envelope/v1`). |
| `evidence_type` | string (enum) | Domain evidence type (§ G), e.g. `AI_DECISION`. |
| `lifecycle_stage` | string (enum) | One of the 15 stages (§ E). |
| `occurred_at` | timestamp \| null | When the fact occurred (source time). |
| `recorded_at` | timestamp | When the record was durably written. |
| `mode` | enum | `PAPER` \| `LIVE` (shared schema). |
| `symbol` | string \| null | Instrument. |
| `timeframe` | string \| null | Timeframe if applicable. |
| `cycle_id` | id \| availability | Cycle correlation. |
| `trade_id` | id \| availability | Trade correlation. |
| `event_id` | id | Unique id of this evidence event. |
| `source` | object | Producer identity (subsystem, module, symbol). |
| `authority` | enum | `OBSERVATION_READ_ONLY` \| `RECORDING_AUTHORITY` \| … (never execution). |
| `payload` | object | Domain-specific, bounded, redacted body. |
| `provenance` | object | Truth level, source reference, version/hash, verification flag. |
| `integrity` | object | Hash/digest + algorithm for tamper-evidence. |
| `availability` | object | Per-field availability map (§ F) for nullable/enriched fields. |
| `redaction` | object | What was redacted and why (secret scrubbing proof). |
| `links` | object | Related ids: `parent_event_id`, `source_record_id`, trace/decision/order/fill ids, revision ids. |

Invariants:
- `event_id` is deterministic where the source supports it; duplicate writes are idempotent.
- `payload` never contains secrets; `redaction` records any removal.
- `authority` is descriptive and can never be an execution/governance/MM authority for Advisor or
  Supervisor evidence.
- Unknown values are represented via `availability`, not omitted silently and not guessed.

---

## E. Fifteen-Stage Mapping

The 15 lifecycle stages (0–14) map to evidence as follows. "P" = producer, "Store" = durable sink.

| Stage | Name | Primary evidence | Current producer/store | Gap |
|---|---|---|---|---|
| 0 | Parameter Context | parameter set + configured/effective revisions; spread unit provenance; risk-percent authority | settings store + revision archive + `f553439` provenance | snapshot↔cycle link |
| 1 | Market Selection | AUTO candidate + selection reason | AMS lifecycle (runtime-only) | not persisted per cycle |
| 2 | Market Data | market context observation | trading trace | reader not restart-safe |
| 3 | Feature Builder | feature evidence | trading trace `:295` | not joined to canonical record |
| 4 | Micro Edge Strategy | strategy signal / rejection | trading trace STRATEGY | not joined |
| 5 | AI Decision / Review | decision + reason + rejection reason | trading trace AI stage `:358` | not joined |
| 6 | Money Management | MM decision + risk + quantity + leverage | MM state/timeline + `f553439` risk authority | no cycle linkage |
| 7 | Governance | governance decision + permission + block reason | in-memory only | **not durable** |
| 8 | Execution | intended/normalized order; exchange request; ACK; fill/partial/reject; fee; slippage; latency | Stage 13 `live_record` (LIVE); in-memory (PAPER); trace | fee/slippage/latency/ACK/partial/reject missing |
| 9 | Position | position state | Stage 13 record | — |
| 10 | Exit Monitoring | exit decision | Stage 13 `exitReason` + trace | — |
| 11 | Settlement / Exit Execution | close request + close fill | Stage 13 `live_record` (LIVE) | PAPER close evidence partial |
| 12 | Position Closed | final exchange position; final FLAT | Stage 13 `final_position` | LIVE-only today |
| 13 | Trade / Parameter Performance Record | gross/net PnL; performance metrics | Stage 13 JSONL | fee not itemized (gross=net on PAPER) |
| 14 | Ready for Next Trade | cycle completion / readiness | runtime + `f553439` readiness/authority status | not persisted as evidence |

Every envelope's `lifecycle_stage` is one of these 15; a record spanning stages uses `links` to
connect stage evidence for one `cycle_id` / `trade_id`.

---

## F. Availability Semantics

`null` alone must not encode multiple distinct states. Every nullable/absent field carries an
explicit availability state (in the envelope `availability` map or field-level marker):

| State | Meaning |
|---|---|
| `VALUE_PRESENT` | Real value is present. |
| `NOT_APPLICABLE` | Field is meaningless for this evidence type/mode. |
| `NOT_AVAILABLE` | Field should exist for this source but the source is not currently reachable. |
| `NOT_CAPTURED` | The system does not (yet) capture this; a real gap. |
| `CAPTURE_FAILED` | Capture was attempted and failed; failure is recorded. |
| `REDACTED` | Value existed but was removed for secret/privacy reasons. |
| `UNKNOWN` | Truth is genuinely unknown; never guessed. |
| `LEGACY_UNVERIFIED` | Historical record predating this contract; not verified under V1. |

Rules: consumers must branch on availability, not truthiness; `UNKNOWN`/`NOT_CAPTURED` must never be
silently converted to a default; a `CAPTURE_FAILED` must preserve the failure reason.

---

## G. Domain Evidence

Minimum evidence types (each an `evidence_type`):

- **AUTO candidate / selection reason** — candidate set, chosen candidate, reason, AMS stage.
- **Market Context / Feature Evidence** — symbol, timeframe, observation, feature vector summary.
- **AI decision / reason / rejection** — decision, reason code, rejection reason, model/provider
  (no secrets), provider-neutral.
- **MM decision / risk / quantity / leverage** — decision, `risk_percent` with source
  (`riskPercentSource`/`riskPercentAuthority` per `f553439`), quantity, effective leverage.
- **Governance decision / permission / block reason** — allow/block, reason, rule id.
- **Intended / normalized order** — intent, normalized order (symbol/side/type/qty/price).
- **Exchange request** — request identity (redacted), idempotency key, timestamp.
- **ACK** — exchange acknowledgement + latency.
- **partial fill / fill / reject** — fills with qty/price/fee; partials; reject reason.
- **fee** — itemized fee (maker/taker), currency.
- **slippage** — intended vs executed price delta.
- **latency** — request→ACK and ACK→fill durations.
- **Position** — entry price/qty, side, open state, position id.
- **Exit decision** — exit reason/rule, trigger.
- **Close request / fill** — close order + close fill.
- **Gross / Net PnL** — gross, fees, funding, net; authoritative flag.
- **Reconciliation** — attempts, deltas, final reconciled state.
- **Final exchange state / Final FLAT** — final position + flat confirmation.
- **Parameter / Trade Settings revisions** — configured/effective revisions, parameter snapshot,
  unit provenance, `f553439` baseline persistence result.
- **task_id / commit SHA / Acceptance result** — provenance linkage.

Each type declares required identifiers, allowed payload fields, redaction rules, and availability
defaults. Any field not captured today must be `NOT_CAPTURED`, not absent.

---

## H. PAPER / LIVE Common Schema

**Common fields (both modes):** `schema_version`, `evidence_type`, `lifecycle_stage`, `mode`,
`symbol`, `timeframe`, `cycle_id`, `trade_id`, `event_id`, `correlation_id`, `source`, `authority`,
`occurred_at`, `recorded_at`, `provenance`, `integrity`, `availability`, `redaction`, `links`, and
the shared trade fields (`side`, `entryPrice`, `exitPrice`, `quantity`, `realizedPnl`,
`exitReason`, `configuration_revision_id`, `parameter_revision_id`).

**PAPER-specific fields:** simulated fill model/source, `paper_account_state` capital/balance/equity,
PAPER `grossPnL == netPnL` semantics, paper fill ids.

**LIVE-specific fields:** exchange order id, raw order (redacted), `final_position`/`finalPosition`,
`positionState`, `openOrderState`, `reconciliationAttempts`, `realizedPnlAuthoritative`, ACK,
partial-fill, reject, fee (maker/taker), slippage, latency.

**Comparison key:** `(mode, symbol, configuration_revision_id, parameter_revision_id)` scoped by
`period`. LIVE and PAPER records with the same comparison key are comparable.

**revision scope:** comparisons are only valid within a fixed `configuration_revision_id` and
`parameter_revision_id`; cross-revision comparison is labelled and never silently mixed.

**symbol scope:** comparison is per `symbol` (or explicitly per symbol set); never global-only.

**period:** explicit `[from, to)` window; missing bounds are `UNKNOWN`/`NOT_APPLICABLE`, never "all".

**Missing evidence behavior:** if either side lacks a field, the comparison reports the availability
state for that side (e.g. `LIVE:NOT_CAPTURED`) and excludes it from numeric gap computation rather
than substituting zero.

**Reality-gap targets:** Decision parity, MM parity, Governance parity, Sizing parity, Entry price
gap, Exit price gap, Slippage, Fee, Latency, Fill behavior, PnL gap. Baseline configuration and
configured/effective/runtime values must come from the canonical `f553439` configuration authority
(`persist-baseline`, `unitProvenance`, `riskPercentSource`), never from frontend state.

---

## I. Persistence Contract

I.1 **Store roles (single source, no duplication).**
- **Stage 13** — canonical completed-trade record (trades, performance inputs, LIVE fill evidence).
- **Trading trace** — canonical stage/decision observation log; writer is canonical, reader must
  become restart-safe.
- **Supervisor SQLite** — canonical supervisor events + conversation turns.
- **MM persistence** — canonical MM state/timeline/monitoring.
- **Parameter Revision Archive** — canonical immutable parameter revisions.
- **Configuration authority (`f553439`)** — canonical baseline/configured/effective persistence.
- **Knowledge Candidate store** — the single knowledge-evolution authority (see reconciliation plan;
  not to be duplicated by WORK I).
- **projection** — read-only, bounded, allowlisted views (Advisor/Supervisor). Projections are
  derived, rebuildable, and never a second source of truth.

I.2 **append / update policy.** Trade, trace, supervisor-event and MM-timeline stores are append-only.
Configuration/revision stores are immutable-append or versioned. No in-place destructive update of
canonical evidence. Projections may be recomputed.

I.3 **idempotency.** Deterministic IDs + append-once semantics for events; repeated persistence of an
identical logical record is a no-op. Conflicting content for the same deterministic ID fails closed
(does not overwrite).

I.4 **restart recovery.** On restart, readers load from durable stores (never require an in-memory
warm-up). A store that cannot be reloaded (e.g. current trace reader) is non-compliant and must be
fixed before being treated as canonical evidence.

I.5 **corruption handling.** Fail closed: a corrupt/short read is surfaced as an explicit integrity
failure (availability `CAPTURE_FAILED` with reason), never silently repaired or truncated.

I.6 **retention / archive.** Bounded stores declare retention; append-only stores may archive by
segment, but archived evidence remains queryable by id. **`localStorage` is not a persistence store
for authority** — the dashboard Trade Settings `localStorage` revision (`f553439`) is presentation
persistence only.

I.7 **33.6 GB trace handling.** The trace file must not be fully memory-loaded. The canonical reader
must support bounded, indexed, restart-safe access (e.g. offset/tail index or a compact derived
projection) without creating a second authoritative trade history.

I.8 **No new duplicate Trade Store or Revision Store.** This contract forbids creating a second
trade-history store, a second performance store, or a second parameter/revision store. Extensions are
additive and versioned on the existing stores.

---

## J. Retrieval Contract

Read-only, GET-only retrieval surface. Each retrieval is bounded, redacted, and returns explicit
availability. Authentication is **separated by principal**: operator session vs a dedicated read-only
Bearer token (the pattern already used by the Advisor: `AI_ADVISOR_AUTH_TOKEN`,
`backend/ai_advisor/api_security.py:79`). The read-only principal can perform GETs only; it can never
reach POST/PUT/PATCH/DELETE, governance, MM, execution, bot, or arm endpoints.

| Retrieval | Purpose | Binds to (existing) | Authority |
|---|---|---|---|
| `get_trade_history` | Completed trades by symbol/mode/period/revision. | `trade_history_read.py` / `GET /api/trade-history` | OBSERVATION_READ_ONLY |
| `get_cycle_evidence` | One cycle's joined evidence envelope set (Stages 0–14). | new envelope view over Stage 13 + trace + MM + revision | OBSERVATION_READ_ONLY |
| `get_parameter_history` | Immutable parameter revisions. | `revision_archive.py` | OBSERVATION_READ_ONLY |
| `get_configuration_revision` | Configured/effective + provenance (`unitProvenance`, risk authority). | settings store + `f553439` | OBSERVATION_READ_ONLY |
| `get_performance_summary` | Derived metrics by revision/scope. | `compute_metrics` | OBSERVATION_READ_ONLY |
| `get_paper_live_comparison` | Reality-gap projection with comparison key. | new derived projection over Stage 13 | OBSERVATION_READ_ONLY |
| `get_current_authority` | Current configured/effective/runtime authority values and sources. | bot status + `f553439` risk authority | OBSERVATION_READ_ONLY |
| `get_advisor_history` | Advisor conversation/recommendation history. | conversation store (if accepted) | CONTEXT_ONLY |
| `get_supervisor_events` | Supervisor event history/replay. | `audit_store.py` / history router | OBSERVATION_READ_ONLY |

Boundaries:
- The read principal is distinct from the operator/write session; scopes are least-privilege.
- All responses are redacted; trace/payload metadata is filtered through the existing scrubbing.
- The retrieval surface never exposes a write path and never triggers execution.
- Advisor/Supervisor use only these read models; neither writes to the runtime.

---

## K. Knowledge Candidate Lifecycle

Canonical knowledge-candidate states:

`CANDIDATE` → `VERIFIED` | `HISTORICAL` | `UNKNOWN` | `SUPERSEDED` | `REJECTED`

Rules:
- Raw ChatGPT conversations, review reports and other free-text sources may only enter as
  `CANDIDATE`.
- **No automatic promotion** of raw ChatGPT conversation to `VERIFIED`. Promotion to `VERIFIED`
  requires explicit human review (`HUMAN_REVIEW_REQUIRED`) bound to the exact content fingerprint;
  changed content invalidates a stale approval.
- `HISTORICAL` = plausible historical evidence, not current authority and not validated knowledge.
- `SUPERSEDED` = replaced by a newer canonical/revisioned source; retained for provenance.
- `REJECTED` = examined and not accepted.
- Truth levels never invert; a candidate repeated many times is still not automatically canonical or
  valid.
- The knowledge candidate store is a single authority; Advisor/Supervisor receive bounded,
  labelled, read-only projections only.

---

## L. REAL #001 P0 Gate

`WORK_AA_REAL_E2E_001` is the first REAL trade. P0 evidence is the set that cannot be reconstructed
after the fact. WORK I defines the contract; it **does not hold REAL execution authority** and can
never start, arm, or place a trade.

### L.1 P0 evaluation (before/at REAL #001)

| Evidence | P0 class | Rationale |
|---|---|---|
| cycle/trade correlation (`cycle_id`,`trade_id`,`correlation_id`) | MUST_BE_IMPLEMENTED_BEFORE_REAL_001 | cannot be reconstructed |
| configuration/parameter revision (configured/effective + archive) | MUST_BE_IMPLEMENTED_BEFORE_REAL_001 (baseline authority exists via `f553439`) | revision snapshot must bind to cycle |
| AUTO candidate / selection reason | MUST_BE_IMPLEMENTED_BEFORE_REAL_001 | selection is transient |
| decision reason / rejection reason | MUST_BE_IMPLEMENTED_BEFORE_REAL_001 | transient reasoning |
| MM decision (`risk_percent` + source, qty, leverage) | MUST_BE_IMPLEMENTED_BEFORE_REAL_001 | decision is transient; authority now canonical (`f553439`) |
| Governance decision / permission / block reason | MUST_BE_IMPLEMENTED_BEFORE_REAL_001 | currently in-memory only |
| intended/normalized order | MUST_BE_IMPLEMENTED_BEFORE_REAL_001 | transient |
| exchange request / ACK | MUST_BE_IMPLEMENTED_BEFORE_REAL_001 | exchange-side proof |
| fill / partial / reject | MUST_BE_IMPLEMENTED_BEFORE_REAL_001 | exchange-side proof |
| fee / slippage / latency | MUST_BE_IMPLEMENTED_BEFORE_REAL_001 | not recoverable later |
| reconciliation | MUST_BE_IMPLEMENTED_BEFORE_REAL_001 | LIVE correctness proof |
| final FLAT | MUST_BE_IMPLEMENTED_BEFORE_REAL_001 | safety-critical end state |
| task_id / commit SHA / acceptance provenance | MUST_BE_IMPLEMENTED_BEFORE_REAL_001 | build provenance |
| restart-safe trace reader | MUST_BE_IMPLEMENTED_BEFORE_REAL_001 | required to retrieve the above after restart |
| per-symbol/per-period aggregation refinements | CAN_BE_DERIVED_AFTER_REAL_001 | derivable from stored raw evidence |
| PAPER↔LIVE comparison projection | CAN_BE_DERIVED_AFTER_REAL_001 | derivable once both sides are stored |
| knowledge import/normalization | CAN_BE_DERIVED_AFTER_REAL_001 | historical, not trade-critical |
| dashboards / UI surfaces for the above | OPTIONAL_FOR_REAL_001 | presentation only |
| long-term archive tiering of the 33.6 GB trace | OPTIONAL_FOR_REAL_001 | operational optimization |
| any change to MM / Governance / Execution **decisioning** authority | PROHIBITED_FROM_BLOCKING_EXECUTION_AUTHORITY | WORK I is observation-only; must never gate or alter execution |

### L.2 Boundaries
- WORK I has **no** REAL execution authority: no START/STOP, no LIVE ARM, no order, no parameter or
  Trade Settings change, no MM/Governance/Execution authority change.
- P0 work is **capture and retrieval only**; it must not introduce a new decisioning authority and
  must not block or alter the existing execution path.
- Where a P0 item is currently `NOT_CAPTURED`, the implementation records an explicit availability
  state rather than inventing data.

---

## M. Delta Integration — commit `f553439` (WORK AA pre-real configuration authority)

The delta from `f619279` → `f553439` ("fix(work-aa): harden pre-real configuration authority") is
additive to configuration authority and is adopted by this contract as a canonical source:

- **Baseline Configuration persistence**: `POST /api/parameter-settings/persist-baseline`
  (`backend/api/parameter_settings.py`) + `ParameterSettingsService.persist_baseline_if_missing`
  (`backend/strategy/parameters/settings_service.py`) persist the exact named baseline when the store
  is `MISSING`, idempotently, without inventing values; LIVE requires `confirmLive=true`; a safe
  stopped promotion makes EFFECTIVE match CONFIGURED. This becomes a canonical producer for Stage 0
  Parameter Context evidence (availability `VALUE_PRESENT` once persisted).
- **Unit provenance**: `backend/strategy/parameters/spread_unit_classification.py` +
  `unitProvenance` in the configuration response. LIVE spread percent interpretation is explicitly
  blocked (`LEGACY_UNIT_REPRESENTATION`, absolute price `MAX_SPREAD=0.0005`); PAPER is
  `PAPER_PERCENT_0_100`. Consumers must read this provenance; PAPER `0.50` must never be copied to
  LIVE.
- **Risk-percent authority**: `backend/money_management/risk_percent_authority.py` makes MM
  `risk_per_trade_pct` the single authority (`resolve_risk_percent_authority`), used by START/AMS
  executability (`resolve_executability_risk_percent`) and STOPPED/RUNNING status display
  (`status_risk_percent_authority`, exposed as `riskPercentSource` / `riskPercentAuthority`).
  It never invents `0.5`/`1.0`. This is the canonical Stage 6 MM decision source.
- **Frontend dashboard Trade Settings**: `localStorage` durable saved revision
  (`frontend/src/state/dashboard-market/DashboardMarketContext.jsx`) is **presentation-only** and
  explicitly **not** canonical authority under § A.4 / § I.6. Server-side revision remains the
  authority.

WORK I references these as canonical sources and re-implements none of them.

---

## N. Non-Goals / Out of Scope

- Creating any new trade history, performance, revision, or knowledge store.
- Any application-code, test, migration, runtime, service, bot, LIVE, or order change.
- Redefining MM/Governance/Execution decisioning authority.
- Importing raw conversations as verified knowledge.

## O. Next Minimal Implementation Task

See `docs/work_i/WORK_I_FEATURE_AI_KNOWLEDGE_RECONCILIATION_PLAN.md` § Next Task. In summary the next
minimal task is **P0-1: restart-safe, bounded trace retrieval** plus the **canonical cycle-evidence
envelope writer** over existing stores (no new store), after a separate implementation approval.
