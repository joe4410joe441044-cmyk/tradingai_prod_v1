# BB-MM-F3.1 Money Management Freshness Evidence Gap Completion

TASK_ID: TRADINGAI-WORK-BB-MM-F3-FRESHNESS-EVIDENCE-GAP-COMPLETION-1

VERDICT: BB_MM_F3_FRESHNESS_EVIDENCE_GAP_PASS

CURRENT is not enabled. No TTL was added. Trading calculations were not changed.

HEAD_BEFORE: `ca52a62 work-bb: design mm runtime freshness policy`

HEAD_AFTER: the commit whose message is
`work-bb: complete mm freshness evidence gaps`.
The hash is recorded only in the external audit copy.

## Canonical reconciliation

Canonical HEAD and `origin/main`: `f344864344b0b99a598f674b3e2e4a367bc9fb25`.

Merge-base: `39273a115637edaba42ea49bde732f1ae6436399`.

MAIN_ONLY under the requested trees, not edited here:

- `backend/money_management/loss_execution_integration.py`
- `backend/money_management/loss_http_api.py`
- `tests/test_contract_quantity_projection_repair.py`
- `tests/test_manual_cycle_diagnostics.py`
- `tests/test_money_management_execution_entry_preview.py`
- `tests/test_paper_trade_pipeline.py` is MAIN_ONLY as a file history; this task did not edit it

`runtime_evidence.py`, `owner_snapshot.py`, `bot_manager.py`, and
`loss_authoritative_runtime_metrics.py` are BB-side files. They are not
in the main-side name list. No conflicting function. Main was not merged.

## CURRENT guard

`backend/context/runtime_evidence.py` `_judge` returns UNKNOWN for the
money-management domain after an explicit `freshness` label of STALE or
HISTORICAL, and before any age policy. `freshnessPolicy`, a recent
`producerObservedAt`, and `publishedAt` cannot make that domain CURRENT.
The unused helper that aged `producerObservedAt` into CURRENT or STALE
was removed. Other domains still use their existing labels. A non-MM
domain with `freshness=STALE` stays STALE. A non-MM domain does not gain
a CURRENT path.

## Invalidation reason

`invalidate_mm_observation_evidence(reason=None)` still advances
`_revision` once, and only when the F2 gate matches. It does not move
`as_of`, the completion timestamp, scope, completeness, or equity.
A second call does not advance revision and does not replace the reason.

The reason is stored only on that successful bump. An unknown string is
not stored. A later successful `note_mm_observation_completed` clears it.
A note that does not pass the gate leaves it. A new runtime session
clears it and clears the LIVE source attestation so the next session
does not publish the previous reason. The completion timestamp stays in
producer memory and stays unpublished, as F2 required.

| Call site | Reason |
| --- | --- |
| PAPER price, auto entry, or auto close detected before observe | `PAPER_INPUT_MUTATION` |
| PAPER manual entry fill | `PAPER_MANUAL_ENTRY` |
| PAPER manual close | `PAPER_MANUAL_CLOSE` |
| LIVE manual close | `LIVE_MANUAL_CLOSE` |
| PAPER emergency flatten when the signature changes | `PAPER_EMERGENCY_FLATTEN` |
| PAPER capital reset when the projection changes | `PAPER_CAPITAL_RESET` |
| Stop while the engine mode is paper | `PAPER_RUNTIME_STOP` |
| Stop while the engine mode is live | `LIVE_RUNTIME_STOP` |
| LIVE cache balance, equity, available balance, or positions | `LIVE_ACCOUNT_CACHE_MUTATION` |
| LIVE source only | `LIVE_SOURCE_CHANGED` |
| LIVE authenticated only | `LIVE_AUTHENTICATION_CHANGED` |
| LIVE stale only | `LIVE_CACHE_STALE` |
| Identical LIVE copy, generation-only, or engine position only | no call, no reason |

The string `UNKNOWN` is not stored. Absence of a reason keeps the
runtime status UNKNOWN. The reason is not an input to trading.

## Producer liveness

No heartbeat timestamp was added. BotManager already has
`lifecycle_state` and `lifecycle_changed_at`. The owner fragment copies
`STARTING`, `RUNNING`, `STOPPING`, or `STOPPED` as `producerLifecycle`.
`producerLifecycleChangedAt` is that existing transition clock formatted
as UTC. It does not update while the state stays RUNNING, so it is not
an observation heartbeat and it is not a TTL.

