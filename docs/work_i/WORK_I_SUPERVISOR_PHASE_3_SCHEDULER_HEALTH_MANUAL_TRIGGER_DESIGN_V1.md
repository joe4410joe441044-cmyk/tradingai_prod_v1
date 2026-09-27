# Work I③ Phase 3 — Supervisor monitoring scheduler, health and manual trigger design V1

Task: `TRADINGAI-WORK-I-03-PHASE-3-SCHEDULER-HEALTH-MANUAL-TRIGGER-DESIGN-AUDIT-1`
Workstream: 作業I③
Status: documentation-only design and source audit. No implementation, no scheduler start,
no API route, no monitoring run, no state write, no notification, no commit.
Audited commit: `342962d1f3d7f856dff08eb32450226eb334d9e6`
Branch: `feature/work-i-next`
Worktree: `/home/joe4410joe/tradingai_prod_v1.worktrees/work-i-integration`

## 1. Scope and safety gate

### 1.1 Safety gate result

| Check | Expected | Observed | Verdict |
|---|---|---|---|
| Working directory | WORKTREE | `/home/joe4410joe/tradingai_prod_v1.worktrees/work-i-integration` | PASS |
| Branch | `feature/work-i-next` | `feature/work-i-next` | PASS |
| HEAD | `342962d1f3d7f856dff08eb32450226eb334d9e6` | `342962d` | PASS |
| `git status --short` | empty | empty | PASS |
| Phase 1 ancestry | ancestor of HEAD | `2955d3d` `feat(work-i): add deterministic supervisor monitoring models` | PASS |
| Phase 2 ancestry | equals HEAD | `342962d` `feat(work-i): add restart-safe supervisor anomaly state` | PASS |
| Local `main` | `ddf0c1a1...` read-only | `ddf0c1a1c12a11467fe03427a87550b022f7389f` | PASS |
| `origin/main` | `ddf0c1a1...` read-only | same | PASS |

No fetch, pull, merge, rebase, cherry-pick or checkout was performed. No application code,
test code, Production composition, service, database or runtime was read or written beyond
read-only source inspection. The only writes are this design document and the ignored review
report under `tmp/chatgpt_reviews/` (see §1.3).

### 1.2 Dynamic non-overlap gate

`main` and `origin/main` are identical (`ddf0c1a1`), and the only commits between the main
merge-base (`ec65b42`) and HEAD are the Work-I③ design/Phase 1/Phase 2 commits plus the prior
Work-I commits. There is no new Supervisor, Advisor, Shared Query or backend-lifecycle movement
on main that overlaps this workstream, therefore the non-overlap gate passes. The previous
frontend-only main separation documented in the V1 design remains accepted under the
frontend-only exception and is unchanged. No merge is required or performed.

### 1.3 Deliverables and prohibitions observed

- Deliverable 1 (tracked): this document.
- Deliverable 2 (ignored): `tmp/chatgpt_reviews/TRADINGAI-WORK-I-03-PHASE-3-SCHEDULER-HEALTH-MANUAL-TRIGGER-DESIGN-AUDIT-1.md`.
- No other tracked file was created or modified.
- Prohibited actions not performed: scheduler implementation/start, `asyncio` task/thread/timer,
  monitoring execution, API implementation, notification, Production composition change,
  application/test code change, persistence write, Production trace read/write, database/runtime
  write, service restart, deploy, Bot operation, ARM, Governance execution, order, merge,
  cherry-pick, rebase, push.

### 1.4 Evidence standard

Every current-behavior statement in §2 is a source finding at the audited commit, not a claim
about a deployed environment, environment variables, data volume or live traffic. All proposed
flags, files, budgets and states below are explicit future design. Missing evidence never proves
normal operation. Severity and every later phase remain observation-only: no Parameter/MM/
Governance change, START/STOP, ARM/DISARM, order, trading-decision modification or automatic
remediation.

---

## 2. Production lifecycle audit

Paths are relative to the repository root. Function names identify audited source independently
of changing line numbers.

### 2.1 Application entrypoint and process model

| Concern | Source evidence at HEAD | Consequence for Phase 3 |
|---|---|---|
| ASGI app | `backend/main.py:132` `app = FastAPI()` — created bare, no `lifespan=` argument. | No lifespan context exists today; a scheduler must attach through the existing event-handler style or a deliberate new lifespan, and must not assume lifespan support. |
| Startup hook | `backend/main.py:532-567` `@app.on_event("startup") async def startup_event()` wires MM application, MM cash-flow runtime, Bot manager providers, AMS paper auto-selection, MM HTTP boundary and execution-entry gate. | This handler is the only safe place to wire an optional monitor lifecycle today, and it is already a composition root with broad side effects. It must not be reused to start monitoring unless the new step is fully guarded and failure-isolated. |
| Shutdown hook | `backend/main.py:570-627` `@app.on_event("shutdown") async def shutdown_event()` unregisters MM boundaries, calls `bot_manager.shutdown()`, logs a sanitized snapshot and shuts down MM. | A Phase 3 shutdown must add its own bounded stop step without reordering or weakening Bot/MM shutdown. |
| Background tasks | `backend/main.py` contains no `asyncio.create_task`, no `threading`, no `Timer`, no scheduler import. | There is no existing supervisor-owned timer to attach to. Phase 3C must introduce its own owner. |
| Process model | `systemd/tradingbot.service:12` `ExecStart=.../python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001`, with `Restart=always` and `RestartSec=5` (`:13-14`). No `--workers`, no `--reload`. | The audited production contract is a **single uvicorn process**, loopback-bound. This is the identity the design may rely on for process-level uniqueness, but see §6.4: single-process is an assumption, not a runtime-enforced guarantee. |
| Other process config | No `Dockerfile`, no `Procfile`, no `gunicorn` config, no APScheduler config were found; only the two systemd units. | There is no alternate multi-worker entrypoint in the repo to reconcile today. |
| Auto-restart | systemd `Restart=always`, `RestartSec=5`. | A crash restarts the process; Phase 3 must be restart-safe and must not create a catch-up storm on repeated restart (§11). |

### 2.2 Supervisor construction and current runtime

