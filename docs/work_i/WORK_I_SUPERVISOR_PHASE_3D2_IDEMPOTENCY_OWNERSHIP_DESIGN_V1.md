# Work I③ Phase 3D-2 — Idempotency and cross-process ownership design V1

Task: `TRADINGAI-WORK-I-03-PHASE-3D-2-IDEMPOTENCY-OWNERSHIP-DESIGN-AUDIT-1`
Workstream: 作業I③
Status: **design and audit only**. No store implemented, no lock opened or acquired, no API route,
no runner invocation, no monitoring execution, no persistence write, no commit.
Audited commit: `b44126c62cc091d0df010fa46b07b2c9d1cf672b` (Phase 3D-1 pure models).
Branch: `feature/work-i-next`
Worktree: `/home/joe4410joe/tradingai_prod_v1.worktrees/work-i-integration`

This document designs, but does not implement, the restart-safe API idempotency authority and the
OS advisory cross-process ownership lock required before a future authenticated Supervisor
manual-trigger route may execute. It builds on the Phase 3D-1 pure models
(`backend/supervisor/monitoring_trigger_models.py`, `backend/supervisor/monitoring_trigger_security.py`)
without changing them. All current-behavior statements are source findings at the audited commit.

---

## 1. Scope, safety gate and evidence standard

### 1.1 Safety gate

| Check | Expected | Observed | Verdict |
|---|---|---|---|
| pwd == WORKTREE | WORKTREE | `/home/joe4410joe/tradingai_prod_v1.worktrees/work-i-integration` | PASS |
| branch | `feature/work-i-next` | `feature/work-i-next` | PASS |
| HEAD | `b44126c` | `b44126c62cc091d0df010fa46b07b2c9d1cf672b` | PASS |
| HEAD parent | `d1fbd0f` | `d1fbd0f480d8ed1296e04e7febc0bf94ad772180` | PASS |
| HEAD is non-merge | single parent | one parent | PASS |
| `git status --short` | empty | empty | PASS |
| HEAD files | 4 Phase 3D-1 files | security+models modules and their tests only | PASS |
| no direct child of START_HEAD implements this task | none | none | PASS |
| local `main` | read-only | `260a388fa400b4c0b1ec6c609b3587a49f1e8824` | PASS |
| `origin/main` | read-only | `260a388fa400b4c0b1ec6c609b3587a49f1e8824` | PASS |

No fetch, pull, reset, merge, rebase, cherry-pick, stash or push. No new worktree, no branch
switch. The only writes are this tracked design document and the ignored report under
`tmp/chatgpt_reviews/`. No application or test file is modified.

### 1.2 Prohibitions observed

No application/test change, no idempotency record, no database, no lock file opened or acquired,
no `flock`, no API route, no `ManualMonitoringRunner` invocation, no monitoring execution, no
anomaly-state write, no scheduler, no background task, no notification, no Production/runtime/
database write, no service restart, no deploy, no Bot operation, no ARM, no Governance execution,
no order, no commit, no merge/cherry-pick/rebase/push.

**Preserved truths (explicit; not weakened anywhere in this document):**

- `AUTHORIZATION_MODEL = IMPLEMENTED` (Phase 3D-1; no Production capability source)
- `PRODUCTION_AUTHORIZATION_SOURCE = UNRESOLVED`
- `POST_ROUTE_IMPLEMENTATION_GATE = BLOCKED`
- `PRODUCTION_ACTIVATION_ALLOWED = NO`
- `IDEMPOTENCY_STORAGE_RECOMMENDATION = SQLITE_TRANSACTIONAL`
- `ATOMIC_MULTI_PROCESS_CLAIM = YES`
- `RESTART_SAFE = YES`
- `OS_ADVISORY_LOCK_DESIGN = YES`
- `LOCK_OPENED = NO`
- `LOCK_ACQUIRED = NO`
- `FLOCK_CALLED = NO`

---

## 2. Distinct identities (must not be conflated)

