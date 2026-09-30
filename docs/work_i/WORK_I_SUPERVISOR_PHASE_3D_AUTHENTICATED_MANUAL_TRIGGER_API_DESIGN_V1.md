# Work I③ Phase 3D — Authenticated manual one-shot trigger API design V1

Task: `TRADINGAI-WORK-I-03-PHASE-3D-AUTHENTICATED-MANUAL-TRIGGER-API-DESIGN-AUDIT-1`
Workstream: 作業I③
Status: **design and audit only**. No endpoint, no application/test code change, no runner
invocation, no scheduler activation, no persistence write, no notification, no commit.
Audited commit: `71eb5aabfe4fdcb27697a56b03a1633cd35fb1d9` (Phase 3C read API).
Branch: `feature/work-i-next`
Worktree: `/home/joe4410joe/tradingai_prod_v1.worktrees/work-i-integration`

This document designs a future endpoint that may explicitly invoke the existing Phase 3B
`ManualMonitoringRunner`. It is a contract, not an implementation. Every current-behavior
statement is a source finding at the audited commit; every proposed behavior is explicit
future design. A design finding that a prerequisite authority is missing is recorded as a
gate, not silently worked around.

---

## 1. Scope, safety gate and evidence standard

### 1.1 Safety gate result

| Check | Expected | Observed | Verdict |
|---|---|---|---|
| pwd == WORKTREE | WORKTREE | `/home/joe4410joe/tradingai_prod_v1.worktrees/work-i-integration` | PASS |
| branch | `feature/work-i-next` | `feature/work-i-next` | PASS |
| HEAD | `71eb5aa` | `71eb5aabfe4fdcb27697a56b03a1633cd35fb1d9` | PASS |
| HEAD parent | `956cda2` | `956cda2ea2191bbb09c69d687098986e480f7224` | PASS |
| HEAD is non-merge | single parent | one parent (`956cda2`) | PASS |
| `git status --short` | empty | empty | PASS |
| commit `71eb5aa` contains exactly the Phase 3C files | 5 files | 5 Phase 3C files | PASS |
| Phase 3C endpoints remain GET-only | GET only | `@router.get("/monitoring/health")`, `@router.get("/monitoring/state")` | PASS |
| local `main` | read-only | `8bff781015159b9bb6a31a7cf3f7507cc80792f6` | PASS |
| `origin/main` | read-only | `8bff781015159b9bb6a31a7cf3f7507cc80792f6` | PASS |

No fetch, pull, reset, merge, rebase, cherry-pick, stash or push was performed. No new worktree,
no branch switch. The only allowed writes are this tracked design document and the ignored
report under `tmp/chatgpt_reviews/`. No application or test file is modified; no route is added.

### 1.2 Prohibitions observed in this task

No application code change, no test change, no API route, no `ManualMonitoringRunner` invocation,
no monitoring execution, no anomaly-state write, no scheduler, no background task, no thread/timer,
no notification, no Production/runtime/database write, no service restart, no deploy, no Bot
operation, no ARM, no Governance execution, no order, no merge/cherry-pick/rebase/push, no commit.

---

## 2. Current-state authority audit

All paths are repository-relative. Line numbers identify source at the audited commit and are
provided for navigation, not as a durable contract.

### 2.1 Authentication authority

| Concern | Source evidence | Finding |
|---|---|---|
| Session middleware | `backend/auth/session_middleware.py:10` `OperatorSessionMiddleware` reads the `tradingai_session` cookie, verifies the HMAC signature via `OperatorSessionManager.unsign`, validates the session (expiry, sliding renewal) and attaches `scope["operator_session"]`. It never denies by itself. | A single reusable session authority exists. |
| Enforcement dependency | `backend/auth/dependencies.py:27` `require_operator_session(request)` returns the verified identity or raises `HTTPException(401, {"status":"UNAUTHENTICATED"})`. It trusts only the middleware-injected scope, never a raw cookie, IP, origin or header (`operator_session_identity`, `:12`). | Fail-closed, reusable, does not reimplement crypto. |
| Installation | `backend/main.py:654-675` installs `OperatorSessionMiddleware` only when `TRADINGAI_OPERATOR_CREDENTIAL_HASH` and `TRADINGAI_SESSION_SECRET` are present and valid (`_auth_configured`). Otherwise the middleware is absent. | If auth is not configured, `scope["operator_session"]` is never set and `require_operator_session` returns 401. Authentication is fail-closed even when unconfigured. |
| Identity | `backend/auth/api.py:165` `operator_identity = "operator"` is the only identity ever created. | Identity is a constant; no per-user model. |
| Comparable mutation routes | `require_operator_session` is used by `backend/api/bot_api.py`, `governance.py`, `money_management.py`, `parameter_settings.py`, `backend/api/runtime.py`, `backend/routers/mode.py`. | This is the canonical mutation-route authentication authority. |