| Concern | Source evidence | Phase 3 consequence |
|---|---|---|
| Router construction | `backend/api/supervisor.py:129-131` builds `create_supervisor_router(knowledge_history_consumer=SupervisorKnowledgeHistoryConsumer())` at **import time**. | Importing the API module constructs `SupervisorAuditStore()` (`:81`) and opens/creates SQLite. A monitoring worker must not import this router; a read model must depend on the pure contracts, not on router construction. |
| Provider selection | `backend/supervisor/provider_configuration.py` defaults `SUPERVISOR_PROVIDER` to `DISABLED`; explicit `OLLAMA_LOCAL`/`OPENAI` select adapters. | Scheduler must never call a provider. The LLM interpretation boundary stays separate from deterministic observation. |
| Snapshot evaluation | `backend/api/supervisor.py` `GET /api/supervisor/snapshot` builds a snapshot on demand via `RuntimeSnapshotAdapter.build`; `_read_bot/_read_governance/_read_money_management/_read_health` are lazy per call (`backend/supervisor/runtime_snapshot_adapter.py`). | Reads are sequential, not an atomic cross-authority snapshot. Phase 3 may reuse read contracts but must treat them as per-call observations. |
| Shadow evaluators | `evaluate_mm_shadow`/`evaluate_master_shadow` are invoked only from `backend/supervisor/conversation_service.py` request handling. No scheduled caller exists. | The Supervisor does **not** automatically evaluate today. Phase 3 introduces the first automatic evaluation, which is exactly why default-OFF and ownership fencing are mandatory. |
| Monitoring modules | `MonitoringStateStore`, `MonitoringStateService` and `one_shot_monitor` exist (Phase 1/2) but are **not constructed anywhere in `backend/`**; `one_shot_monitor` is a pure synchronous function. | Phase 3 is the first composition of these modules. All required budgets/flags/paths must be introduced by Phase 3, not inherited. |
| Capability metadata | `backend/runtime/knowledge_history_query.py:630-639` declares `AI_SUPERVISOR` consumer with `scheduler_registration: False` and `api_route: None`. | The shared-query contract currently asserts no scheduler registration and no route; Phase 3 must not silently contradict this without an explicit, separately approved change. |
| Integration guard tests | `tests/test_supervisor_monitoring_integration.py:159-210` assert no `create_task`, `Thread(`, `APScheduler`, no network/DB, no `logs/runtime`/`os.environ` in monitoring modules, no trading fields. | Phase 3A/3B pure modules must preserve these guards. Only Phase 3C may introduce a controlled owner, under new tests. |

### 2.3 Health, authorization, audit and configuration conventions

| Concern | Source evidence | Phase 3 consequence |
|---|---|---|
| Existing health route | `backend/main.py:515-526` `GET /health` returns `{"status":"ok","runtimeHealthy": ...}`. No `/ready` or `/readiness` route exists. | Monitoring health must be a separate read-only surface and must not change `/health` semantics. |
| Supervisor auth | Supervisor routes have no `Depends(require_operator_session)` and no CSRF entry. `OperatorSessionMiddleware` only populates `scope["operator_session"]` and never denies (`backend/auth/session_middleware.py`); enforcement is opt-in (`backend/auth/dependencies.py`). The CSRF allowlist `_csrf_protected` (`backend/main.py:677-710`) contains no `/api/supervisor/*` path. | A Phase 3 manual trigger is a **state-changing** action and therefore requires a stronger boundary than existing read-only Supervisor routes: session auth + CSRF, per §8. Read health routes may remain unauthenticated only if they expose no sensitive data, but the manual trigger may not. |
| Control-route precedent | Control routes that mutate state enforce `require_operator_session` and appear in `_csrf_protected` (e.g. `/api/bot/*`, `/api/governance/*`, `/api/money-management/*`, `/api/parameter-settings/*`). | The manual trigger design follows this existing precedent rather than the weaker existing Supervisor precedent. |
| Audit store | `backend/supervisor/audit_store.py` uses SQLite `logs/runtime/supervisor_audit.sqlite3`, bounded at 5,000 events and page limit 100, transaction + RLock. | This is conversation/assessment audit, **not** monitoring state. Phase 3 must not overload it; monitoring state authority is the Phase 2 JSONL journal. |
| Monitoring state store | `backend/supervisor/monitoring_state_store.py:73-83` requires an explicit `path`; there is no default and no env-derived path. Process-local `RLock` + per-path `RLock` registry (`:34-45`); append uses `O_CREAT|O_APPEND|O_WRONLY`, mode `0o600`, optional fsync. | Phase 3 must supply a validated journal path via new configuration; there is no existing production path to reuse. Process-local locks do **not** provide cross-process safety (§6.4). |
| State-path convention precedent | `CYCLE_EVIDENCE_PATH` → `logs/runtime/cycle_evidence.jsonl` (`backend/runtime/cycle_evidence_store.py:40-41`); `TRADING_E2E_TRACE_PATH` → `logs/runtime/trading_e2e_trace.jsonl`. | The monitoring journal path should follow this explicit-env-plus-documented-default convention, default OFF, but must remain an explicit constructor argument at the model boundary. |
| Recovery/integrity concepts | Phase 2 already models `RecoveryResult` (`partial`, `corruption_count`, `duplicate_events`, `corrupted`), `AppendOutcome` (`WRITTEN/DUPLICATE/CONFLICT/REJECTED`) and corruption reasons (`OVERSIZED_RECORD`, `TRUNCATED_FINAL_RECORD`, `INVALID_ENCODING`, `INVALID_JSON`, `NOT_AN_OBJECT`, `SCHEMA_VERSION_UNSUPPORTED`, `INVALID_RECORD`). | Phase 3 health must surface these existing concepts, not invent parallel integrity vocabulary. |
| Feature-flag convention | Env flags, default OFF, truthy in `{"1","true","yes","on"}` (some modules also accept `"enabled"`): `CYCLE_EVIDENCE_PHASE_A_ENABLED`, `AI_ADVISOR_KNOWLEDGE_HISTORY_ENABLED`, `AI_SUPERVISOR_KNOWLEDGE_HISTORY_ENABLED`, `KNOWLEDGE_HISTORY_QUERY_CONSUMERS_ENABLED`. | Phase 3 adds exactly one new scheduler flag following the same parser shape and fail-to-OFF rule (§3). |
| Test layout | `tests/test_supervisor_monitoring_models.py`, `_drift_evaluator.py`, `_one_shot_monitor.py`, `_monitoring_state.py`, `_monitoring_transitions.py`, `_monitoring_state_store.py`, `_monitoring_integration.py`; plus Supervisor API/auth/security tests. | Phase 3 tests extend this layout; no test infrastructure is missing. |

### 2.4 Audit determinations

1. **Exact safe scheduler owner.** The single safe composition point is the existing
   `@app.on_event("startup")`/`@app.on_event("shutdown")` pair in `backend/main.py`, because it is
   the only code that runs exactly once per process lifecycle. The owner must be a dedicated,
   default-OFF, failure-isolated component created there; it must not be the Supervisor router
   (import-time side effects) and must not reuse the Bot/MM loops.
2. **Multiple processes/workers.** The audited deployment is single-process uvicorn with no
   `--workers`. The design may **assume** a single worker for the canonical host, but source
   cannot prove no operator ever starts a second process or disables the systemd unit in favor of
   another runner.
3. **Duplicate schedulers.** Nothing in the current source prevents two processes from starting
   the same scheduler and appending to the same journal. A process-local lock cannot prevent
   this. Cross-process safety is therefore **not currently guaranteed** (§6).
