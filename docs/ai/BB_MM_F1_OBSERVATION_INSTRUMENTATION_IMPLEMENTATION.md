# BB-MM-F1.8 MM Observation Completion Evidence

TASK_ID: TRADINGAI-WORK-BB-MM-F1-OBSERVATION-INSTRUMENTATION-IMPLEMENTATION-1

VERDICT: BB_MM_F1_OBSERVATION_INSTRUMENTATION_PASS

The producer records `mmObservationCompletedAt` only after a qualifying
observation returns. Owner publication copies that clock only when its stored
revision still equals the metrics revision. Runtime evidence stays `UNKNOWN`.
No freshness policy was added, and no status becomes `CURRENT`.

## Canonical Reconciliation

CANONICAL_HEAD: f344864344b0b99a598f674b3e2e4a367bc9fb25

ORIGIN_MAIN: f344864344b0b99a598f674b3e2e4a367bc9fb25

merge-base of this branch and origin/main:
39273a115637edaba42ea49bde732f1ae6436399

Main-only files since that merge-base include loss HTTP preview,
`execution_engine.py`, cycle diagnostics, supervisor snapshot helpers, and
frontend diagnostics. Those files are not the producer, owner snapshot, or
runtime-evidence path used here. They were not merged and not edited.

`backend/bot_manager/bot_manager.py`,
`backend/bot_manager/owner_snapshot.py`, and
`backend/money_management/loss_authoritative_runtime_metrics.py` have no
main-only edits since the merge-base. There is no function-level conflict
to resolve before this note.

## Worktree

WORKTREE: /home/joe4410joe/tradingai_prod_v1.worktrees/ai-mm-observation-instrumentation

BRANCH: feature/ai-mm-observation-instrumentation

BASE_COMMIT: 08b668a23f1504e753e21d2fc762bd5da074abc2

HEAD_BEFORE: 08b668a23f1504e753e21d2fc762bd5da074abc2

HEAD_AFTER: the tip commit on this branch whose message is
`work-bb: add mm observation completion evidence`

The external report records that commit id after `git rev-parse HEAD`.

## Producer

PRODUCER_WRITE_POINT:

`AuthoritativeLossRuntimeMetricsState.note_mm_observation_completed`

The note runs only after `observe` or `observe_stopped_paper_maintenance`
has returned. It stores a timezone-aware UTC datetime,
`inputCompleteness=COMPLETE`, `inputScope`, and the metrics revision from
that return. It does not change equity, drawdown, peak, `as_of`, or
`revision`.

Callers:

- `BotManager._observe_money_management_runtime_metrics`, after `observe`
- `BotManager.initialize_money_management_runtime_metrics`, after a fresh
  stopped PAPER maintenance observation

The published JSON name is `mmObservationCompletedAt`. The value uses the
existing UTC form `YYYY-MM-DDTHH:MM:SSZ`. `as_of`, `readAt`, and
`publishedAt` are not copied into it.

PAPER_SUCCESS_GATE:

1. `_capture_account_snapshot` assigned a new `account_snapshot` object.
2. `observation_valid` is true.
3. `observe` returned.
4. `note_mm_observation_completed` can store that snapshot's revision.

A capture exception returns the previous object, so the clock is not
written. An invalid observation is not written. Stopped PAPER uses a
separate capture: `paper_account_store.observe` returned `freshness=FRESH`,
then `observe_stopped_paper_maintenance` returned with
`observation_valid` true. A `STALE` store observation does not note.
Stopped FLAT maintenance still leaves `observation_valid` false in the
existing metrics rules, so it does not note. That validity rule was not
changed.

LIVE_SUCCESS_GATE:

The snapshot copied into `observe` must already show both
`balanceSource` and `positionSource` as `KUCOIN_FUTURES_READ_ONLY`,
`authenticated` true, `stale` false, at least one balance field, and a
non-null `positions` value. Balance and position values without those
source fields are not a full sync. Balance-only, position-only, both
failed, unauthenticated, and stale do not note. This path does not call
the exchange and does not call `_refresh_real_account_snapshot`.

REVISION_CONSISTENCY:

The note stores `mm_observation_evidence_revision` equal to the revision
just returned. Owner publication emits `mmObservationCompletedAt`,
`inputCompleteness`, `inputScope`, and `evidenceRevision` only when that
stored revision equals `snapshot.revision`. Session start, restore, and
peak recovery move revision or `as_of` and do not call the note. An older
clock therefore stays unpublished. Revision equality is not `CURRENT`.

OWNER_SNAPSHOT_MAPPING:

`_held_money_management` reads `snapshot()` and adds the four names only
on a revision match. Existing numeric fields are copied as before.
`producerObservedAt` remains `as_of`. `publishedAt` stays the publication
clock. `freshnessPolicy` is not added. `freshness` stays `UNKNOWN`.