**AUTHENTICATION_AUTHORITY = RESOLVED.** The future trigger endpoint must depend on
`require_operator_session` (or a thin wrapper that calls it) and must not reimplement session
verification.

### 2.2 Authorization authority

| Concern | Source evidence | Finding |
|---|---|---|
| Roles/capabilities | Repository search found no role, scope or capability model for the operator session. `OperatorSessionManager` stores only `identity`; `create_session` is called with the constant `"operator"`. | There is **no** authorization authority distinct from authentication. |
| Route-level checks | Mutation routes only assert `_operator: str = Depends(require_operator_session)`. No endpoint distinguishes privileges. | Authentication is currently treated as sufficient for every mutating route. |
| Distinction required | A monitoring trigger executes evaluation and (optionally) writes anomaly state; a read-only monitoring projection is less privileged. | The design must not assume `require_operator_session` alone authorizes triggering. |

**AUTHORIZATION_AUTHORITY = UNRESOLVED. IMPLEMENTATION_GATE = BLOCKED.** No proven capability
authority exists to authorize a monitoring trigger or to separate read-only monitoring from
state-persisting monitoring. Authentication alone is **not** accepted as authorization. A future
capability/role authority (e.g. `require_operator_capability("supervisor.monitoring.trigger")`)
must be added and approved before the trigger endpoint may be implemented. Until then the design
below specifies the required contract but marks it unsatisfied.

### 2.3 CSRF authority

| Concern | Source evidence | Finding |
|---|---|---|
| Middleware | `backend/auth/csrf.py:15` `OperatorCsrfProtection` is a double-submit cookie check: cookie `tradingai_csrf` (`:5`) must equal header `X-TradingAI-CSRF` (`:6`) via `secrets.compare_digest` (`:71`); safe methods pass (`:7`). | Reusable. |
| Allowlist | `backend/main.py:677-710` `_csrf_protected` enumerates protected mutation paths; middleware installed `:711-714`. A non-safe path **not** in the allowlist is not checked (`csrf.py:32-38`). | The trigger path must be added to `_csrf_protected`. |
| Installation coupling | The CSRF middleware is installed only inside the same `if _auth_configured:` block (`main.py:660-714`). | If auth is unconfigured, CSRF is absent **and** auth is absent, so the route still fails closed at authentication. |
| Failure response | `csrf.py:73-86` returns `403 {"status":"UNAUTHENTICATED"}` with no detail. | Existing convention conflates CSRF denial with an unauthenticated status; the design preserves it rather than inventing a new shape. |
| Origin/Referer | No origin/referer enforcement exists anywhere (search found none). | Do not claim origin validation; CSRF is token-only. Do not weaken it. |
| Token trust | The CSRF token is not bound to the session; it is a double-submit cookie. | Accepted as the canonical authority; no strengthening here. |

**CSRF_AUTHORITY = RESOLVED.** Reuse `OperatorCsrfProtection` by adding
`/api/supervisor/monitoring/run-once` to `_csrf_protected`. CSRF validation must complete
before any runner construction or invocation.

### 2.4 Rate-limit and concurrency authorities

| Concern | Source evidence | Finding |
|---|---|---|
| Rate limiter | `backend/ai_advisor/api_rate_limit.py:9` `AdvisorRateLimiter` (in-process sliding window, `allow(principal_id)`); used by login (`backend/auth/api.py:80`) and the Advisor. | Reusable primitive, process-local only. |
| Concurrency limiter | `api_rate_limit.py:49` `AdvisorConcurrencyLimiter` uses an `asyncio.Semaphore`; not usable for a synchronous blocking run. | Not directly applicable to the synchronous trigger. |
| Login precedent | `backend/auth/api.py:148-153` returns `429` with `Retry-After`. | Reuse the status/header convention for trigger rate limiting. |

### 2.5 Idempotency authority

| Concern | Source evidence | Finding |
|---|---|---|
| Generic API idempotency | No API-level idempotency ledger exists. `backend/bot_manager/bot_manager.py:228` mentions a per-request idempotency ledger for manual PAPER trades only (`self.manual_trade_requests`), scoped to order dispatch. | No reusable general idempotency authority. |
| Phase 2 event idempotency | `backend/supervisor/monitoring_state_store.py:206-250` `append` is idempotent per deterministic `event_id`/content digest (`DUPLICATE`/`CONFLICT`). | This dedups **state events**, not HTTP requests, and does not prevent a second observation run. |
| Runner request identity | `backend/supervisor/manual_monitoring_runner.py:193-195` derives `run_id = sha256(request_id:requested_at)[:32]`. | Request identity exists but is not a durable HTTP idempotency authority. |