4. **Shutdown cancellation.** There is no existing supervisor cancellation primitive. Phase 3
   must add a bounded stop step inside `shutdown_event` that requests cancellation and waits a
   bounded time; Python cancellation cannot terminate blocking I/O (§6.5).
5. **State path configuration.** No production monitoring-state path exists; Phase 3 must
   introduce and validate it. The store already rejects a `None`/`bool` path, so a missing or
   invalid configuration must fail the scheduler to OFF rather than raise through startup.
6. **State persistence before startup.** The journal is created lazily on first append; recovery
   is read-only and works whether or not the file exists (`RecoveryResult.exists`). Therefore
   persistence is available on demand but the scheduler must not create or write state merely to
   start.
7. **Automatic evaluation today.** No. The existing Supervisor evaluates only inside request
   handling.
8. **Manual one-shot sharing the lock.** There is no shared lock today because there is no
   runner. Phase 3 must make the manual path and the scheduled path share one non-overlap guard
   (§6.3), otherwise manual runs could interleave with scheduled runs and double-append.

---

## 3. Feature-flag contract

### 3.1 Dedicated scheduler flag

| Property | Design |
|---|---|
| Name | `AI_SUPERVISOR_CONTINUOUS_MONITORING_ENABLED` |
| Default | OFF (unset, empty or falsy) |
| Truthy set | `{"1","true","yes","on"}` (reuse the exact parser shape at `backend/supervisor/knowledge_history_consumer.py:57-68`); `"enabled"` is **not** accepted to keep one canonical vocabulary |
| Independence | Independent of `SUPERVISOR_PROVIDER*`, `AI_SUPERVISOR_KNOWLEDGE_HISTORY_ENABLED`, `AI_ADVISOR_KNOWLEDGE_HISTORY_ENABLED`, `CYCLE_EVIDENCE_PHASE_A_ENABLED`, `KNOWLEDGE_HISTORY_QUERY_CONSUMERS_ENABLED`, and Phase A evidence |
| OFF means | No task, no timer, no thread, no lease acquisition, no source query, no state-journal open/append, no health timer, no provider call, no API side effect beyond reading the flag for a read-only status |
| Invalid value | Fails to OFF; health reports reason code `FLAG_INVALID` and never starts |
| Startup report | Scheduler status reports `enabled` plus `feature_flag_source` (`ENV_NAME` / `DEFAULT_OFF` / `INVALID`) and, when disabled, `disabled_reason` |
| Trading authority | Enabling the flag grants **no** trading, governance, MM, ARM or order authority; every output remains observation-only |
| Dynamic enablement | None in Phase 3. The flag is read at composition/startup only. No endpoint may toggle it. |

### 3.2 Configuration values and bounds

All values are validated at composition time. Any out-of-range value fails the scheduler to OFF
with `CONFIG_INVALID` and a bounded reason; it must not raise through `startup_event` and must not
partially start. One documented default per field; all defaults are inert until the flag turns ON.

| Setting | Env key | Default | Valid range | Notes |
|---|---|---|---|---|
| Interval seconds | `AI_SUPERVISOR_MONITORING_INTERVAL_SECONDS` | 60 | 15..3600 | Scheduled period; no catch-up. |
| Startup delay seconds | `AI_SUPERVISOR_MONITORING_STARTUP_DELAY_SECONDS` | 30 | 0..600 | Delay after composition before first tick; gives Bot/MM time to settle. |
| Run timeout seconds | `AI_SUPERVISOR_MONITORING_RUN_TIMEOUT_SECONDS` | 10 | 1..60 | Whole-run budget. |
| Per-source timeout seconds | `AI_SUPERVISOR_MONITORING_SOURCE_TIMEOUT_SECONDS` | 2 | 0.1..10 | Must be < run timeout. |
| Cancellation wait seconds | `AI_SUPERVISOR_MONITORING_CANCEL_WAIT_SECONDS` | 5 | 0.5..30 | Bounded graceful drain. |
| Max shared pages per run | `AI_SUPERVISOR_MONITORING_MAX_PAGES` | 4 | 1..16 | All adapters combined. |
| Max items per page | `AI_SUPERVISOR_MONITORING_MAX_PAGE_ITEMS` | 200 | 1..200 | Matches Shared Query max (`knowledge_history_query` max 200). |
| Max total query items | `AI_SUPERVISOR_MONITORING_MAX_ITEMS` | 800 | 1..800 | 4 × 200. |
| Max scan bytes | `AI_SUPERVISOR_MONITORING_MAX_SCAN_BYTES` | 8 MiB | 64 KiB..64 MiB | Combined. |
| Max scan lines | `AI_SUPERVISOR_MONITORING_MAX_SCAN_LINES` | 50000 | 1..500000 | Combined physical lines. |
| Max record bytes | `AI_SUPERVISOR_MONITORING_MAX_RECORD_BYTES` | 256 KiB | 1 KiB..10 MiB | Must not exceed the store's own 10 MiB ceiling. |
| Max observations | `AI_SUPERVISOR_MONITORING_MAX_OBSERVATIONS` | 128 | 1..800 | Must not exceed `EvaluationPolicy.maximum_inputs` (≤800). |
| Max state events per run | `AI_SUPERVISOR_MONITORING_MAX_STATE_EVENTS` | 256 | 1..5000 | Bound on persisted events per run. |
| State journal path | `AI_SUPERVISOR_MONITORING_STATE_PATH` | `logs/runtime/supervisor_monitoring_state.jsonl` | absolute or repo-relative file path | Documented default only; the store constructor still receives an explicit `Path`. |
| Recovery max records | `AI_SUPERVISOR_MONITORING_RECOVERY_MAX_RECORDS` | 50000 | 1..500000 | Passed to store's `max_recovery_records`. |
| Recovery max bytes | `AI_SUPERVISOR_MONITORING_RECOVERY_MAX_BYTES` | 8 MiB | 1..256 MiB | Passed to store's `max_recovery_bytes`. |
| Lease/owner lock path | `AI_SUPERVISOR_MONITORING_LOCK_PATH` | `logs/runtime/supervisor_monitoring.lock` | file path | Only used by the future cross-process owner (see §6.4); inert until approved. |

Cross-field validation: `source_timeout < run_timeout`; `cancel_wait <= run_timeout`;
`max_items <= max_pages * max_page_items`; `max_record_bytes <= 10 MiB`;
`max_observations <= policy.maximum_inputs`; recovery bounds positive. Any violation = `CONFIG_INVALID`.
Interval, startup delay, source timeout and cancellation wait are whole/decimal seconds; the
config parser must reject non-numeric and negative values without raising.

---

## 4. Scheduler state machine

### 4.1 States