| Identity | Authority (today) | Purpose | This design |
|---|---|---|---|
| API request idempotency | none | de-duplicate one manual-trigger HTTP request across retries/restarts | **new durable authority designed here** |
| Anomaly-event idempotency | Phase 2 `MonitoringStateStore.append` (`backend/supervisor/monitoring_state_store.py:206-250`), deterministic `event_id` + content digest (`DUPLICATE`/`CONFLICT`) | de-duplicate persisted anomaly-state events | unchanged; **not** API idempotency |
| Audit-event identity | `SupervisorAuditStore` (`backend/supervisor/audit_store.py:16`), unique `event_id` in `supervisor_events` | durable sanitized Supervisor history/replay | unchanged; **not** idempotency or ownership |
| Cross-process execution ownership | none | ensure at most one monitoring execution across processes | **new OS advisory lock designed here** |
| In-process overlap control | Phase 3B `ManualMonitoringRunner._active_run_id` (`manual_monitoring_runner.py:233-234,338-359`) | serialise runs within one process | unchanged; a process-local guard |
| Process metadata | none | diagnostic owner evidence | bounded, non-authoritative side record |
| Fencing token/generation | none | reject a stale owner's durable writes | **new monotonic generation designed here** |
| Monitoring result persistence | Phase 2 `MonitoringStateService`/`MonitoringStateStore` | persist anomaly state (`dry_run` default) | unchanged; only Phase 2 may write anomaly state |

The design keeps all eight separate. Phase 2 event identity is explicitly **not** reused as API
idempotency, and the audit store is explicitly **not** the ownership or idempotency authority.

---

## 3. Existing repository patterns inspected

| Pattern | Evidence | Relevance |
|---|---|---|
| Append-only JSONL store | `backend/runtime/cycle_evidence_store.py:301-343`, `backend/supervisor/monitoring_state_store.py:206-250`; both use `os.open(O_CREAT\|O_APPEND\|O_WRONLY, 0o600)` + optional `fsync`, process-local `RLock` and a per-path lock registry (`monitoring_state_store.py:34-45`). | De-dup is by deterministic `event_id`; **no compare-and-swap or multi-process claim**. |
| Bounded JSONL recovery | `monitoring_state_store.py:139-186` recovers latest state per fingerprint with record/byte bounds and isolates corrupt/truncated lines (`CorruptRecord`). | Good for bounded reads, but append-only cannot atomically claim. |
| SQLite store + transaction | `backend/supervisor/audit_store.py:16-38` uses `sqlite3.connect(timeout=2.0)`, `BEGIN IMMEDIATE`, unique `event_id`, process `RLock`, 5000-event cap, secret-marker redaction. | The only transactional multi-process-capable store in the repository; **closest reusable precedent**. |
| Atomic durable file replace | `backend/strategy/parameters/store.py:347-397`: temp `O_CREAT\|O_EXCL\|O_WRONLY\|O_NOFOLLOW 0o600`, `fsync`, regular-file check, `os.replace`, directory `fsync`; unsafe-file checks for symlink/non-regular/permissions (`:324-333,452-467`). `backend/runtime/paper_account_store.py:134-157` uses `tempfile.mkstemp` + `fsync` + `os.replace`. | Precedent for atomic metadata writes and symlink-safe opens. |
| O_EXCL lock-file idiom | `backend/money_management/live_initial_baseline.py:112-150`: `os.open(lock, O_CREAT\|O_EXCL\|O_WRONLY\|O_NOFOLLOW, 0o600)` then `unlink` in `finally`; failure → `BASELINE_INITIALIZATION_IN_PROGRESS`. | Existence-based mutual exclusion; **not crash-safe** (a crash leaves the lock file forever). Not sufficient as the ownership authority. |
| `fcntl.flock` usage | none found anywhere in `backend/`. | The advisory lock is a **new** mechanism; the task requires its design. |
| Versioned envelope + integrity | `backend/strategy/parameters/store.py:28-29` `strategy-parameter-envelope/v1`, `SHA256`; `MAX_FILE_SIZE = 256 * 1024`. | Precedent for schema version + digest on durable records. |
| Runtime path convention | `logs/runtime/*` defaults with env overrides: `DEFAULT_SUPERVISOR_AUDIT_PATH` (`audit_store.py:10`), `DEFAULT_CYCLE_EVIDENCE_PATH`, `TRADING_E2E_TRACE_PATH`, `PARAMETER_PERFORMANCE_PATH`. Directory created with `mkdir(parents=True, exist_ok=True)`. | Path authority convention. |
| Server/deployment | `systemd/tradingbot.service`: single `uvicorn backend.main:app --host 127.0.0.1 --port 8001`, `Restart=always`, `User/Group=joe4410joe`, `UMask=0077`, no `--workers`; `.env` via `EnvironmentFile`. | Canonical deployment is single-process; multi-process is possible in principle and must be assumed. |
| File modes | Stores open `0o600`; systemd `UMask=0077`. | 0o600 files under a 0o700 directory. |