**IDEMPOTENCY_CONTRACT = YES (designed below), but restart-safe HTTP idempotency requires new
persistence, which is a separate implementation decision.** In-process idempotency alone is not
restart-safe and is not Production-acceptable.

### 2.6 Audit-store authority

| Concern | Source evidence | Finding |
|---|---|---|
| Store | `backend/supervisor/audit_store.py:16` `SupervisorAuditStore`: append-only SQLite `logs/runtime/supervisor_audit.sqlite3`, unique `event_id`, `BEGIN IMMEDIATE`, process `RLock`, 5000-event cap (`:8`), bounded list page 100 (`:9`), secret-marker redaction (`:11-14`). | A bounded, sanitized, append-safe audit authority exists. |
| Event contract | `backend/supervisor/history_contracts.py:10-21` `SupervisorEventType` has no monitoring-run vocabulary; `history_contracts.py:27` `SupervisorHistoryEvent` fixes `agentId` to `MASTER_SUPERVISOR|MM_SUPERVISOR` (`backend/supervisor/contracts.py:17`), `mode=SHADOW`, `operationalEffect="NONE"` (`:41`). | Reuse is possible but requires an **additive** monitoring event type/agent mapping under separate approval; no monitoring-specific contract exists today. |
| Failure surface | `backend/supervisor/failure_codes.py:6` `SupervisorFailureCode` includes `STORE_UNAVAILABLE`, `STORE_FULL`, `DUPLICATE_EVENT`, `EVENT_INVALID`. | Stable codes available. |

**AUDIT_AUTHORITY = RESOLVED** (the store is the reuse target); the event contract extension is an
additive, separately approved change, not part of this task.

### 2.7 Phase 3B runner contract (invocation target)

| Concern | Source evidence | Finding |
|---|---|---|
| Dormancy | `manual_monitoring_runner.py:1-22` — import/construction performs no run, query, evaluation, persistence or I/O. | Safe to import; must only be invoked explicitly. |
| Request model | `MonitoringRunRequest` (`:121-149`): `request_id`, `requested_at`, `caller`, `correlation_id`, `scope`, `symbols` (≤32), `modes` (≤4), `max_observations` (1..800), `dry_run`, `persist`, `expected_flag_enabled`, `policy_version`; `persist` requires `dry_run=False`. | The API DTO must be a narrower, server-authoritative projection of this. |
| Feature flag gate | `:305-317` invalid flag → `DISABLED` (`FLAG_INVALID`); disabled → `DISABLED` (`DISABLED_RESULT`). | The runner already fails closed on the monitoring flag. |
| In-process overlap | `:233-234` `_active_run_id`/`_active_request_id`; `:338-349` `decide_overlap`; `:351-359` set/clear in `try/finally`. There is **no mutex**; control relies on synchronous, non-interleaved invocation. | A process-local lock must be added at the API boundary; see §11. |
| Persistence | `:480-500` writes only for events when `request.persist` and a `MonitoringStateService` is injected; returns `NOT_ATTEMPTED/PERSISTED/IDEMPOTENT/PARTIAL/REJECTED/FAILED`. | Persistence is explicit and reported, never hidden. |
| Failure isolation | `:369-478` query/evaluation/transition failures become bounded `UNAVAILABLE/FAILED` results with `partial_result`; no invented state. | Good; API maps these to bounded responses. |
| No deadline enforcement | `run_timeout_seconds` is copied into `MonitoringRun` (`:531`) but **never enforced**; there is no wall-clock deadline or cancellation. | Resource-limit gap; see §17. An outer bounded executor/deadline is required and is a prerequisite. |

### 2.8 Phase 3C read API (must remain unaffected)

`backend/api/supervisor_monitoring.py:52-58` exposes only
`GET /api/supervisor/monitoring/health` and `GET /api/supervisor/monitoring/state`, wired
additively in `backend/api/supervisor.py:84-85`. `backend/supervisor/monitoring_read_service.py`
is read-only and never runs monitoring. These routes and the Supervisor snapshot contract
(`backend/api/supervisor.py:71`, `backend/supervisor/contracts.py:312`) are frozen for this work.

### 2.9 Production composition and lifecycle

`backend/main.py:100` imports the module-level `supervisor_router`;
`backend/main.py:803` `app.include_router(supervisor_router)`. There is no monitoring scheduler,
no supervisor timer, no monitoring lifecycle in `startup_event`/`shutdown_event`. The Phase 3C
router is constructed with a dependency-free `MonitoringReadService()` (`backend/api/supervisor.py:85`).

---

## 3. Resolved vs unresolved authorities (gate summary)