RUNTIME_EVIDENCE_MAPPING:

`runtime_evidence._judge` is unchanged. A fragment with
`producerObservedAt` and no money-management freshness policy is
`UNKNOWN`. A missing fragment is `UNAVAILABLE`. The new names travel
inside `runtimeValues`. They do not change `runtimeStatus`.

CURRENT_STATUS: UNKNOWN

FRESHNESS_POLICY: not added

## Tests

Command:

`python3 -m pytest` on the new evidence file plus the related metrics,
owner, runtime-evidence, advisor, supervisor, authentication, bot manager,
and baseline files.

Result of that run: 315 passed, 9 failed, 53 subtests passed.

The new file `tests/test_mm_observation_completion_evidence.py` passed,
including T01 through T25.

TEST_FAILURES, all reproduced on the unmodified base commit
`08b668a23f1504e753e21d2fc762bd5da074abc2`:

- `tests/test_paper_trade_pipeline.py::test_paper_buy_runtime_order_fill_close_account_history_and_dashboard`
- `tests/test_paper_trade_pipeline.py::test_paper_sell_signal_creates_short_order_and_fill`
- `tests/test_paper_trade_pipeline.py::test_paper_order_never_reaches_exchange_when_global_config_is_live`
- `tests/test_mm_stopped_paper_recovery_metrics.py::StoppedPaperRecoveryMetricsTests::test_fresh_stopped_paper_is_available_complete_and_current_identity`
- `tests/test_mm_stopped_paper_recovery_metrics.py::StoppedPaperRecoveryMetricsTests::test_stale_store_reports_stale`
- `tests/test_mm_baseline_session_transition.py::test_stop_boundary_ws_callback_never_overwrites_active_mm_authority`
- `tests/test_mm_baseline_session_transition.py::test_run_boundary_ws_callback_still_observes_when_authority_active`
- `tests/test_mm_baseline_session_transition.py::test_session_1_stop_2_stop_3_start_recovers_with_fresh_baseline`
- `tests/test_mm_baseline_session_transition.py::test_monitoring_start_allowed_with_incomplete_pre_runtime_baseline`

The paper pipeline failures stop before observation, on
`handoffExecuted`. The baseline failures return
`RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL`. The stopped FLAT maintenance
failure is the existing `observation_valid` false result when position is
`None`. None of these nine were introduced by the completion note.

## Acceptance

| Item | Result |
| --- | --- |
| A01 Producer Timestamp | PASS |
| A02 PAPER Success Gate | PASS |
| A03 PAPER Failure Gate | PASS |
| A04 LIVE Full Observation Gate | PASS |
| A05 LIVE Partial Rejection | PASS |
| A06 Revision Consistency | PASS |
| A07 Session / Restore Safety | PASS |
| A08 Peak Recovery Safety | PASS |
| A09 Owner Snapshot Mapping | PASS |
| A10 Runtime Evidence Mapping | PASS |
| A11 Advisor Regression | PASS |
| A12 Supervisor Regression | PASS |
| A13 Authentication | PASS |
| A14 Public Isolation | PASS |
| A15 JSON Safety | PASS |
| A16 No False CURRENT | PASS |
| A17 No MM Calculation Change | PASS |
| A18 No Execution Authority Change | PASS |
| A19 No Account Sync | PASS |
| A20 No Production Mutation | PASS |
| A21 No Real Orders | PASS |
| A22 Test Regression | PASS |
| A23 Canonical Reconciliation | PASS |

A22 is PASS because the nine failures above also fail on the base commit.
This note did not add a failing test.

## Remaining

CHANGED_FILES:

- backend/money_management/loss_authoritative_runtime_metrics.py
- backend/bot_manager/bot_manager.py
- backend/bot_manager/owner_snapshot.py
- tests/test_mm_observation_completion_evidence.py
- docs/ai/BB_MM_F1_OBSERVATION_INSTRUMENTATION_IMPLEMENTATION.md

COMMIT: work-bb: add mm observation completion evidence

REMAINING_GAPS:

- Stopped FLAT PAPER maintenance still has `observation_valid` false when
  the store position is `None`, so it does not receive a completion clock.
- Position open, position update, mode identity, and LIVE cache lag remain
  unknown. The clock is not proof that later inputs are unchanged.
- `CURRENT` remains unavailable. No freshness policy was selected.

BLOCK_REASON: NONE

DEPENDENCY: none for acceptance of this clock. Invalidation and freshness
stay separate.

RESUME_CONDITION: start the acceptance task only. Do not promote freshness
and do not merge main from this work.

NEXT_RECOMMENDED_TASK: BB_MM_F1_OBSERVATION_INSTRUMENTATION_ACCEPTANCE

The next task was not started. Canonical main was not changed. No merge,
push, deploy, restart, runtime mutation, or real order was performed.