**Reuse classification**

- `SupervisorAuditStore` transaction idiom — **REUSE_PATTERN** (transactional SQLite + `BEGIN IMMEDIATE` + bounded recovery), but the audit DB is **not** reused as the idempotency store.
- JSONL stores — **REUSE_PATTERN_FOR_EVIDENCE_ONLY**; rejected as the API idempotency authority (no atomic claim).
- Atomic-replace and O_NOFOLLOW helpers — **REUSE_PATTERN** for lock metadata and bounded side files.
- No existing idempotency or OS-lock authority — **NEW_REQUIRED**.

---

## 4. IDEMPOTENCY AUTHORITY (design)

### 4.1 Durable record

A dedicated table (or equivalent transactional record) keyed by
`(operation, principal_scope, idempotency_key)`:

| Field | Meaning |
|---|---|
| `schema_version` | versioned schema, e.g. `supervisor-trigger-idempotency-v1` |
| `idempotency_key` | bounded client key (Phase 3D-1 `request_id` rules) |
| `request_fingerprint` | Phase 3D-1 versioned fingerprint (`supervisor-trigger-fingerprint-v1`) |
| `principal_scope` | privacy-safe actor/authorization-scope reference (never raw identity) |
| `operation` | fixed operation name, e.g. `SUPERVISOR_MONITORING_RUN_ONCE` |
| `created_at`, `updated_at`, `expires_at` | UTC wall-clock timestamps |
| `state` | see §4.2 |
| `run_id` | assigned when a run starts |
| `result_ref` / `result_summary` | bounded sanitized result reference/summary |
| `error_class` | bounded error classification |
| `generation` | monotonic fencing generation |
| `owner_generation` | generation the current owner holds |
| `lease_expires_at` | recovery lease deadline |
| `attempt_count` | bounded |

### 4.2 States

`CLAIMED`, `IN_PROGRESS`, `COMPLETED`, `FAILED_RETRYABLE`, `FAILED_FINAL`, `EXPIRED`, `CONFLICT`,
`CORRUPT`.

### 4.3 Deterministic behavior

| Situation | Behavior |
|---|---|
| First request | atomic claim → `CLAIMED`, then `IN_PROGRESS` when running |
| Same key + same fingerprint, `COMPLETED` | replay stored bounded result (`REPLAY_COMPLETED`); do not re-execute |
| Same key + different fingerprint | `CONFLICT`; record kept; new payload never executed under the old key |
| Retry during `IN_PROGRESS` | `ALREADY_IN_PROGRESS`; no second execution |
| Retry after `COMPLETED` | `REPLAY_COMPLETED` |
| Retry after `FAILED_RETRYABLE` (within retention) | `RETRY_ALLOWED` → re-claim atomically with a new generation |
| Retry after `FAILED_FINAL` | `CONFLICT`/terminal rejection; operator action required |
| Expired record | `EXPIRED_RECLAIMED` under a new generation; the expired record is retained until cleanup |
| Corrupt record | `CORRUPT`; fail closed (no execution) and surface for operator review |
| Authority unavailable | `AUTHORITY_UNAVAILABLE`; fail closed before execution |
| Crash after claim | lease/generation recovery (see §10); never silently re-execute while `IN_PROGRESS` un-reconciled |
| Crash after execution, before completion record | conservative `FAILED_FINAL`/operator review unless a durable result reference proves completion (see §10) |

---

## 5. STORAGE SELECTION