| Authority | Classification | Consequence |
|---|---|---|
| Authentication | RESOLVED (`require_operator_session`) | Reuse directly. |
| Authorization / capability | **UNRESOLVED** | **IMPLEMENTATION_GATE = BLOCKED.** Add and approve a capability authority before implementing the trigger. |
| CSRF | RESOLVED (`OperatorCsrfProtection` + allowlist) | Reuse; add the trigger path to `_csrf_protected`. |
| Rate limit | RESOLVED primitive (`AdvisorRateLimiter`) | Reuse for per-principal throttling. |
| Idempotency | NOT PRESENT; new bounded persistence required | Restart-safe idempotency is a separate implementation decision. |
| Audit | RESOLVED store (`SupervisorAuditStore`); additive event type required | Reuse with an additive, separately approved event mapping. |
| Cross-process ownership | NOT PRESENT | Production activation remains BLOCKED. |
| Bounded execution deadline | NOT PRESENT in the runner | Add an outer deadline or keep activation blocked. |

**Preserved implementation gates (explicitly retained; never weakened to obtain PASS):**

- `AUTHORIZATION_AUTHORITY = UNRESOLVED`
- `IMPLEMENTATION_GATE = BLOCKED`
- `CROSS_PROCESS_SAFETY = NOT_GUARANTEED`
- `PRODUCTION_ACTIVATION_ALLOWED = NO`
- `DEFAULT_ENABLED = NO`

---

## 4. Proposed endpoint

**Route:** `POST /api/supervisor/monitoring/run-once`

Rationale for the final shape, following repository convention:

- Sub-router `backend/api/supervisor_monitoring.py` already owns the `/api/supervisor/monitoring`
  namespace; the mutation route is added there (or in a sibling `supervisor_monitoring_trigger.py`)
  and mounted by `create_supervisor_router`. No new top-level router.
- Mutating Supervisor routes do not exist today; the closest comparable control endpoints are
  the bot/governance/parameter routes, which use `require_operator_session` and CSRF.
- The route is **not** added to `_csrf_protected` by this task; that is a Phase 3D-3 change.

**Hard prohibitions for this endpoint:**

- No GET-triggered execution: only `POST`; GET on the path returns 405 (as Phase 3C does).
- No implicit execution at import time.
- No execution during application startup.
- No scheduler activation, no recurring timer/task/thread.
- No notification delivery.
- No Parameter/MM/Governance mutation.
- No trading execution, no ARM, no order placement.
- No arbitrary query/source/path parameters.

---

## 5. Authentication contract

- **Dependency:** `backend.auth.dependencies.require_operator_session`
  (or a wrapper that calls it; the wrapper must not weaken or reimplement it).
- **Absent/invalid/expired session:** `require_operator_session` raises `401`
  `{"status":"UNAUTHENTICATED"}` before the route body executes; the runner is never constructed
  for the request.
- **Authority unavailable:** when `_auth_configured` is false (`backend/main.py:655`), the session
  middleware is not installed, so no identity can ever be attached and every request is `401`.
  Fail-closed is guaranteed by construction.
- **Reuse safety:** the dependency reads only the middleware-validated scope; it does not trust
  cookies, headers, IP or origin. It is safe to reuse.
- **Do not reimplement:** signature verification, session storage, expiry/sliding renewal, or
  cookie parsing belong to `backend/auth/*`; the trigger route must not duplicate them.
- **Order:** authentication is evaluated before authorization, CSRF, request validation and any
  runner work (§18).

---

## 6. Authorization contract

- **Required capability (proposed):** an operator capability such as
  `supervisor.monitoring.trigger` for observation-only runs, and a distinct, stronger capability
  such as `supervisor.monitoring.persist` for `persistenceRequested=true`. The persistence-capable
  capability must never be implied by the observation capability alone.
- **Authenticated ≠ authorized:** passing `require_operator_session` proves identity, not the right
  to trigger monitoring or to write anomaly state.
- **Denial behavior:** `403` with a bounded body (e.g. `{"code":"SUPERVISOR_MONITORING_FORBIDDEN"}`)
  before CSRF/validation/runner work. No partial execution.
- **Existing authority:** none. Repository evidence shows a constant `"operator"` identity and no
  role/capability checks.
- **If no adequate authority exists:** **AUTHORIZATION_AUTHORITY = UNRESOLVED** and
  **IMPLEMENTATION_GATE = BLOCKED**. Phase 3D-1 must add a capability authority (or an explicitly
  approved, documented single-operator decision) before Phase 3D-3 wiring. Authentication alone is
  not accepted as authorization.

---

## 7. CSRF contract

- **Authority:** `backend.auth.csrf.OperatorCsrfProtection` (double-submit cookie).
- **Token source:** `tradingai_csrf` cookie issued at login (`backend/auth/api.py:169,183`).
- **Validation dependency:** the ASGI middleware, activated only for paths in
  `_csrf_protected` (`backend/main.py:677-714`).