| State | Meaning |
|---|---|
| `DISABLED` | Flag OFF or config invalid. No resources, no timer, no query, no state. Terminal until restart. |
| `STARTING` | Enabled; acquiring ownership and validating config/store; no run yet. |
| `IDLE` | Owned and healthy, waiting for the next scheduled or manual trigger. |
| `RUNNING` | Exactly one bounded run in progress. |
| `DEGRADED` | Owned but health is impaired (source unavailable, store degraded, recovery partial, ownership uncertain). Scheduling may continue at reduced capability or be suspended per policy. |
| `STOPPING` | Cancellation requested; draining a run and releasing ownership. |
| `STOPPED` | Cleanly stopped; no active run; no new triggers accepted. |
| `FAILED` | Startup or repeated run failure escalated; no automatic retry storm; requires operator/restart. |

### 4.2 Transitions

| From | Event | To | Reason code |
|---|---|---|---|
| (init) | flag OFF | `DISABLED` | `FLAG_OFF` |
| (init) | flag invalid | `DISABLED` | `FLAG_INVALID` |
| (init) | config invalid | `DISABLED` | `CONFIG_INVALID` |
| `DISABLED` | — | (terminal) | `DISABLED_TERMINAL` |
| (enabled) | composition | `STARTING` | `START_REQUESTED` |
| `STARTING` | delay scheduled | `STARTING` | `STARTUP_DELAY_ACTIVE` |
| `STARTING` | ownership acquired, config/store valid | `IDLE` | `STARTED` |
| `STARTING` | ownership unavailable | `FAILED` | `OWNERSHIP_UNAVAILABLE` |
| `STARTING` | store invalid | `DEGRADED` | `STORE_DEGRADED_AT_START` |
| `IDLE` | scheduled tick / manual request | `RUNNING` | `RUN_STARTED_SCHEDULED` / `RUN_STARTED_MANUAL` |
| `IDLE`/`RUNNING` | run budget/health impairment | `DEGRADED` | `RUN_DEGRADED` |
| `DEGRADED` | healthy run | `IDLE` | `RECOVERED` |
| `RUNNING` | run complete | `IDLE` | `RUN_COMPLETED` |
| `RUNNING` | source/query budget exceeded | `DEGRADED` | `BUDGET_EXHAUSTED` |
| `RUNNING` | store append conflict/failure | `DEGRADED` | `PERSISTENCE_DEGRADED` |
| `RUNNING` | timeout | `DEGRADED` | `RUN_TIMEOUT` |
| `RUNNING`/`IDLE`/`STARTING` | shutdown requested | `STOPPING` | `STOP_REQUESTED` |
| `STOPPING` | drained | `STOPPED` | `STOPPED_CLEAN` |
| `STOPPING` | drain timeout | `STOPPED` | `STOPPED_FORCED` (records `cancellation_incomplete=true`) |
| `IDLE`/`DEGRADED` | repeated consecutive failures ≥ threshold | `FAILED` | `FAILURE_THRESHOLD` |
| `FAILED` | — | (terminal until restart) | `FAILED_TERMINAL` |

### 4.3 Guarantees

- **One active scheduler per process.** At most one owner object exists; construction is
  idempotent and a second construction attempt returns the existing owner or a conflict.
- **One monitoring run at a time.** A single run guard (process-local mutex plus, when approved,
  a lease) serialises scheduled and manual runs.
- **Skipped overlap is observable.** A tick that cannot acquire the guard increments
  `skipped_overlap_count` and records reason `SKIPPED_OVERLAP`; it does not queue.
- **No unbounded backlog.** At most one pending trigger; no tick queue; missed intervals collapse
  to a single next-run timestamp.
- **No retry storm.** Minimum backoff between consecutive failures, capped; no immediate retry.
- **Cancellation is bounded.** Run cancellation has an explicit deadline and a recorded
  `cancellation_incomplete` flag if the drain did not finish.
- **Exceptions do not terminate Bot runtime.** All scheduler failures are caught inside the owner
  boundary and converted to health/reason codes; they never propagate into `startup_event`/`shutdown_event`.
- **Scheduler failure does not affect trading.** The owner shares no transaction, lock or thread
  with Bot/MM/Governance/execution.
- **Never maps results to ALLOW/BLOCK.** State and health vocabularies contain no trading
  permission field and no control-plane mutation.
- **Shutdown does not corrupt the journal.** The store is append-only, idempotent by `event_id`,
  and writes whole lines with optional fsync; an interrupted final append is recoverable as
  `TRUNCATED_FINAL_RECORD` and never repaired in place.

---

## 5. Bounded run contract

One run is an explicit ordered sequence. Every step declares timeout, maximum items, failure
behavior, partial-result behavior, cancellation point, observable reason code, whether a write
occurs, and the required flag. No notifications are sent in Phase 3.

| # | Step | Timeout | Max items | Failure behavior | Partial result | Cancellation point | Reason code | Write? | Flag |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Acquire non-overlap guard | ≤ 0 s (try-acquire) | 1 | If busy: skip, no run | n/a | n/a | `SKIPPED_OVERLAP` | No | `AI_SUPERVISOR_CONTINUOUS_MONITORING_ENABLED` (manual path may run with flag OFF, §8) |
| 2 | Capture explicit evaluation timestamp | 0 s | 1 | Clock regression → `DEGRADED`, no run | n/a | yes | `CLOCK_REGRESSION` | No | same |
| 3 | Read bounded evidence/history (Shared Query) | per-source timeout | ≤ max_pages × max_page_items, total ≤ max_items; ≤ max_scan_bytes/lines | Source failure → source UNKNOWN/PARTIAL; other sources continue | `partial_result=true` if any scan/budget incomplete | yes (cooperative between pages) | `SOURCE_UNAVAILABLE`, `SOURCE_STALE`, `BUDGET_EXHAUSTED` | No | same |
| 4 | Build observations/baselines | ≤ run timeout remainder | ≤ max_observations; `one_shot_monitor` pre-validation budgets (≤16,000 nodes, ≤16 depth, ≤65,536 chars) | Invalid input isolated per key | `partial_result=true` if invalid_count>0 | yes | `MODEL_VALIDATION_FAILED`, `INVALID_INPUT` | No | same |
| 5 | Run Phase 1 one-shot evaluation | bounded by step 3–4 budgets | ≤ policy.maximum_inputs (≤800) | `one_shot_monitor` returns `MonitorResult` with `INVALID` results; never trades | `aggregate_status` may be `UNKNOWN`/`PARTIAL` | yes | `EMPTY_INPUT`, `INCOMPLETE_EVALUATION` | No | same |
| 6 | Recover Phase 2 state | ≤ run timeout remainder | ≤ recovery_max_records, ≤ recovery_max_bytes | Corrupt/partial recovery isolated | `partial=true`, `corrupted` populated | yes | `RECOVERY_PARTIAL`, `RECOVERY_CORRUPTION_ISOLATED`, `RECOVERY_BYTE_BUDGET`, `RECOVERY_RECORD_BUDGET` | No | same |
| 7 | Apply Phase 2 transitions/dedup/cooldown | CPU-only, bounded by observation count | ≤ max_observations | Pure function; validation errors isolated | warnings retained (`DEDUP_CONFLICT`) | no (short, pure) | `DUPLICATE`, `CONFLICT`, `SUPPRESSED`, `ESCALATED`, `RESOLVED` | No | same |
| 8 | Explicitly persist state events | bounded by store I/O | ≤ max_state_events | `AppendResult` `REJECTED`/`CONFLICT` → `DEGRADED`; never raises | events partially written; conflicts counted | yes (before each append) | `PERSISTENCE_CONFLICT`, `PERSISTENCE_REJECTED` | **Yes** (only step that writes) | same |
| 9 | Update scheduler health/read model | 0 s | in-memory fields only | Best-effort in-memory update | n/a | n/a | `HEALTH_UPDATED` | No (in-memory read model only) | same |
| 10 | Release guard | 0 s | 1 | Must release even on failure (finally) | n/a | n/a | `GUARD_RELEASED` | No | same |