| Criterion | Append-only JSONL | SQLite transactional | Reuse existing audit DB |
|---|---|---|---|
| Atomic claim | **No** — append + in-memory index; no CAS; process-local locks only (`monitoring_state_store.py:34-45`) | **Yes** — `BEGIN IMMEDIATE` + `UNIQUE`/PK, one writer | **Yes** — same SQLite primitive |
| Multi-process safety | No (two processes can both append) | Yes (SQLite file lock/transaction, `timeout`) | Yes |
| Crash consistency | Partial (truncated tail recoverable) | Yes (rollback/WAL journal) | Yes |
| Corruption isolation | Per-line isolation | DB-level integrity; per-row recoverable | Yes |
| Replay cost | Full scan / in-memory index | Indexed PK lookup | Indexed |
| Bounded recovery | Record/byte bounds | `LIMIT` queries | `LIMIT` |
| Query/index | Linear | Indexed | Indexed |
| Retention/compaction | Rewrite/truncate (unsafe for active) | `DELETE` + `VACUUM` | `DELETE` |
| Permissions | `0o600` file | `0o600` file + parent dir | `0o600` |
| Operational complexity | Low | Medium | Medium (but couples to conversation audit) |
| Dependencies | stdlib | stdlib `sqlite3` | stdlib |
| Repo consistency | Used for evidence/state | Used by `audit_store.py` | Direct reuse |

**Decision:** a **dedicated SQLite transactional store** (a new file, not
`supervisor_audit.sqlite3`) is the API idempotency authority. JSONL is rejected for the claim path
because it cannot provide an atomic multi-process compare-and-swap. The existing audit DB is not
reused because idempotency and audit are different authorities with different retention and
failure semantics.

- `IDEMPOTENCY_STORAGE_RECOMMENDATION = SQLITE_TRANSACTIONAL`
- `ATOMIC_MULTI_PROCESS_CLAIM = YES`
- `RESTART_SAFE = YES`

Proposed default path (server-configured, documented default, not request-controlled):
`logs/runtime/supervisor_monitoring_trigger.sqlite3`, file mode `0o600`, database opened with a
bounded `timeout` and `PRAGMA journal_mode=WAL` / `PRAGMA busy_timeout` evaluated during
implementation (the audit store today relies on `timeout` + `BEGIN IMMEDIATE`; the design selects
one consistent configuration).

---

## 6. ATOMIC CLAIM CONTRACT

```
claim(idempotency_key, request_fingerprint, principal_scope, operation, now) -> ClaimResult
```

`ClaimResult ∈ { CLAIM_ACQUIRED, REPLAY_COMPLETED, ALREADY_IN_PROGRESS, CONFLICT,
RETRY_ALLOWED, EXPIRED_RECLAIMED, AUTHORITY_UNAVAILABLE, CORRUPT }`.

- The lookup and the state transition are **one atomic transaction/critical section**
  (`BEGIN IMMEDIATE`; insert-or-update under a `UNIQUE(operation, principal_scope,
  idempotency_key)` constraint). A read-then-write without transactional exclusion is
  unacceptable.
- `CLAIM_ACQUIRED` writes a new record with state `CLAIMED`, a fresh `generation`, and a lease.
- `EXPIRED_RECLAIMED` and `RETRY_ALLOWED` atomically bump `generation` and reset the lease.
- Any ambiguity (corrupt row, unsupported schema, lock/busy beyond timeout, unavailable DB) fails
  closed (`CORRUPT`/`AUTHORITY_UNAVAILABLE`) with no execution.

---

## 7. COMPLETION CONTRACT

Operations: `mark_running`, `complete_success`, `complete_failure_retryable`,
`complete_failure_final`, `read_result` (replay), `expire_record`, `recover_abandoned_claim`.

Every transition verifies, inside one transaction:

- `idempotency_key` and `request_fingerprint`,
- `generation`/fencing token — the caller must hold the current generation,
- the expected current `state`,
- the owner identity/generation.

A **stale owner must not overwrite a newer result**: if the stored `generation` does not equal the
caller's generation, the update is rejected (`CONFLICT`/`STALE_OWNER`) and no write occurs.

---

## 8. RESPONSE REPLAY

- Store/replay only bounded, sanitized response data (classification, code, bounded counts, run
  id, timestamps, warnings) — never credentials, cookies, authorization headers, CSRF tokens, raw
  trace/evidence, raw exception text or stack traces.
- Maximum stored serialized response size: **16 KiB** (hard bound). A larger result stores a stable
  bounded summary plus an opaque result reference; the raw body is never persisted.