- **Header/cookie contract:** header `X-TradingAI-CSRF` must equal cookie `tradingai_csrf`.
- **Failure response:** `403 {"status":"UNAUTHENTICATED"}` (existing shape, `csrf.py:73-86`).
- **Origin/Referer:** none enforced; do not introduce or rely on one.
- **Missing CSRF configuration:** the middleware is absent exactly when auth is unconfigured, in
  which case authentication already fails closed (401). A definitively missing/invalid CSRF token
  on a configured host is `403` before the route body.
- **Blocking point:** CSRF is validated before request validation, idempotency, ownership, overlap
  and runner construction/invocation.
- **Do not weaken policy:** the trigger path must be added to `_csrf_protected`; the middleware
  must not be bypassed, and no `GET` alias may be offered.

---

## 8. Feature-flag contract

Two independent gates, both default OFF, both must pass before runner invocation.

| Gate | Env name | Default | Purpose |
|---|---|---|---|
| Trigger API route | `AI_SUPERVISOR_MANUAL_TRIGGER_API_ENABLED` | OFF | Whether the mutation route is enabled at all. |
| Monitoring execution | `AI_SUPERVISOR_CONTINUOUS_MONITORING_ENABLED` | OFF | Whether monitoring may execute (the runner's injected `FeatureFlagStatus`). |

- **Parser:** reuse the canonical truthy vocabulary `{"1","true","yes","on"}` and fail-to-OFF on
  any non-truthy value (mirroring `backend/supervisor/monitoring_scheduler_models.py:21,193` and
  `supervisor_knowledge_history_enabled`). Malformed configuration → OFF (fail closed), recorded
  with a bounded reason (e.g. `FLAG_INVALID`).
- **API flag OFF:** the route returns a disabled result (see §16). Recommended: mount the route but
  return `503 SUPERVISOR_MONITORING_TRIGGER_DISABLED`; alternatively omit the route (404). The
  chosen convention must be identical across the phase plan.
- **Monitoring flag OFF:** even with the API flag ON, the runner returns `DISABLED` before any
  query/evaluation. Both gates must pass.
- **Neither flag** creates, starts or enables a scheduler, timer, thread, task or startup run.
- **Enabling the API flag alone must not execute monitoring.**
- **Dynamic enablement:** none; flags are read at composition/evaluation time. No endpoint toggles
  a flag. Environment files are not modified by the design or its tasks.

*Note:* this is deliberately stricter than design V1 §8.1, which allowed the manual path to run
with the scheduler flag OFF. Requiring both gates is the conservative, fail-closed choice.

---

## 9. Request contract

A bounded API DTO validated before the runner is touched. It must be narrower than
`MonitoringRunRequest`; server-authoritative fields are never client-supplied.

| Field | Type | Source | Bound |
|---|---|---|---|
| `requestId` | token | client | 1..128, `^[A-Za-z0-9][A-Za-z0-9_.:-]*$`; also the idempotency key |
| `scope` | enum `ALL/HEALTH/TRADING/SELECTION` | client | must be an allowed value |
| `symbols` | tuple[token] | client | ≤ 8 (hard cap below runner's 32); tokens only |
| `modes` | tuple[token] | client | ≤ 4; from a fixed allowlist |
| `maxObservations` | int | client | 1..min(config.max_observations, 128) |
| `persistenceRequested` | bool | client | default false; requires persist capability |
| `reason` | text | client | 0..256 chars, optional, no newlines |
| `expectedConfigVersion` | token \| null | client | must equal server `SchedulerConfig.config_version` if supplied |

Server-authoritative (client **must not** supply; server ignores/rejects):

- `requested_at` — server clock (client time is untrusted).
- `caller` — always `"OPERATOR"`.
- `run_id` — derived by the runner from the persisted idempotency record.
- `expected_flag_enabled` — set from the resolved monitoring flag.
- `policy_version` — server `EvaluationPolicy` identity.
- State-journal path, store, query/evaluator, `MonitoringStateService`, `SchedulerConfig`.

Rejected outright: arbitrary filesystem paths, arbitrary source names, unbounded limits/lists,
raw trace payloads, credentials/tokens, feature-flag mutation, scheduler commands, trading
commands. Unknown fields are rejected (`extra="forbid"`, mirroring existing contracts).

---

## 10. Idempotency contract

Phase 2 event idempotency does **not** provide API-request idempotency. A dedicated bounded ledger
is required for restart safety.

- **Key authority:** the client `requestId`, bounded and validated, scoped by operator identity
  and route.
- **Request fingerprint:** deterministic hash over the normalized DTO (excluding timestamps) plus
  the resolved server context (config version, policy version, monitoring flag state).
- **Retry behavior:** same key + same fingerprint → return the **stored response verbatim** (same
  `runId`, same body), do not re-invoke the runner. An explicit `idempotentReplay: true` marker is
  added to the response.
- **Duplicate behavior:** in-flight duplicate → `409 BUSY` (in-process) or replay of the completed
  record if finished.
- **Same key / different payload:** `409 SUPERVISOR_MONITORING_IDEMPOTENCY_CONFLICT`; never
  silently execute the new payload under the old key.
- **Retention window:** bounded (proposed 24 h or N=10,000 records, whichever is smaller),
  documented and enforced; eviction must not evict an in-flight key.
- **Restart behavior:** restart-safe replay is only possible with durable storage. This requires a
  **new persistence decision** (an additive monitored table per design V1 §7 `EXTEND_EXISTING`, or
  a dedicated bounded JSONL ledger). Without it, idempotency is process-lifetime only and is not
  Production-acceptable. State this explicitly.
- **Response replay policy:** only bounded, sanitized responses are stored (no raw evidence), and
  replay must re-emit the same idempotency result classification.
- **Relationship to Phase 2:** the idempotency ledger is separate from the anomaly-state journal;
  it never substitutes for Phase 2 event dedup and never writes anomaly state.
- **Relationship to runner `request_id`/`run_id`:** the API `requestId` becomes
  `MonitoringRunRequest.request_id`; the stored `run_id` is the runner-derived id, reused on
  replay.

---

## 11. Overlap and cross-process safety

Preserved constants:

- `IN_PROCESS_OVERLAP_CONTROL = AVAILABLE`
- `CROSS_PROCESS_SAFETY = NOT_GUARANTEED`
- `PRODUCTION_ACTIVATION_ALLOWED = NO`

### 11.1 Same-process concurrency

The runner's overlap control is an unguarded attribute (`manual_monitoring_runner.py:233-234,
338-359`). It is correct only when `run_once` is invoked non-interleaved. A synchronous FastAPI
`def` route runs in a thread pool, so two requests can race the `is_running` check. Therefore the
trigger service must wrap invocation in an explicit **process-local non-blocking lock**
(`threading.Lock` try-acquire / `threading.BoundedSemaphore(1)`) held for the whole run and
released in `finally`, in addition to the runner's own check. The lock object must be the single
shared guard for all trigger invocations in the process.

- Concurrent request while held → `409 SUPERVISOR_MONITORING_BUSY` (no queueing).
- The runner's internal check remains as defense in depth but is not relied upon alone.

### 11.2 HTTP result for BUSY

`409` with a bounded body `{"code":"SUPERVISOR_MONITORING_BUSY","retryable":true}`.

### 11.3 Process crash

A crash releases the OS-level resources; the in-process lock disappears with the process. Any
interrupted persistence is handled by the Phase 2 journal's `TRUNCATED_FINAL_RECORD` recovery and
`event_id` idempotency. An interrupted run must not be reported as success; the next authorized
run observes recovery status.

### 11.4 Multi-worker / multi-process risk

Two processes can both run observation and both attempt journal appends. The store's per-path
locks are process-local (`monitoring_state_store.py:34-45`), and `event_id` idempotency collapses
identical events but not divergent concurrent transitions. Cross-process exclusion is therefore
required before any Production activation.

### 11.5 Candidate ownership solutions

| Option | Mechanism | Trade-offs |
|---|---|---|
| 1. Verified single-process deployment | Startup self-check that refuses to start when a peer owner holds the lease; systemd `tradingbot.service` is single-process today | Weakest; only an assumption plus a self-check, no enforcement across hosts or manual launches |
| 2. OS advisory lock | `fcntl.flock(LOCK_EX\|LOCK_NB)` on a dedicated lock file held for the run/owner lifetime | Simple, host-scoped, crash-safe (kernel releases); does not coordinate across hosts |
| 3. DB lease with fencing token | Exclusive lease row + monotonic fencing generation; each append carries the fence | Strongest, cross-host; more complex, needs schema/retention/locking review and a new persistence authority |

**CROSS_PROCESS_RECOMMENDATION = OS_ADVISORY_EXCLUSIVE_LOCK**, adopted as the primary mechanism,
combined with option 1 as a startup assertion and option 3 reserved for a future cross-host
requirement. Rationale: the canonical deployment is a single host/process; an OS advisory
exclusive lock gives real mutual exclusion among cooperating processes on that host, is
crash-safe, and requires no new database authority. It must be held for the entire run (not just
until a request timeout) and acquired non-blocking so a concurrent trigger returns
`503 SUPERVISOR_MONITORING_OWNERSHIP_UNAVAILABLE` rather than queueing. None of these options is
implemented in this task.

---

## 12. Persistence permission

- **Explicit only:** persistence occurs only when the client sets `persistenceRequested=true`,
  the request passes the stronger persistence capability, and a `MonitoringStateService` is
  injected. Default is observation-only (`dry_run=true`, `persist=false`).
- **Single authority:** only the Phase 2 `MonitoringStateService`/`MonitoringStateStore` may
  write anomaly state. No new anomaly store, no duplicate corpus, no direct file writes.
- **Dry/read-only representable:** `dry_run` is the default; a dry run performs no append.
- **No invented state:** a failed observation/evaluation/transition produces `UNAVAILABLE`/`FAILED`
  and performs no persistence (`manual_monitoring_runner.py:369-416`).
- **Partial/corrupt explicit:** recovery partial/corruption and append `REJECTED`/`CONFLICT`
  surface as bounded `partial_result`, `corruption_count`, `persistence_status` and warnings.
- **Persistence failure returned, not hidden:** `persistence_status ∈
  {REJECTED, PARTIAL, FAILED}` and the corresponding bounded HTTP code (see §16).
- **Privilege separation:** persistence is more privileged than read-only monitoring. It requires
  the distinct capability from §6. Because authorization authority is unresolved, persistence
  remains blocked along with triggering.

---

## 13. Audit evidence

Reuse `SupervisorAuditStore` (append-only, bounded, sanitized, `operational_effect='NONE'`) with an
additive monitoring-trigger event mapping under separate approval.

**Recorded fields (bounded):**

- `requestId`
- privacy-safe actor reference (e.g. `sha256(operator_identity)` truncated; never the raw identity,
  never a cookie or session id)
- authorization result (`ALLOW`/`DENY`/`UNRESOLVED`)
- CSRF result (`PASS`/`FAIL`/`NOT_APPLICABLE`)
- feature-flag results (API flag, monitoring flag)
- request fingerprint (hash)
- `runId`
- start/finish timestamps (UTC)
- result classification (bounded enum mirroring the run status)
- persistence requested / applied
- error code (bounded, from `SupervisorFailureCode`/run codes)
- idempotency result (`NEW`/`REPLAYED`/`CONFLICT`)

**Never stored:** credentials, session cookies, CSRF token values, API keys, raw trace content,
unbounded payloads, internal stack traces.

**Reuse assessment:** the store is the correct authority, but `SupervisorHistoryEvent` cannot
express a monitoring-trigger event today (`SupervisorEventType`, agent/mode restrictions). Reuse
requires an additive event type and a privacy-safe actor field; that extension is a tracked change
for a future task, not this one. If the extension cannot be approved, implementation of audit is
blocked.

---

## 14. Synchronous vs asynchronous execution

Prefer **bounded synchronous one-shot execution**: the request holds until one bounded run
completes; the response carries the run result. There is no safe job authority in the repository
(no queue, no durable run registry, no ownership), so a hidden background job must not be designed.
Asynchronous/queued execution is out of scope until an owned, persistent job authority exists.

---

## 15. Response and HTTP contract

Bounded, sanitized, `extra="forbid"` response bodies. Suggested mapping:

| Outcome | HTTP | Bounded code / body |
|---|---|---|
| Accepted and completed (SUCCESS) | 200 | run summary |
| Completed with partial result | 200 | `partialResult=true` |
| Disabled (API flag OFF) | 503 | `SUPERVISOR_MONITORING_TRIGGER_DISABLED` (or 404 if unmounted) |
| Unauthenticated | 401 | `{"status":"UNAUTHENTICATED"}` |
| Unauthorized | 403 | `SUPERVISOR_MONITORING_FORBIDDEN` |
| CSRF rejected | 403 | `{"status":"UNAUTHENTICATED"}` (existing middleware shape) |
| Invalid request | 400 | `SUPERVISOR_MONITORING_REQUEST_INVALID` |
| Duplicate (idempotent replay) | 200 | stored response + `idempotentReplay=true` |
| Idempotency conflict | 409 | `SUPERVISOR_MONITORING_IDEMPOTENCY_CONFLICT` |
| In-process busy | 409 | `SUPERVISOR_MONITORING_BUSY` |
| Cross-process ownership unavailable | 503 | `SUPERVISOR_MONITORING_OWNERSHIP_UNAVAILABLE` |
| Observation unavailable | 503 | `SUPERVISOR_MONITORING_OBSERVATION_UNAVAILABLE` |
| Corruption detected | 200 | `corruptionCount>0` / `journalAvailability=CORRUPT` |
| Runner failure | 502 | `SUPERVISOR_MONITORING_RUN_FAILED` |
| Persistence failure (requested) | 500 | `SUPERVISOR_MONITORING_PERSISTENCE_FAILED` |
| Timeout / budget exhausted | 504 | `SUPERVISOR_MONITORING_TIMEOUT` |

Rules: no tracebacks, no filesystem paths, no raw evidence, no provider output, no secrets. The
response is a projection of the runner's bounded `ManualRunResult`, not the raw object.

---

## 16. Resource limits

| Limit | Bound |
|---|---|
| Request body size | ≤ 4096 bytes (mirror `backend/auth/api.py:123,129`) |
| Text field (`reason`) | ≤ 256 chars |
| Filter counts | symbols ≤ 8, modes ≤ 4 |
| Observation record count | ≤ min(config.max_observations, 128) |
| Observation byte count | ≤ config.max_scan_bytes, additionally capped by the API (proposed ≤ 1 MiB per request) |
| Execution deadline | `config.run_timeout_seconds` (1..60) **must be enforced by an outer bounded executor**; the runner does not enforce it (gap, §2.7) |
| Response size | < 64 KiB serialized |
| Warnings/errors count | ≤ 64 (runner already bounds) |
| Anomaly count returned | projected only; hard cap in the API projection |

Timeout/cancellation must not leave the runner locked: the runner resets its active id in
`finally`, and the API process-local lock must also be released in `finally`. Blocking I/O cannot be
force-cancelled (design V1 §6.5); a run that cannot be bounded must degrade to `DEGRADED`/`TIMEOUT`
and suppress new ownership until the worker is observed to exit.

---

## 17. Failure order (fail-closed)

Before any runner invocation:

1. **Route enabled** — API flag ON, else disabled response; no work.
2. **Authentication** — `require_operator_session`; 401 on failure.
3. **Authorization** — capability check; 403 on failure (currently UNRESOLVED → blocked).
4. **CSRF** — middleware allowlist; 403 on failure.
5. **Request validation** — bounded DTO, `extra="forbid"`; 400 on failure.
6. **Idempotency** — key lookup; replay or 409 conflict.
7. **Ownership / cross-process gate** — lease/advisory lock; 503 if unavailable.
8. **In-process overlap gate** — process-local lock; 409 BUSY if held.
9. **Bounded runner invocation** — one `run_once` with a server-authoritative request.
10. **Optional Phase 2 persistence** — only if requested and authorized; failures reported.
11. **Audit completion** — append sanitized record; audit failure never converts a deny into an
    allow.
12. **Response** — bounded, sanitized projection.

**Audit evidence for rejections:** post-authentication rejections (authorization, CSRF,
validation, idempotency, ownership, overlap, runner/persistence outcomes) produce a sanitized audit
record. Pre-authentication rejections (route disabled, unauthenticated) do **not** create a durable
per-request row — the actor is untrusted and unauthenticated durable writes are an abuse vector; a
bounded in-process counter/metric is recorded instead.

---

## 18. Existing GET API protection

The trigger endpoint must not:

- change Phase 3C GET behavior;
- cause any GET request to execute monitoring;
- make GET availability depend on trigger availability (the trigger route lives in the same
  sub-router but is independently gated);
- expose mutation controls through query parameters;
- alter the Supervisor snapshot (`GET /api/supervisor/snapshot`) or provider-status contracts.

Phase 3C GET routes remain exactly as committed in `71eb5aa`.

---

## 19. Implementation phase plan

- **Phase 3D-1 — pure contracts and adapters (no route, no execution).** Authentication wrapper
  over `require_operator_session`; capability authorization authority (or an explicitly approved
  single-operator decision); CSRF integration contract; bounded request/response models; bounded
  idempotency design and its persistence decision; audit event mapping. Default OFF. Tests only.
- **Phase 3D-2 — cross-process ownership authority.** OS advisory exclusive lock (primary), with a
  startup single-process assertion; recovery/fencing tests; no Production activation.
- **Phase 3D-3 — POST route wiring.** Mount `POST /api/supervisor/monitoring/run-once`; add the
  path to `_csrf_protected`; wire the injected `ManualMonitoringRunner`; audit evidence; temp/
  injected dependencies in tests; default OFF; no Production deployment.
- **Phase 3D-4 — isolated acceptance.** Authentication/authorization/CSRF/idempotency/overlap
  verification in an isolated environment; no notification, no scheduler, no Production.

Production activation remains a separate approval after cross-process safety and the execution
deadline are proven.

---

## 20. Validation checklist (this design task)

- [x] Safety gate verified; HEAD == `71eb5aa`, branch and worktree correct.
- [x] Required documents and modules inspected read-only.
- [x] Exactly one tracked design document created; no application/test file changed.
- [x] No route added; no runner invoked; no monitoring executed; no persistence written.
- [x] No commit; document left unstaged; report ignored.
- [x] Authentication/authorization/CSRF/idempotency/audit authorities classified.
- [x] Implementation blockers recorded (authorization, idempotency persistence, cross-process
      ownership, execution deadline).
- [x] Prohibitions observed.

**Design verdict: PASS for design/audit completion.** Implementation of the trigger endpoint is
**BLOCKED** until an authorization/capability authority exists, a restart-safe idempotency decision
is approved, cross-process ownership is implemented, and a bounded execution deadline is enforced.
Production activation remains blocked independently of this design.