Global run rules:

- Steps 1 and 10 always run even if an earlier step fails (try/finally), so the guard cannot leak.
- The run has a single deadline = `min(current_time + run_timeout, ...)`; steps 3–8 share it.
- A write only ever occurs at step 8, only for `StateEvent`s with `persistence_required`.
- No network, exchange, provider or notifier client may be invoked in any step.
- The run returns a bounded run result referencing IDs/reason codes, never raw evidence payloads.

---

## 6. Non-overlap design

### 6.1 Concurrency matrix

| Pair | Protection | Behavior |
|---|---|---|
| Scheduled run vs scheduled run | One owner's interval timer cannot fire a second run; guard try-acquire | Second tick skipped, `skipped_overlap_count++` |
| Scheduled run vs manual run | Same single run guard | Manual returns `BUSY` (HTTP 409-class) if scheduled run holds guard; no queue |
| Manual run vs manual run | Same single run guard | Second manual requests idempotent status of the in-flight run if same key; otherwise `BUSY` |
| Shutdown during run | `STOPPING` sets cancel event; run observes cooperative cancellation, drains within `cancel_wait` | `STOPPED_CLEAN` or `STOPPED_FORCED` with `cancellation_incomplete` |
| Process restart after interrupted append | Store recovery treats the final unterminated/bad line as `TRUNCATED_FINAL_RECORD`; idempotent `event_id` prevents replay | State preserved; no duplicate events |
| Multi-worker / multi-process duplication | **Not solvable by process-local lock** | See §6.4 |

### 6.2 Protection classification

- **Process-local lock (implemented today at the store boundary):** the store's per-instance
  `RLock` and per-path `RLock` registry (`monitoring_state_store.py:34-45,90`) serialise appends
  **within one process**. This is necessary but not sufficient.
- **Filesystem/state-store coordination (available primitive):** the append-only journal's
  deterministic `event_id` + content digest gives idempotency and conflict detection for
  appends. It prevents duplicate persisted events but does **not** prevent two processes from
  running evaluations concurrently or from interleaving appends.
- **Single-worker deployment guarantee (assumed, not enforced):** `systemd/tradingbot.service`
  runs one uvicorn process without `--workers`. This is the canonical deployment but source
  cannot enforce it against an operator starting a second process on another host or port.
- **Lease / leader election (required for cross-process safety, not implemented):** the V1 design
  proposes a deployment-scoped OS advisory exclusive lock plus DB fencing generation
  (`WORK_I_SUPERVISOR_CONTINUOUS_MONITORING_DRIFT_ALERT_DESIGN_V1.md` §8). No such mechanism
  exists at HEAD.

### 6.3 Scheduled vs manual sharing

The scheduled and manual paths must call the **same** run function and acquire the **same** guard
object. The manual path must not create a second timer or a second store/service instance. This
guarantees at most one Phase 1 evaluation and one Phase 2 reduce/persist at a time per process.

### 6.4 Cross-process safety verdict

The source at HEAD provides **no cross-process exclusion** for the scheduler. A process-local
`RLock` and an append-only journal with idempotent IDs do not prevent two processes from both
evaluating and both attempting appends. Idempotency collapses identical `event_id`s, but two
processes computing from the same journal can still produce divergent in-memory transitions and
racing appends.

**Therefore Production activation of the Phase 3 scheduler is BLOCKED until a cross-process
ownership authority is implemented and approved** (one of: enforced single-process deployment
contract with a startup self-check that refuses to start when another monitor owner holds the
lease; or an OS advisory file lock held for the owner's lifetime; or a DB lease with fencing
generation as proposed in §8 of the V1 design). Phase 3A–3E implementation may proceed in
non-Production; only the Production activation gate is blocked.

### 6.5 Cancellation caveat

Python thread/asyncio cancellation cannot terminate blocking file or socket I/O. If a bounded
reader blocks past `cancel_wait`, the run records `cancellation_incomplete=true`, the owner
enters `STOPPED_FORCED`, and no new run is started until the previous worker is observed to have
exited. The design must not claim that cancellation guarantees termination.

---

## 7. Health / read model

### 7.1 Fields

The health model is a frozen, read-only contract. All timestamps are UTC. It contains no
secrets, no raw stack traces, no raw evidence payloads and no trading-authority fields.

| Field | Type | Source | Notes |
|---|---|---|---|
| `enabled` | bool | flag/config | False when OFF or invalid |
| `scheduler_state` | enum | owner | §4 vocabulary: `DISABLED/STARTING/IDLE/RUNNING/DEGRADED/STOPPING/STOPPED/FAILED` |
| `feature_flag_source` | enum | flag parser | `ENV` / `DEFAULT_OFF` / `INVALID` |
| `disabled_reason` | token\|null | flag/config | `FLAG_OFF`, `FLAG_INVALID`, `CONFIG_INVALID` |
| `started_at` | datetime\|null | owner | Ownership acquired time |
| `last_run_started_at` | datetime\|null | owner | Last run start |
| `last_run_completed_at` | datetime\|null | owner | Last run finish (success or failure) |
| `last_success_at` | datetime\|null | owner | Last run with no fatal error |
| `next_run_at` | datetime\|null | owner | Deterministic from interval + last run; null when disabled |
| `current_run_id` | token\|null | owner | Present only while `RUNNING` |
| `run_count` | count | owner | Monotonic |
| `success_count` | count | owner | |
| `failure_count` | count | owner | |
| `timeout_count` | count | owner | |
| `skipped_overlap_count` | count | owner | |
| `last_duration_ms` | int\|null | owner | Bounded |
| `last_result_status` | token\|null | run | `MonitorResult.aggregate_status`, e.g. `NORMAL/INFO/WARNING/CRITICAL/UNKNOWN/...` |
| `last_error_code` | token\|null | owner | Bounded reason code from a fixed vocabulary, no exception text |
| `last_error_summary` | token\|null | owner | Sanitized, length-bounded, no path/stack/secret |
| `observation_count` | count | last run | Bounded by `max_observations` |
| `anomaly_count` | count | last run | `DriftResult` count |
| `active_anomaly_count` | count | recovered state | Active `AnomalyState` count |
| `eligible_notification_count` | count | cycle | **Count only**; no delivery in Phase 3 |
| `state_recovery_status` | enum | store | `OK` / `PARTIAL` / `CORRUPT` / `UNAVAILABLE` / `NOT_ATTEMPTED` |
| `state_corruption_count` | count | `RecoveryResult.corruption_count` | |
| `state_partial_recovery` | bool | `RecoveryResult.partial` | |
| `source_freshness` | token\|null | last run | Worst applicable freshness policy state |
| `source_availability` | token\|null | last run | Worst availability state |
| `degraded_reasons` | tuple[token] | owner | Sorted, deduplicated, capped (≤32), from fixed vocabulary |
| `updated_at` | datetime | owner | Last health mutation time |