STOPPED is published as STOPPED. The value ACTIVE is not produced.
A new session does not keep the previous invalidation reason. Liveness
is read from the current owner at publication, not from a stored flag
inside the old metrics revision. Neither field can make the domain CURRENT.

A periodic producer heartbeat is still missing. Its update point is not
a single safe clock, so it was not invented.

## LIVE source evidence

On a successful LIVE completion note, these fields are copied from the
cache object already passed to observe:

- `liveBalanceSource`
- `livePositionSource`
- `liveAuthenticated`
- `liveStale`
- `liveSourceObservedAt`, only when `lastSync` is already a finite non-negative number
- `liveSnapshotGeneration`, only when `generation` is already a non-negative int

Missing values stay missing. `datetime.now()` is not used for the source
clock. `engine.actual_position` is not read. No account refresh and no
exchange call were added.

The owner copies those fields only together with the F1 completion gate.
After invalidation they are omitted, same as the completion clock.
A PAPER completion clears them. A new session clears them in memory.

## Owner snapshot and runtime evidence

`backend/bot_manager/owner_snapshot.py` is the owner document. There is
no `backend/context/owner_snapshot.py`. The new names are JSON values
on the existing money-management allowlist: strings, bools, and one int.
The copy does not take a lock, a client, a socket, or a credential.

Completion names stay behind the F1 revision gate. The invalidation
reason is copied only when that gate does not copy the completion.
Fragment equity, exposure, and drawdown are unchanged.

Runtime status for a present MM fragment remains UNKNOWN, including when
a reason or LIVE source fields are present. A missing fragment remains
UNAVAILABLE. Reason codes do not enable STALE. An explicit fragment
label `freshness=STALE` still returns STALE for every domain, which is
the previous label path. The MM owner path still sets freshness UNKNOWN,
so production MM fragments do not take that label.

When a failed observe sets `observation_valid` false, the owner still
publishes no MM fragment. The reason remains on the metrics snapshot.
The reader sees UNAVAILABLE rather than a republished completion. That
is the existing valid-observation gate, not a new CURRENT path.

## Advisor, Supervisor, and security

Advisor and Supervisor both read `load_shared_operator_context`. No
second freshness judge was added. The shared result in the new test is
UNKNOWN, authority NONE, trading control FORBIDDEN.

The operator route still depends on `require_operator_session` and
returns 401 without a session. The public view does not contain runtime
evidence, the invalidation reason, producer lifecycle, or LIVE source
fields.

## Tests

```text
python3 -m pytest tests/test_mm_freshness_evidence_gap.py \
  tests/test_mm_observation_invalidation.py \
  tests/test_mm_observation_completion_evidence.py \
  tests/test_ai_context_runtime_producer.py \
  tests/test_ai_context_runtime_evidence.py \
  tests/test_money_management_loss_authoritative_runtime_metrics.py \
  tests/test_ai_context_runtime_coverage.py \
  tests/test_ai_context_runtime_reacceptance.py \
  tests/test_ai_context_owner_wiring.py \
  tests/test_ai_context_owner_cache.py \
  tests/test_supervisor_runtime_acceptance.py \
  tests/test_supervisor_held_evaluation_cache.py
```

Those files passed: 143, then 30, then 120 after the unused age helper
was removed. The last 120 includes the gap file and the F1, F2, and
runtime-evidence files.

Known-failure files, same assertions as the previous acceptance:

```text
python3 -m pytest tests/test_paper_trade_pipeline.py \
  tests/test_mm_stopped_paper_recovery_metrics.py \
  tests/test_mm_baseline_session_transition.py
```

9 failed, 15 passed, 5 subtests. Failures: pipeline lines 111, 185, 206;
stopped paper `False is not true` and `INCONSISTENT != STALE`; baseline
session `'error' == 'started'` with `RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL`.
Class: PRE_EXISTING_FAILURE. Not fixed.

`tests/test_exchange_live_status.py` was not run. This task does not
call an exchange. It is not counted as a new pass or a new failure.

## Test matrix

