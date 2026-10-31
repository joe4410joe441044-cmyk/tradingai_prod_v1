# BB-MM-F1.9 MM Observation Instrumentation Acceptance

TASK_ID: TRADINGAI-WORK-BB-MM-F1-OBSERVATION-INSTRUMENTATION-ACCEPTANCE-1

VERDICT: BB_MM_F1_OBSERVATION_ACCEPTANCE_PASS

Read-only acceptance of `mmObservationCompletedAt` from
`ac1f1d4dc2ab6f7d83f6377d4510465eed532a4f`. No application code was
changed. The clock stays a producer note. It does not become `CURRENT`.

## Identity

CANONICAL_HEAD: f344864344b0b99a598f674b3e2e4a367bc9fb25

ORIGIN_MAIN: f344864344b0b99a598f674b3e2e4a367bc9fb25

WORKTREE: /home/joe4410joe/tradingai_prod_v1.worktrees/ai-mm-observation-acceptance

BRANCH: test/ai-mm-observation-acceptance

BASE_COMMIT: ac1f1d4dc2ab6f7d83f6377d4510465eed532a4f

HEAD_BEFORE: ac1f1d4dc2ab6f7d83f6377d4510465eed532a4f

HEAD_AFTER: the docs-only tip of this branch, message
`work-bb: accept mm observation completion evidence`

The external report records that commit id after `git rev-parse HEAD`.

CHANGED_FILES:

- docs/ai/BB_MM_F1_OBSERVATION_INSTRUMENTATION_ACCEPTANCE.md

COMMIT: work-bb: accept mm observation completion evidence

## Canonical Reconciliation

merge-base: 39273a115637edaba42ea49bde732f1ae6436399

Main was not merged. Files that differ from this branch toward origin/main:

| Path | Class |
| --- | --- |
| Bot/engine/execution_engine.py | MAIN_ONLY |
| backend/api/money_management.py | MAIN_ONLY |
| backend/money_management/loss_execution_integration.py | MAIN_ONLY |
| backend/money_management/loss_http_api.py | MAIN_ONLY |
| backend/runtime/cycle_diagnostics.py | MAIN_ONLY |
| backend/supervisor/runtime_snapshot_adapter.py | MAIN_ONLY |
| backend/supervisor/snapshot_builder.py | MAIN_ONLY |
| frontend runtime diagnostics and dashboard CSS | MAIN_ONLY |
| tests/test_contract_quantity_projection_repair.py | MAIN_ONLY |
| tests/test_manual_cycle_diagnostics.py | MAIN_ONLY |
| tests/test_money_management_execution_entry_preview.py | MAIN_ONLY |
| tests/test_paper_trade_pipeline.py | MAIN_ONLY |

None of those paths changed on this branch between the merge-base and
`ac1f1d4`. The supervisor hunks are `_governance_payload`,
`_source_timestamp`, and `build_supervisor_snapshot`. They are not the
observation note. No CONFLICTING overlap was found.

BB_ONLY for this acceptance is the implementation commit:

- backend/money_management/loss_authoritative_runtime_metrics.py
- backend/bot_manager/bot_manager.py
- backend/bot_manager/owner_snapshot.py
- tests/test_mm_observation_completion_evidence.py
- docs/ai/BB_MM_F1_OBSERVATION_INSTRUMENTATION_IMPLEMENTATION.md

ALREADY_CANONICAL: none of the observation-note files are on origin/main.
UNKNOWN: none for the producer, owner snapshot, or runtime-evidence path.

## Producer, PAPER, and LIVE

PRODUCER_TIMESTAMP_ACCEPTANCE: PASS

`note_mm_observation_completed` is owned by
`AuthoritativeLossRuntimeMetricsState`. It runs only after `observe` or
stopped PAPER maintenance returns. The stored value is a timezone-aware
UTC datetime and the owner copy ends with `Z`. `as_of`, `readAt`, and
`publishedAt` are separate fields. Session start, restore, and peak
recovery do not call the note. Existing tests T12, T13, and T14 passed.
A session-mismatch `observe` raised `ValueError` before any clock was
stored (`revision` stayed 1, clock stayed absent).

PAPER_ACCEPTANCE: PASS