### 7.2 Requirements

- **No secrets.** No token, credential, path, prompt or provider output appears.
- **No raw stack trace.** Errors are reduced to a bounded code plus a sanitized summary.
- **No raw evidence payload.** Only counts, IDs and reason codes.
- **No trading-authority fields.** Forbidden field names (mirroring
  `tests/test_supervisor_monitoring_integration.py:202-210`): `allow`, `block`, `order`,
  `execute`, `arm`, `disarm`, `runtime`, `tradingRecommendation`, `governance`, `remediate`.
- **Deterministic status vocabulary.** All status/reason values come from fixed Literals/enums;
  no free-form strings.
- **Backward-compatible optional Supervisor metadata.** Any Supervisor metadata added for
  monitoring is optional and additive; existing snapshot/history contracts are unchanged.
- **Flag OFF health remains readable.** With the flag OFF, a health read returns a well-formed
  model whose `enabled=false`, `scheduler_state=DISABLED`, `feature_flag_source=DEFAULT_OFF`,
  `disabled_reason=FLAG_OFF`, nulls for time fields and zero counters, **without** starting,
  loading or writing anything.

### 7.3 Health is the read model, not the journal

Health is an in-memory projection rebuilt from the owner and the last bounded recovery. It is not
persisted in Phase 3. Persisted monitoring state stays in the Phase 2 journal only.

---

## 8. Manual one-shot trigger design

The manual trigger is **designed, not implemented**.

### 8.1 Required behavior

- **Observation/evaluation only.** Runs the same bounded sequence as §5, steps 1–10.
- **Same bounded run path.** Calls the one shared run function; no duplicate logic.
- **Same non-overlap guard.** Shared with the scheduled path; no parallel run.
- **Scheduler may remain disabled.** The flag OFF disables scheduled runs but the manual path may
  still be explicitly invoked if (and only if) the invocation is authorized and the run is
  bounded. The recurring timer is not created.
- **No recurring task created.** One-shot lifecycle only.
- **No notification delivery.** Eligibility may be counted; nothing is sent.
- **Explicit dry observational semantics.** The response states observation-only and carries no
  trading authority.
- **Request id / idempotency key.** Caller supplies a bounded idempotency key; repeated requests
  with the same key return the same run reference and do not re-execute.
- **Run status / result reference.** Response returns a bounded run reference (run ID, status,
  timestamps, counts, reason codes, state-recovery status) — never raw evidence.
- **Bounded timeout.** The run obeys `run_timeout`; the trigger does not hold the request beyond
  a bounded wait.
- **No raw evidence response.**
- **No trading/configuration mutation.**

### 8.2 Security boundary audit

| Boundary | Requirement | Basis |
|---|---|---|
| Authentication | Operator session required (`Depends(require_operator_session)`) | Follows existing control-route precedent (`backend/auth/dependencies.py`) |
| Authorization | Operator role/scope; no anonymous trigger | Same |
| CSRF | Path added to `_csrf_protected` (`backend/main.py:677-710`) | Mutating action; existing allowlist |
| Allowed HTTP method | `POST` only (read-only GET is not sufficient for a mutating trigger) | Existing mutating routes use POST |
| Audit record | Durable actor/time/run-id/decision record, bounded | Mirrors Supervisor audit-store convention |
| Rate limit | Per-session bound; excess returns rate-limited status | Follows `TRADINGAI_AUTH_RATE_LIMIT` convention |
| Concurrency conflict | `BUSY`/409-class when the guard is held | §6 |
| Idempotent retry | Same idempotency key → same run reference, no re-execution | §8.1 |
| Disabled by default | Endpoint absent/404 until explicitly enabled by a separate approval | §3 |
| No generic arbitrary-query endpoint | Trigger takes no caller-supplied query/metric/scope; only an optional idempotency key | Prevents arbitrary source probing |

The manual trigger must **not** expose a generic arbitrary-query endpoint. It cannot accept
metric names, source names, windows, filters or SQL.

---

## 9. Read API design

Read APIs are **designed, not implemented**. All routes are read-only and return sanitized,
bounded JSON. Vocabulary is deterministic. No route mutates state. A route may be unavailable
when the feature is disabled or the state store is corrupt; unavailability is explicit, not a
falsely empty success.

| # | Route | Method | Auth | Response contract | Max limit | Pagination | Sanitization | Disabled behavior | Unavailable behavior | Corruption/partial |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `/api/supervisor/monitoring/health` | GET | none required for the non-sensitive subset; operator session if enriched | Health model §7.1 | n/a | n/a | No secrets/paths/stack/evidence | `200` with `enabled=false`, `scheduler_state=DISABLED`, `disabled_reason=FLAG_OFF` | `503` with `state_recovery_status=UNAVAILABLE` | `state_recovery_status=CORRUPT/PARTIAL` with counts |
| 2 | `/api/supervisor/monitoring/runs/latest` | GET | operator session | Latest run summary (run id, status, timestamps, counts, reason codes, result status) | 1 | none | No raw evidence | `200` with `run=null`, `disabled_reason` | `503` | `partial=true` surfaced |
| 3 | `/api/supervisor/monitoring/anomalies/active` | GET | operator session | Active `AnomalyState` summaries (fingerprint, metric, category, severity, lifecycle, first/last seen, occurrence count) | 100 | cursor (fingerprint) | No offending raw identity, only fingerprint | `200` empty list | `503` | `partial`/`corruption_count` surfaced |
| 4 | `/api/supervisor/monitoring/anomalies/resolved` | GET | operator session | Resolved episode summaries | 100 | cursor | Same | `200` empty list | `503` | Same |
| 5 | `/api/supervisor/monitoring/state/integrity` | GET | operator session | `RecoveryResult` projection (records seen, bytes read, corruption count, duplicates, partial, warnings, corrupt positions) | 100 corrupt records | cursor (position) | Positions/reasons only; no record content | `200` `NOT_ATTEMPTED` | `503` | Primary corruption surface |
| 6 | `/api/supervisor/monitoring/run/{run_id}` | GET | operator session | Manual/scheduled run status by bounded run id | 1 | none | No raw evidence | `404` | `503` | `partial` surfaced |