| ID | Result |
| --- | --- |
| T01 Fragment missing | PASS UNAVAILABLE |
| T02 Fragment present | PASS UNKNOWN |
| T03 Policy injection | PASS not CURRENT |
| T04 Recent as_of | PASS not CURRENT |
| T05 Recent publishedAt | PASS not CURRENT |
| T06 Other domain | PASS STALE label unchanged; no new CURRENT |
| T07 Revision | PASS one increment, timestamp and equity unchanged |
| T08 Idempotence | PASS second reason does not replace the first |
| T09 Reason | PASS stored only on a real bump |
| T10 Successful observe clears reason | PASS |
| T11 Failed observe preserves invalidation | PASS on the metrics snapshot. Owner fragment is absent because observation_valid is false. |
| T12 PAPER price | PASS `PAPER_INPUT_MUTATION` |
| T13 PAPER auto entry | PASS same code. The detector does not split price from position. |
| T14 PAPER auto close | PASS same code |
| T15 PAPER manual entry | PASS reason remains, no new note |
| T16 PAPER manual close | PASS reason visible before the new note, then cleared |
| T17 PAPER emergency | PASS |
| T18 PAPER capital reset | PASS before the new note |
| T19 PAPER stop | PASS `PAPER_RUNTIME_STOP`, lifecycle STOPPED |
| T20 LIVE cache mutation | PASS |
| T21 LIVE source | PASS |
| T22 LIVE authentication | PASS |
| T23 LIVE stale | PASS |
| T24 LIVE no-op copy | PASS, including an engine-position-only change |
| T25 Producer active evidence | PASS lifecycle RUNNING, status UNKNOWN |
| T26 Producer stop evidence | PASS STOPPED, not ACTIVE |
| T27 Session restart | PASS same session keeps the reason; a new session clears it |
| T28 LIVE source projection | PASS from the cache already observed |
| T29 Owner projection | PASS |
| T30 Runtime UNKNOWN | PASS |
| T31 Runtime UNAVAILABLE | PASS |
| T32 Advisor | PASS |
| T33 Supervisor | PASS same status as advisor |
| T34 Operator 401 | PASS |
| T35 PUBLIC isolation | PASS |
| T36 No account sync | PASS |
| T37 No exchange API | PASS |
| T38 No real orders | PASS |
| T39 No MM calculation change | PASS equity, as_of, and completion timestamp unchanged by invalidation |
| T40 No new regression | PASS on the suites above. Known nine remain. Exchange file not run. |

## Acceptance matrix

| ID | Result |
| --- | --- |
| A01 CURRENT guard | PASS |
| A02 MM UNKNOWN | PASS |
| A03 MM UNAVAILABLE | PASS |
| A04 Other domain | PASS |
| A05 Invalidation reason | PASS |
| A06 Revision preservation | PASS |
| A07 PAPER mutation evidence | PASS |
| A08 LIVE cache mutation evidence | PASS |
| A09 Producer liveness | PASS for lifecycle. No new heartbeat. |
| A10 Session boundary | PASS |
| A11 LIVE source evidence | PASS for fields that already exist |
| A12 Owner snapshot | PASS |
| A13 Runtime evidence | PASS UNKNOWN, not STALE from a reason |
| A14 Advisor | PASS |
| A15 Supervisor | PASS |
| A16 Operator authentication | PASS |
| A17 PUBLIC isolation | PASS |
| A18 No account sync | PASS |
| A19 No exchange API | PASS |
| A20 No real orders | PASS |
| A21 No trading logic change | PASS |
| A22 No MM calculation change | PASS |
| A23 No new regression | PASS |
| A24 Canonical reconciliation | PASS |

## Remaining gaps

1. No periodic producer heartbeat and no accepted MM age bound. CURRENT
   stays disabled until both exist under a later policy task.
2. Reason codes do not select STALE. That judgment stays a later task.
3. An invalid observation removes the owner fragment, so the retained
   reason is not visible until a valid fragment exists again.
4. LIVE `engine.actual_position` is still not the MM cache. Closing that
   gap would require account sync, which this task does not add.
5. `tests/test_exchange_live_status.py` was not re-run.

BLOCK_REASON: none.

DEPENDENCY: F3 design `ca52a62 work-bb: design mm runtime freshness policy`.

RESUME_CONDITION: acceptance of this evidence can start. It must not
enable CURRENT or invent a TTL.

NEXT_RECOMMENDED_TASK: `BB_MM_F3_FRESHNESS_EVIDENCE_ACCEPTANCE`

This task does not start that work.