Normal PAPER requires a newly assigned `account_snapshot`,
`observation_valid=true`, a returned `observe`, and that revision.
Invalid observation and a reused snapshot do not note. Stopped PAPER
notes only when the store observation is `FRESH` and
`observation_valid` is true. `STALE` does not note. A store state with
`restoreReason` set makes `paper_account_store.observe` fail, and
`initialize_money_management_runtime_metrics` returns the restored
snapshot with no clock (`source_state=RESTORED_PERSISTED_STATE`).

LIVE_ACCEPTANCE: PASS

A complete LIVE note requires both sources
`KUCOIN_FUTURES_READ_ONLY`, `authenticated=true`, `stale=false`, and
the same copied snapshot. Balance-only, position-only, both failed,
unauthenticated, stale, and cached values without sources do not note.
The LIVE test counted zero refresh calls. No exchange client was used.

REVISION_ACCEPTANCE: PASS

Publication copies the clock only when
`mm_observation_evidence_revision` equals `revision`. Session start and
peak recovery keep the old clock and hide it. A failed note does not
replace an older clock. Matching revisions do not set `CURRENT`.

## Downstream

OWNER_SNAPSHOT_ACCEPTANCE: PASS

`_held_money_management` copies `mmObservationCompletedAt`,
`inputCompleteness`, `inputScope`, and `evidenceRevision` only on a
revision match. Equity and position size stay the observed numbers.
`publishedAt` in the publication test is `1999-01-01T00:00:00Z` and is
not the completion clock. `snapshot()` does not refresh an account or
evaluate risk. JSON serialization of the fragment passed.

RUNTIME_EVIDENCE_ACCEPTANCE: PASS

`_judge` is unchanged. A published fragment with no
`freshnessPolicy` is `UNKNOWN`. A missing fragment is `UNAVAILABLE`.
The completion clock is inside `runtimeValues` and does not change
`runtimeStatus`. No domain in the checked document was `CURRENT`.

ADVISOR_ACCEPTANCE: PASS

SUPERVISOR_ACCEPTANCE: PASS

Both callers use `load_shared_operator_context` on the same owner
document. Acceptance execution compared the two attachments. Money
Management `runtimeStatus` was `UNKNOWN` on both.
`runtimeValues` were equal, including `mmObservationCompletedAt`.
`authority` was `NONE` and `tradingControl` was `FORBIDDEN` on both.
No supervisor evaluation was started.

SECURITY_ACCEPTANCE: PASS

`/api/ai-context/operator` without a session returned 401.
`PUBLIC_ENDPOINT_ENABLED` is false. The public view built from the
owner document did not contain `mmObservationCompletedAt` or
`runtimeEvidence`. Existing owner-snapshot tests that scrub secrets
passed in this run. No live credential was used.

## Baseline Failure Comparison

Same test set as BB-MM-F1.8, executed on this worktree at `ac1f1d4`.

TEST_RESULTS: 315 passed, 9 failed, 53 subtests passed.

The nine failures were also executed on a detached worktree at the
parent `08b668a23f1504e753e21d2fc762bd5da074abc2`. That worktree was
removed after the comparison. `git diff 08b668a ac1f1d4` does not touch
the three failing test modules, the execution handoff path, or
`risk_percent_authority.py`.