Shared read-API rules:

- Every list route enforces a hard max limit and a stable cursor; no unbounded reads.
- Every response runs through the same sanitizer used by monitoring models (secret-like marker
  rejection, bounded tokens).
- Flag OFF never starts a run to answer a read; health/integrity reads only report the disabled
  state.
- A corrupt store yields an explicit corruption/partial status, never a silent empty list.
- Existing Supervisor routes are unchanged; the new routes are additive and separately approved.

---

## 10. Failure isolation

Bot/Trading runtime must remain unaffected in every case. All failures are converted to bounded
monitoring health/reason codes and never propagate into `startup_event`, `shutdown_event`, Bot,
MM, Governance or execution.

| Failure | Detection | Monitoring behavior | Bot/trading effect |
|---|---|---|---|
| Shared Query failure | exception/timeout from the shared facade | Source becomes UNKNOWN/PARTIAL; other sources continue; `failure_count++` | None |
| All sources unavailable | no usable observations | Run completes with `aggregate_status=UNKNOWN`, `partial_result=true`; no false NORMAL | None; never maps to ALLOW/BLOCK |
| Stale sources | freshness policy state = STALE | Source retained with STALE; no auto-resolve of incidents | None |
| Malformed evidence | schema/integrity validation | Record isolated; `invalid_count++`; `MODEL_VALIDATION_FAILED` | None |
| Phase 1 validation failure | `one_shot_monitor` `ValidationError`/`TypeError` at call boundary | Run failed; `failure_count++`; no write; guard released | None |
| Phase 2 recovery corruption | `RecoveryResult.partial`/`corruption_count>0` | `state_recovery_status=CORRUPT/PARTIAL`; continue with recovered states only | None |
| Append conflict | `AppendOutcome.CONFLICT` | `PERSISTENCE_CONFLICT`; run DEGRADED; no overwrite | None |
| State journal unavailable | `OSError` on append; store `persist_errors++` | `PERSISTENCE_REJECTED`; `state_recovery_status=UNAVAILABLE`; eligible count suppressed | None |
| Run timeout | deadline exceeded | `RUN_TIMEOUT`; `timeout_count++`; DEGRADED; guard released | None |
| Cancellation | cancel event observed | `STOPPING`→`STOPPED`; `cancellation_incomplete` if forced | None; shutdown continues |
| Unexpected exception | broad try/except at owner boundary | `unexpected_exception` sanitized code; `failure_count++`; never re-raised | None |
| Scheduler startup failure | flag/config/ownership/store error | `DISABLED`/`FAILED`; `startup_event` continues past the monitoring step | None; app starts normally |
| Shutdown timeout | drain exceeds `cancel_wait` | `STOPPED_FORCED`; `cancellation_incomplete=true`; shutdown proceeds | None; Bot/MM shutdown not delayed beyond bound |

Containment rules: monitoring code shares no lock, transaction, thread or exception path with
trading components; a monitoring failure cannot cancel, block or corrupt Bot/MM/Governance
operations. No retry storm: consecutive failures use capped backoff and a failure threshold that
moves the owner to `FAILED` (no automatic restart).

---

## 11. Restart contract

| Concern | Design |
|---|---|
| Flag re-evaluation | The flag is read fresh at each process start; no cached ON state survives restart. |
| Scheduler state reset | Scheduler state machine returns to `DISABLED`/`STARTING`; no in-memory counters are treated as durable. |
| State-journal recovery | On first owned run, `store.recover()` performs one bounded pass; latest event per fingerprint wins. |
| Interrupted-run status | The last run of the previous process is marked interrupted in the **next authorized state write**; it is never silently reported as success. |
| No duplicate event replay | Recovery indexes `event_id`; re-appending an identical event is `DUPLICATE`; conflicting content is `CONFLICT`. |
| Cooldown preservation | `cooldown_until` is stored in `AnomalyState` and survives restart; recovery restores suppression deadlines. |
| Acknowledgement preservation | `acknowledged_at`/`acknowledged_by` survive restart; ACK is not lost or auto-cleared. |
| Resolved-state preservation | `RESOLVED` episodes remain resolved; recurrence creates a new episode number, not an overwrite. |
| Next-run calculation | `next_run_at = now + startup_delay` at startup, then `last_run + interval`; no catch-up for missed intervals during downtime. |
| Startup delay | Applies after successful composition; prevents a query burst while Bot/MM are still converging. |
| Corruption/degraded status | `state_recovery_status` reflects `OK`/`PARTIAL`/`CORRUPT`; degradation is surfaced in health. |
| Safe shutdown timeout | `STOPPING` drains within `cancel_wait`; forced stop records `cancellation_incomplete`. |
| No catch-up storm | At most one pending tick; missed intervals collapse to a single next run. A downtime of N intervals does not enqueue N runs. |
| Backwards clock | A clock regression detected at step 2 puts the owner in `DEGRADED` and suspends new eligibility until monotonic recovery; persisted deadlines remain UTC. |

---

## 12. Observability

### 12.1 Approved signals

- **Structured logs** with fixed fields only.
- **Run IDs** (bounded token), monotonic and restart-safe per process.
- **Reason codes** from the fixed vocabulary in §4, §5, §10, §11.
- **Duration** (ms, bounded) per run and per step.
- **Source status** (availability/freshness per source, aggregate worst state).
- **Result counts** (observations, anomalies, active/resolved, eligible count, persisted events).
- **Recovery integrity** (`records_read`, `bytes_read`, `corruption_count`, `duplicate_events`, `partial`).
- **Overlap skips** (`skipped_overlap_count`, `SKIPPED_OVERLAP`).
- **Timeout/cancellation** (`timeout_count`, `cancellation_incomplete`).
- **Flag state** (`feature_flag_source`, `enabled`, `disabled_reason`).

### 12.2 Prohibited signals

- Credentials, API keys, tokens, session secrets, cookies.
- Raw evidence payloads, raw journal records, raw trace records.
- Raw prompts, provider outputs, LLM text.
- Account/broker/exchange secrets or balances.
- Full stack traces in public API responses or logs (sanitized summary only).
- High-cardinality labels: no unbounded symbol sets, no free-form user text, no raw IDs used as
  metric labels; all label sets are bounded and enumerated.

---

## 13. Implementation plan

All task IDs are prefixed `TRADINGAI-WORK-I-03-`. Approval of this document authorizes no code.
Phases are sequential. Each phase lists modules/tests/flags/writes/API/lifecycle/rollback/
approval/acceptance.

### Phase 3A — Scheduler and health models + pure state machine