- Replay is scoped: a stored record is replayed only to the **same** `principal_scope` and
  `operation`; a different principal/scope gets no replay of another principal's result.
- Replay must re-emit the same bounded classification and idempotency result; it must not re-invoke
  the runner.

---

## 9. RETENTION AND BOUNDEDNESS

| Limit | Proposed value |
|---|---|
| Max active claims (`CLAIMED`/`IN_PROGRESS`) | bounded, e.g. 1,000 (reject claims beyond) |
| Completed-record retention | 24 h (and at most 10,000 completed rows) |
| Failed-record retention | 7 days (`FAILED_RETRYABLE`/`FAILED_FINAL`) |
| Expiry policy | `expires_at` set at claim (e.g. 24 h); inclusive expiry boundary |
| Max DB size | bound enforced with a size check and capacity failure mode |
| Cleanup trigger | on start and on a bounded periodic boundary (no timer task required for correctness) |
| Bounded startup recovery | single `LIMIT`-bounded pass over non-terminal rows |
| Bounded query limits | every query has a hard `LIMIT` |
| Capacity reached | fail closed (`AUTHORITY_UNAVAILABLE`/`CAPACITY`) rather than silently drop |
| Compaction/vacuum | `VACUUM`/incremental cleanup only after retention; never during an active claim |
| Corruption reporting | count + bounded positions returned; corrupt rows isolated, not deleted |

Cleanup must never delete an active (`CLAIMED`/`IN_PROGRESS`, unexpired) claim.

---

## 10. ABANDONED CLAIM RECOVERY

Recovery does **not** rely on elapsed wall-clock alone. It combines:

- **lock availability** — the OS advisory lock can be acquired non-blocking (the previous owner is
  dead), and
- **claim lease** (`lease_expires_at`, `updated_at`), and
- **process-start identity** (where available) to defeat PID reuse, and
- **fencing generation** (atomic bump on reclaim), and
- an explicit **recovery transaction**.

Deterministic outcomes:

| Condition | Outcome |
|---|---|
| Lock acquirable + lease expired + generation matches | `reclaim` under a new generation (preserve attempt count); may retry |
| Lock acquirable + lease not expired | conservative: **left blocked** for operator review |
| Lock held by a live owner | do not touch (BUSY) |
| Terminal `COMPLETED` | replay only |
| Crash after execution, no durable result reference | conservative `FAILED_FINAL` / operator review — never auto-success |
| Crash after execution, durable result reference exists | `complete` from the reference (idempotent) |
| Ambiguous ownership | leave blocked; never re-execute |

A claim may be **replayed** only when `COMPLETED`; **retried** only from `FAILED_RETRYABLE` or a
provably safe reclaim; **reclaimed** only in the lock-acquirable + lease-expired case; **marked
failed** on proven terminal ambiguity; otherwise **left blocked for operator review**.

---

## 11. OS ADVISORY OWNERSHIP LOCK (design)

- **Lock path authority:** server-configured via
  `AI_SUPERVISOR_MONITORING_TRIGGER_LOCK_PATH`, documented default
  `logs/runtime/supervisor_monitoring_trigger.lock`. Never request-controlled.
- **Directory ownership/permissions:** the `logs/runtime` directory is owned by the service user
  with mode `0o700`; `UMask=0077` (`systemd/tradingbot.service`) keeps created files `0o600`.
- **Symlink protection:** open with `O_NOFOLLOW` and reject `lstat`/`stat` symlink or non-regular
  files, mirroring `strategy/parameters/store.py:324-333,452-467`.
- **Regular-file verification:** `stat.S_ISREG` required after open.
- **`O_NOFOLLOW`:** used when available (`getattr(os, "O_NOFOLLOW", 0)`), consistent with repository
  precedent; absence degrades to the explicit symlink/regular-file check.
- **File mode:** `0o600`.
- **Acquisition mode:** `fcntl.flock(fd, LOCK_EX | LOCK_NB)` — **non-blocking exclusive**; failure →
  `BUSY` (no indefinite wait).
- **Descriptor lifetime:** the fd is retained for the entire execution and released in `finally`
  (`LOCK_UN` + `close`).