| TEST_ID | TEST_NAME | FAILURE_SIGNATURE | BASELINE_SIGNATURE | CURRENT_SIGNATURE | SAME_OR_CHANGED | RELATED_TO_BB_MM_F1_8 | CLASS |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F01 | test_paper_buy_runtime_order_fill_close_account_history_and_dashboard | handoffExecuted is False at test_paper_trade_pipeline.py:111 | assert False is True | assert False is True | SAME | NO | PRE_EXISTING_FAILURE |
| F02 | test_paper_sell_signal_creates_short_order_and_fill | actual_position is None at line 185 | TypeError NoneType not subscriptable | TypeError NoneType not subscriptable | SAME | NO | PRE_EXISTING_FAILURE |
| F03 | test_paper_order_never_reaches_exchange_when_global_config_is_live | actual_position is None at line 206 | TypeError NoneType not subscriptable | TypeError NoneType not subscriptable | SAME | NO | PRE_EXISTING_FAILURE |
| F04 | test_fresh_stopped_paper_is_available_complete_and_current_identity | metrics.is_complete is false | AssertionError False is not true | AssertionError False is not true | SAME | NO | PRE_EXISTING_FAILURE |
| F05 | test_stale_store_reports_stale | read status INCONSISTENT, expected STALE | INCONSISTENT != STALE | INCONSISTENT != STALE | SAME | NO | PRE_EXISTING_FAILURE |
| F06 | test_stop_boundary_ws_callback_never_overwrites_active_mm_authority | start status error | assert error == started | assert error == started | SAME | NO | PRE_EXISTING_FAILURE |
| F07 | test_run_boundary_ws_callback_still_observes_when_authority_active | start status error | assert error == started | assert error == started | SAME | NO | PRE_EXISTING_FAILURE |
| F08 | test_session_1_stop_2_stop_3_start_recovers_with_fresh_baseline | start reason RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL | same reason, error == started | same reason, error == started | SAME | NO | PRE_EXISTING_FAILURE |
| F09 | test_monitoring_start_allowed_with_incomplete_pre_runtime_baseline | start reason RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL | same reason, error == started | same reason, error == started | SAME | NO | PRE_EXISTING_FAILURE |

F01 stops in `process_execution_runtime` before Money Management
observation. F02 and F03 follow that failed handoff, so
`actual_position` stays `None`. F04 and F05 are the existing stopped
FLAT result: position `None` leaves `observation_valid` false, so the
metrics are incomplete and the stale reader sees `INCONSISTENT` rather
than `STALE`. F06 through F09 fail inside `BotManager.start` because
the fixture `risk_percent` is `1` and the canonical MM risk is `7.00`,
which raises `RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL`. That return
happens before an observation note. Acceptance execution printed that
reason for the same start fixture.

TEST_FAILURES: the nine rows above. No NEW_REGRESSION. No UNVERIFIED row.

Required checks T01 through T30 are covered by
`tests/test_mm_observation_completion_evidence.py` plus this comparison
and the canonical diff. No new test file was added and no existing test
was edited.

## Acceptance Matrix

| Item | Result |
| --- | --- |
| A01 Producer Timestamp | PASS |
| A02 PAPER Normal Observation | PASS |
| A03 PAPER Stopped Observation | PASS |
| A04 PAPER Failure Handling | PASS |
| A05 LIVE Complete Observation | PASS |
| A06 LIVE Partial Rejection | PASS |
| A07 LIVE Authentication | PASS |
| A08 Revision Consistency | PASS |
| A09 Session / Restore | PASS |
| A10 Peak Recovery | PASS |
| A11 Owner Snapshot | PASS |
| A12 Runtime Evidence | PASS |
| A13 Advisor Context | PASS |
| A14 Supervisor Context | PASS |
| A15 Operator Authentication | PASS |
| A16 Public Isolation | PASS |
| A17 JSON Safety | PASS |
| A18 Null / Zero / False | PASS |
| A19 No False CURRENT | PASS |
| A20 No MM Calculation Change | PASS |
| A21 No Execution Authority Change | PASS |
| A22 No Account Sync | PASS |
| A23 No Real Orders | PASS |
| A24 Baseline Failure Comparison | PASS |
| A25 No New Regression | PASS |
| A26 Canonical Reconciliation | PASS |

## Remaining

REMAINING_GAPS:

- Stopped FLAT PAPER still has `observation_valid=false` when the store
  position is `None`. That is the pre-existing F04 and F05 behavior.
  The completion note correctly stays absent there.
- Position open, position update, mode identity, and LIVE cache lag are
  still not an invalidation proof. `CURRENT` stays unavailable.
- Main-only execution preview and supervisor snapshot edits were not
  integrated.

BLOCK_REASON: NONE

DEPENDENCY: none for the next design task. Freshness policy is still
not selected.

RESUME_CONDITION: start a new task for invalidation design. Do not
promote this clock to `CURRENT`. Do not merge main from this branch.

NEXT_RECOMMENDED_TASK: BB_MM_F2_INVALIDATION_INSTRUMENTATION_DESIGN

The next task was not started. Canonical main was not changed. No
merge, push, deploy, restart, runtime mutation, or real order was
performed.