- **Task ID:** `TRADINGAI-WORK-I-03-P3A-MODELS-STATE-MACHINE`
- **Modules/files:** proposed `backend/supervisor/monitoring_scheduler_models.py` (health model,
  run result, config model), `backend/supervisor/monitoring_scheduler_state.py` (pure state
  machine). Reuse Phase 1/2 models unchanged.
- **Tests:** proposed `tests/test_supervisor_scheduler_models.py`,
  `tests/test_supervisor_scheduler_state.py`; extend the no-scheduler guard in
  `tests/test_supervisor_monitoring_integration.py` only for the new pure modules (must remain
  import-pure, no task/thread).
- **Feature flags:** define the parser for `AI_SUPERVISOR_CONTINUOUS_MONITORING_ENABLED` and the
  config keys (§3). No timer.
- **Persistence writes:** NONE.
- **API changes:** none.
- **Lifecycle changes:** none.
- **Rollback:** delete the two modules and their tests.
- **Approvals:** implementation only.
- **Acceptance:** pure models; deterministic states/transitions/reason codes; health field
  vocabulary complete (§7); forbidden trading fields absent; no `asyncio`/`threading` import.

### Phase 3B — Manual in-process one-shot runner

- **Task ID:** `TRADINGAI-WORK-I-03-P3B-MANUAL-ONESHOT`
- **Modules/files:** proposed `backend/supervisor/monitoring_scheduler_run.py` exposing one
  bounded `run_monitoring_once(...)` that calls `one_shot_monitor` and
  `MonitoringStateService`/`reduce_monitoring_state`; no API, no timer.
- **Tests:** proposed `tests/test_supervisor_scheduler_run.py` (bounds, partial/corrupt,
  idempotency key, no network/provider/trading).
- **Feature flags:** manual path may run with the scheduler flag OFF; guarded by an explicit
  invocation contract only.
- **Persistence writes:** explicit, only when an explicit journal path is supplied and a
  persistence argument is passed; default test invocation writes nothing.
- **API changes:** none.
- **Lifecycle changes:** none.
- **Rollback:** remove the runner module; no migration.
- **Approvals:** implementation only.
- **Acceptance:** same bounded sequence as §5; guard shared with any future scheduler; no
  notification; no trading authority.

### Phase 3C — Default-OFF scheduler lifecycle and startup/shutdown wiring

- **Task ID:** `TRADINGAI-WORK-I-03-P3C-SCHEDULER-LIFECYCLE`
- **Modules/files:** proposed `backend/supervisor/monitoring_scheduler.py` (owner, interval timer
  via a single bounded primitive, state machine driver); minimal guarded integration in
  `backend/main.py` `startup_event`/`shutdown_event`.
- **Tests:** proposed `tests/test_supervisor_scheduler_lifecycle.py` (OFF creates no resources;
  startup delay; single owner; overlap skip; timeout; cancellation; shutdown drain; failure
  isolation; restart). Update the capability metadata test only after approval of the scheduler
  registration change.
- **Feature flags:** `AI_SUPERVISOR_CONTINUOUS_MONITORING_ENABLED` (default OFF). No dynamic
  enablement.
- **Persistence writes:** Phase 2 journal only, only when ON and only at step 8.
- **API changes:** none.
- **Lifecycle changes:** adds opt-in start/stop in `backend/main.py` only; must be wrapped so a
  failure cannot break app startup.
- **Rollback:** flag OFF; the owner is not started; no service change.
- **Approvals:** implementation + explicit non-Production lifecycle wiring review. Production
  activation remains **BLOCKED** on cross-process ownership (§6.4).
- **Acceptance:** OFF is inert; ON under a single process is non-overlapping and bounded;
  failures do not affect Bot runtime; shutdown drains within bound.

### Phase 3D — Read-only health API and manual trigger API (separate approval)

- **Task ID:** `TRADINGAI-WORK-I-03-P3D-HEALTH-TRIGGER-API`
- **Modules/files:** proposed `backend/api/supervisor_monitoring.py` (read routes §9 and the
  manual POST §8). Add the manual path to `_csrf_protected` in `backend/main.py` only if approved.
- **Tests:** proposed `tests/test_supervisor_monitoring_health_api.py`,
  `tests/test_supervisor_monitoring_manual_trigger_api.py` (auth, CSRF, rate limit, idempotency,
  BUSY, disabled/unavailable/corrupt behavior, sanitization, no arbitrary query).
- **Feature flags:** health read available when OFF (reports disabled); manual trigger requires a
  separate flag or explicit route enablement and separate approval.
- **Persistence writes:** only via the bounded run at step 8.
- **API changes:** additive read routes + one mutating POST.
- **Lifecycle changes:** none beyond route registration.
- **Rollback:** remove route registration/flag; monitoring state preserved.
- **Approvals:** separate explicit API and security-boundary approval; **not** included in the
  scheduler implementation approval.
- **Acceptance:** every route matches §9; manual trigger is authenticated, CSRF-protected,
  idempotent, rate-limited and never arbitrary-query; no trading mutation.

### Phase 3E — Controlled non-Production acceptance

- **Task ID:** `TRADINGAI-WORK-I-03-P3E-NONPROD-ACCEPTANCE`
- **Modules/files:** acceptance runbook/documentation only; no code change.
- **Tests:** exercise ON in an isolated non-Production environment with injected/sandbox sources;
  verify bounds, overlap skips, cancellation, restart recovery, corruption isolation and Bot
  failure isolation.
- **Feature flags:** ON only in the isolated environment; every default remains OFF elsewhere.
- **Persistence writes:** isolated monitor journal only.
- **API changes:** read APIs only.
- **Lifecycle changes:** isolated environment only.
- **Rollback:** flag OFF and drain; preserve state.
- **Approvals:** explicit human non-Production acceptance authorization. Production remains
  BLOCKED on §6.4.
- **Acceptance:** injected/sandbox runs meet §5–§6 budgets; no overlap under cancellation/
  restart; failures do not affect runtime; OFF is inert; no notification sent.

---

## 14. Validation checklist

- [x] Design is consistent across flag, state machine, run contract, non-overlap, health,
      manual trigger, read API, failure isolation, restart, observability and plan.
- [x] Existing lifecycle evidence is cited with paths/functions for every current-behavior claim.
- [x] Application and test files are unchanged.
- [x] No scheduler/task/timer implementation.
- [x] No API route added.
- [x] No persistence write.
- [x] No monitoring execution.
- [x] No notification.
- [x] `git status` contains only the new design document (plus the ignored report).
- [x] Production untouched.
- [x] Cross-process safety explicitly marked as BLOCKED for Production activation.

Design verdict: PASS for documentation/audit completion. Implementation, API exposure and
Production activation remain unapproved. Phase 3A–3E implementation may proceed in non-Production;
Production scheduler activation is **BLOCKED** until the cross-process ownership authority in
§6.4 is implemented and separately approved.