- **Cleanup policy:** the lock file may persist; ownership is the flock, not the file's existence
  (avoids the crash-leaves-file flaw of the O_EXCL idiom).
- **Crash behavior:** the kernel releases the flock when the process dies.
- **Unsupported platform:** if `fcntl`/`flock` is unavailable, return `UNSUPPORTED` and fail closed
  (no execution).
- **Filesystem requirements / NFS:** advisory `flock` semantics are not reliable on NFS/SMB and are
  not guaranteed across hosts. The design limits ownership to a single host and requires the
  durable idempotency/fencing layer for any cross-process correctness on shared storage.

---

## 12. OWNER METADATA

Metadata is **diagnostic evidence, not lock authority**. Bounded record:

`schema_version`, `process_id`, `process_start_identity` (where available, e.g. `/proc/<pid>/stat`
starttime), `instance_id` (privacy-safe hostname/instance reference), `acquired_at`, `request_id`,
`run_id`, `generation`, `operation`.

- PID alone is **not** ownership proof (PID reuse).
- No secrets, tokens or raw request bodies.
- Prefer storing owner metadata in the idempotency DB `owner_leases` row (transactional) rather
  than the lock file; if a sidecar is used, write it atomically (temp + `fsync` + `os.replace`).

---

## 13. FENCING CONTRACT

- **Token source:** a monotonic `generation` allocated atomically in the idempotency DB within the
  claim/reclaim transaction.
- **Atomic allocation:** `generation = current + 1` under `BEGIN IMMEDIATE` (or row versioning).
- **Storage:** on the idempotency record and the `owner_leases` row.
- **Propagation:** every completion writes the generation; the runner's result reference carries it.
- **Stale-token rejection:** a write whose generation ≠ the stored generation is rejected
  (`STALE_OWNER`), so a resumed old owner cannot overwrite a newer result.
- **Crash behavior:** an abandoned claim's generation is superseded on reclaim; the old fd's lock
  is gone.
- **Lock ↔ transaction relationship:** the OS lock provides live mutual exclusion; the durable
  generation provides stale-writer rejection. The lock alone is **not** sufficient for durable
  stale-writer protection across crashes and must be paired with the DB generation.
- **Lock acquired but token allocation fails:** abort immediately, release the lock, fail closed;
  never execute without a valid generation.

---

## 14. LOCK AND IDEMPOTENCY ORDER

Future order:

1. authentication → authorization → CSRF → request validation (before any durable work)
2. idempotency lookup/claim (transactional)
3. OS ownership acquisition (non-blocking exclusive)
4. fencing-token validation/allocation
5. in-process overlap gate
6. execution budget
7. runner execution (bounded, observation-only)
8. result/state persistence (Phase 2 only, when authorized)
9. idempotency completion (generation-checked)
10. audit completion
11. lock release (`finally`)

Race resolution:

| Race | Resolution |
|---|---|
| claim acquired, lock busy | return `BUSY`; record released/returned to `CLAIMED` or left for lease expiry; no execution |
| lock acquired, claim fails | release lock; `AUTHORITY_UNAVAILABLE`; no execution |
| crash after lock acquisition | kernel releases lock; claim recovered by lease/generation |
| crash after runner execution | conservative (see §10) |
| completion write fails | lock released; claim remains `IN_PROGRESS`; recovered conservatively |
| audit write fails | run/claim result preserved; audit failure surfaced, never converts a deny→allow |
| response lost after successful completion | retry replays `COMPLETED` result |

Fail closed before step 7 whenever ownership/idempotency safety cannot be proven.

---

## 15. CLOCK AND TIME SAFETY

- Durable timestamps are **UTC ISO-8601** (`Z`).
- **Monotonic** time (`time.monotonic`) is used for in-process execution deadlines/budgets.
- **Wall clock (UTC)** is used for durable expiry and retention.
- **Expiry boundary** is inclusive (a record at exactly `expires_at` is expired), matching the
  Phase 3D-1 `evaluate_idempotency` contract.
- **Clock skew:** a bounded maximum tolerated skew (e.g. 120 s) is applied to lease/expiry
  comparisons; measurements beyond tolerance are treated conservatively.
- **Invalid/future timestamps:** rejected; future `created_at`/`updated_at` beyond tolerance are
  treated as invalid and fail closed.
- Client timestamps are never authoritative.

---

## 16. FAILURE ISOLATION

| Failure | Behavior |
|---|---|
| Idempotency store unavailable | `AUTHORITY_UNAVAILABLE`; no execution |
| DB locked/busy beyond timeout | fail closed; no execution |
| DB corrupt / schema unsupported | `CORRUPT`/`UNSUPPORTED`; no execution; surface for operator |
| Capacity exhausted | fail closed; never silently drop |
| Lock directory missing | fail closed (`NOT_CONFIGURED`); no auto-create with unsafe perms |
| Permission denied | fail closed (`ERROR`) |
| Lock busy | `BUSY`; no execution |
| Advisory locking unsupported | `UNSUPPORTED`; no execution |
| Fencing allocation failure | release lock, abort, no execution |
| Recovery ambiguity | leave blocked for operator review; never re-execute |
| Completion failure | claim left for recovery; result not reported as success |
| Audit failure | bounded warning; never converts a deny into an allow |

Ownership/idempotency failure must never break the existing Supervisor snapshot/GET endpoints or
the application; the trigger path fails closed and isolated.

---

## 17. SECURITY

- Paths are **server-configured** (env + documented default); caller-selected lock/DB paths are
  rejected by construction (the Phase 3D-1 request DTO cannot carry paths).
- Symlink attacks → `O_NOFOLLOW` + regular-file/dir checks.
- Permissive modes → `0o600` files under `0o700` dirs; reject files with group/other bits (mirroring
  `store.py:461-467`).
- Malicious idempotency keys → Phase 3D-1 `Token` bounds (1..128, strict pattern) and a total
  request size cap.
- Cross-user data leakage → records are scoped by `principal_scope`; replay requires a matching
  scope; DB file is owner-only.
- Response replay to a different principal/scope → forbidden (scope-checked).
- Secret persistence → only bounded sanitized fields; secret markers rejected/redacted.
- Unbounded growth → retention, size caps and capacity fail-closed.
- Arbitrary SQL/query input → parameterized statements only; no caller-supplied SQL/table/filter.

---

## 18. PRODUCTION ACTIVATION GATES

Before any Production activation all of the following are required:

1. verified Production authorization source (currently `UNRESOLVED`),
2. implemented durable idempotency authority,
3. atomic multi-process claim proven,
4. OS advisory ownership implemented,
5. fencing/stale-owner rejection implemented,
6. execution-deadline enforcement connected,
7. audit authority connected,
8. default-OFF trigger feature flag,
9. multi-process tests passed,
10. crash/restart tests passed,
11. separate Production approval.

Until then:

- `POST_ROUTE_IMPLEMENTATION_GATE = BLOCKED`
- `PRODUCTION_ACTIVATION_ALLOWED = NO`

---

## 19. IMPLEMENTATION PLAN

- **Phase 3D-2A — durable idempotency store.** SQLite schema + version table, bounded
  claim/complete/read/expire/recover CRUD; temp paths only; no API, no runner.
- **Phase 3D-2B — OS advisory lock.** Non-blocking `flock`, owner metadata, fencing integration;
  multi-process/crash tests; no API, no runner.
- **Phase 3D-2C — pure coordinator.** Injected fake runner only; wires idempotency + ownership +
  Phase 3D-1 gate/budget models; no API route.
- **Phase 3D-3 — authenticated POST route.** Default OFF; no Production activation.

Production activation remains a separate, explicitly approved step after §18 gates pass.

---

## 20. Validation checklist (this design task)

- [x] Safety gate verified; HEAD == `b44126c`.
- [x] Required documents and modules inspected read-only.
- [x] Exactly one tracked design document; no application/test file changed.
- [x] No store implemented; no DB created; no lock opened/acquired; no `flock`; no persistence
      write; no route; no runner; no monitoring; no commit.
- [x] Distinct identities separated (§2).
- [x] Storage comparison and recommendation recorded.
- [x] Atomic claim, completion, replay, retention, recovery, lock, metadata, fencing, ordering,
      clock, failure and security contracts defined.
- [x] Production gates and phase plan recorded.

**Design verdict: PASS for design/audit completion.** Implementation and Production activation
remain separately gated and blocked.
