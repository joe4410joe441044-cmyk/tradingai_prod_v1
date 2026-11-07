# BB-MM-F2 Invalidation Instrumentation Acceptance

TASK_ID: TRADINGAI-WORK-BB-MM-F2-INVALIDATION-INSTRUMENTATION-ACCEPTANCE-1

VERDICT: BB_MM_F2_INVALIDATION_ACCEPTANCE_PASS

CANONICAL_HEAD: f344864344b0b99a598f674b3e2e4a367bc9fb25

ORIGIN_MAIN: f344864344b0b99a598f674b3e2e4a367bc9fb25

WORKTREE: /home/joe4410joe/tradingai_prod_v1.worktrees/ai-mm-invalidation-acceptance

BRANCH: test/ai-mm-invalidation-acceptance

BASE_COMMIT: 004de5fddf81932a036549685455017af3b53403

HEAD_BEFORE: 004de5fddf81932a036549685455017af3b53403

HEAD_AFTER: the docs-only commit on this branch whose message is `work-bb: accept mm observation invalidation`. The external report records that commit hash after the commit. This file does not contain its own hash.

CHANGED_FILES:

- docs/ai/BB_MM_F2_INVALIDATION_INSTRUMENTATION_ACCEPTANCE.md

COMMIT: work-bb: accept mm observation invalidation

DESIGN_COMMIT: 06550215aa3b0354946b7be0bc315090e8788d1c

IMPLEMENTATION_COMMIT: 004de5fddf81932a036549685455017af3b53403

IMPLEMENTATION_VERDICT: BB_MM_F2_INVALIDATION_IMPLEMENTATION_PASS

This acceptance pass did not change application code.

## PRODUCER_ACCEPTANCE

`tests/test_mm_observation_invalidation.py` T01–T07 passed on `004de5f`.

`invalidate_mm_observation_evidence` advances revision only when a publishable completion exists. The first call increments revision by one. The second call does not. Evidence revision, the timestamp, `as_of`, equity, peak, drawdown, scope, and completeness stay on the stored note. A state with no completion does not increment.

## PAPER_ACCEPTANCE

T08–T17 passed.

Auto entry, auto close, and price update invalidate after the detected PAPER input change and before observe. A successful observe then publishes a new completion. An unchanged price tick does not invalidate.

PAPER manual entry invalidates after `MANUAL_ENTRY_FILLED` and does not call observe. A rejected entry leaves the revision and the published completion in place.

A confirmed manual close invalidates before observe. A rejected close does not invalidate.

PAPER emergency flatten invalidates when the signature changes, before observe. Capital reset hides the pre-reset completion at `_publish_context_snapshot`. Stop hides the completion, keeps the old timestamp, and does not write a new one.

T32 passed: after invalidation, a raised observe leaves the old timestamp unpublished.

## LIVE_CACHE_ACCEPTANCE

T18–T26 passed.

Balance, positions, partial source, exchange source, authentication, and stale changes each advance revision once and hide the completion. Loading-only refresh advances revision once for the later empty commit, not for the loading copy. Generation-only rewrite and an identical fresh copy do not advance revision.

T27 passed. A LIVE engine position change and a confirmed LIVE manual entry leave the revision and the published completion unchanged. `refresh_calls` stays 0. T45 and T46 passed: invalidation does not call account refresh and does not call `place_order`, `create_order`, or `submit_order`.

## MODE_TRANSITION_ACCEPTANCE

T28–T31 passed.

`set_mode` to live leaves the metrics revision and the published evidence revision unchanged. `begin_runtime_session` and peak recovery unpublish the old completion through their existing revision increment and do not call `invalidate_mm_observation_evidence`. Restore on a fresh state writes no completion timestamp, and a following invalidation call does not increment. The implementation commit does not modify `backend/routers/mode.py` or `Bot/engine/execution_engine.py`. This acceptance does not modify them either.

## REVISION_CONSISTENCY

T34 and T35 passed. A matching revision publishes `mmObservationCompletedAt`, `inputCompleteness`, `inputScope`, and `evidenceRevision`. After invalidation, evidence revision differs from metrics revision and those four names are absent. T08, T09, and T13 show a later successful observe publishing a new completion. T32 and T33 show a failed or partial observe leaving the old completion unpublished.

## OWNER_SNAPSHOT_ACCEPTANCE

T36 passed. Before invalidation the completion names are present. After invalidation the numeric fields and `producerObservedAt` remain, and the completion names are absent. `owner_snapshot.py` was not modified by this acceptance. The implementation commit did not modify it either.

## RUNTIME_EVIDENCE_ACCEPTANCE

T37 and T38 passed. A remaining fragment is `UNKNOWN`. A missing fragment is `UNAVAILABLE`. The status is not `CURRENT`. `freshnessPolicy` is absent. `runtime_evidence.py` was not modified.

## ADVISOR_SUPERVISOR_ACCEPTANCE

T39 and T40 passed. Both callers use `load_shared_operator_context` on the same owner document. After invalidation, `mmObservationCompletedAt` is absent from the advisor block, both money-management statuses are `UNKNOWN`, `authority` is `NONE`, and `tradingControl` is `FORBIDDEN`.

## SECURITY_ACCEPTANCE

T41 passed. `PUBLIC_ENDPOINT_ENABLED` is false. `/api/ai-context/operator` without a session returns 401, and the route depends on `require_operator_session`.

T42 passed. The public view does not contain `mmObservationCompletedAt`, `evidenceRevision`, or `runtimeEvidence`.

The tests use fixtures and do not print credentials. No production credential was supplied to the test run.

## TEST_COMMANDS

Primary related set, in the acceptance worktree:

`python3 -m pytest tests/test_mm_observation_invalidation.py tests/test_mm_observation_completion_evidence.py tests/test_money_management_loss_authoritative_runtime_metrics.py tests/test_mm_stopped_paper_recovery_metrics.py tests/test_mm_baseline_session_transition.py tests/test_mm_runtime_session_rehydration.py tests/test_mm_live_peak_authority_recovery.py tests/test_mm_live_peak_authority_separation.py tests/test_paper_capital_reset.py tests/test_paper_trade_pipeline.py tests/test_ai_context_owner_snapshot.py tests/test_ai_context_owner_wiring.py tests/test_ai_context_owner_cache.py tests/test_ai_context_owner_integration.py tests/test_ai_context_runtime_evidence.py tests/test_ai_context_runtime_producer.py tests/test_ai_context_snapshot_copy.py tests/test_ai_advisor_mm_authority_preservation.py tests/test_paper_mm_capital_authority.py tests/test_bot_manager.py tests/test_account_status_financial_contract.py tests/test_account_view_dual_projection.py tests/test_current_position_view.py -q --tb=line`

Exchange comparison, run separately in this worktree and in the design worktree at `06550215aa3b0354946b7be0bc315090e8788d1c`:

`python3 -m pytest tests/test_exchange_live_status.py --tb=no -q`

The nine known failures were also run alone in the design worktree.

## TEST_RESULTS

Primary related set: 459 passed, 9 failed, 55 subtests passed.

`tests/test_mm_observation_invalidation.py` collected 46 tests. None of those 46 are in the failure list, so T01–T46 passed.

`tests/test_bot_manager.py` passed inside the primary set.

Exchange file on this commit: 85 failed, 217 passed, 286 subtests passed.

Exchange file on design commit `06550215aa3b0354946b7be0bc315090e8788d1c`: 85 failed, 217 passed, 286 subtests passed. The sorted failure identifiers, including subtest parameters, are identical.

## TEST_FAILURES

The nine failures in the primary set:

| ID | Test | Signature on 004de5f |
| --- | --- | --- |
| F01 | `test_paper_buy_runtime_order_fill_close_account_history_and_dashboard` | `assert False is True` at `test_paper_trade_pipeline.py:111` (`handoffExecuted`) |
| F02 | `test_paper_sell_signal_creates_short_order_and_fill` | `TypeError: 'NoneType' object is not subscriptable` at line 185 |
| F03 | `test_paper_order_never_reaches_exchange_when_global_config_is_live` | `TypeError: 'NoneType' object is not subscriptable` at line 206 |
| F04 | `test_fresh_stopped_paper_is_available_complete_and_current_identity` | `AssertionError: False is not true` |
| F05 | `test_stale_store_reports_stale` | `INCONSISTENT != STALE` |
| F06 | `test_stop_boundary_ws_callback_never_overwrites_active_mm_authority` | `assert 'error' == 'started'` at line 211 |
| F07 | `test_run_boundary_ws_callback_still_observes_when_authority_active` | `assert 'error' == 'started'` at line 271 |
| F08 | `test_session_1_stop_2_stop_3_start_recovers_with_fresh_baseline` | start result reason `RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL` |
| F09 | `test_monitoring_start_allowed_with_incomplete_pre_runtime_baseline` | start result reason `RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL` |

F06 and F07 stop at `manager.start`. A direct call of that same fixture printed `reason=RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL`, `status=error`, `success=False`, `completed=False`, `stateUnknown=True`. The same call on the design worktree printed the same five fields.

## KNOWN_FAILURE_CLASSIFICATION

The same nine tests failed on design commit `06550215aa3b0354946b7be0bc315090e8788d1c` with the same assertion text and the same line numbers. F06's direct start reason on that commit is also `RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL`.

| ID | Class |
| --- | --- |
| F01 | PRE_EXISTING_FAILURE |
| F02 | PRE_EXISTING_FAILURE |
| F03 | PRE_EXISTING_FAILURE |
| F04 | PRE_EXISTING_FAILURE |
| F05 | PRE_EXISTING_FAILURE |
| F06 | PRE_EXISTING_FAILURE |
| F07 | PRE_EXISTING_FAILURE |
| F08 | PRE_EXISTING_FAILURE |
| F09 | PRE_EXISTING_FAILURE |

Exchange live status, compared by running the whole file in each worktree:

Representative signatures, identical on both commits:

- `test_bootstrap_start_stop_creates_normal_durable_snapshot`: `'error' != 'started'`, result reason `RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL`
- `test_emergency_retry_engine_none_without_authoritative_snapshot_fails`: `'FINAL_STATE_UNKNOWN' != 'SNAPSHOT_SOURCE_UNKNOWN'`

The full sorted identifier lists both contain 85 entries and `diff` between them is empty. Those 85 are `PRE_EXISTING_FAILURE` relative to the design commit. They include 19 whole tests and the parameterized subtests under `test_auto_trade_off_allowed_when_emergency_locked`, `test_auto_trade_off_allowed_when_loop_off`, `test_emergency_retry_rejects_malformed_modes`, `test_emergency_retry_rejects_stale_stopped_paper_unsafe_states`, `test_emergency_stopped_paper_requires_authoritative_safety`, `test_restart_durable_authority_invalid_evidence_fails_closed`, `test_restart_rebound_durable_freshness_boundaries`, `test_stopped_paper_durable_snapshot_invalid_inputs_fail_closed`, `test_stopped_paper_open_order_unknown_or_remaining_blocks_success`, and `test_stopped_paper_snapshot_freshness_fail_closed`.

## NEW_REGRESSIONS

None. The invalidation tests passed. The primary related set added no failure beyond F01–F09. The exchange failure set matches the design commit identifier for identifier.

## TEST_MATRIX

| ID | Result |
| --- | --- |
| T01 Producer First Invalidation | PASS |
| T02 Producer Second Invalidation | PASS |
| T03 Producer No Active Evidence | PASS |
| T04 Producer Revision Mismatch | PASS |
| T05 Timestamp Preservation | PASS |
| T06 as_of Preservation | PASS |
| T07 MM Metrics Preservation | PASS |
| T08 PAPER Auto Entry | PASS |
| T09 PAPER Auto Close | PASS |
| T10 PAPER Price Update | PASS |
| T11 PAPER Manual Entry | PASS |
| T12 PAPER Manual Entry Rejection | PASS |
| T13 PAPER Manual Close | PASS |
| T14 PAPER Manual Close Rejection | PASS |
| T15 PAPER Emergency Flatten | PASS |
| T16 PAPER Capital Reset | PASS |
| T17 PAPER Stop | PASS |
| T18 LIVE Balance Change | PASS |
| T19 LIVE Position Change | PASS |
| T20 LIVE Partial Cache Change | PASS |
| T21 LIVE Source Change | PASS |
| T22 LIVE Authentication Change | PASS |
| T23 LIVE Stale Change | PASS |
| T24 LIVE Loading-only | PASS |
| T25 LIVE Generation-only | PASS |
| T26 LIVE Identical Copy | PASS |
| T27 LIVE Engine Position-only | PASS |
| T28 Mode Config-only | PASS |
| T29 Session Start | PASS |
| T30 Restore | PASS |
| T31 Peak Recovery | PASS |
| T32 Observation Failure | PASS |
| T33 Partial Observation | PASS |
| T34 Revision Match Publication | PASS |
| T35 Revision Mismatch Suppression | PASS |
| T36 Owner Snapshot | PASS |
| T37 Runtime Evidence UNKNOWN | PASS |
| T38 Missing Fragment UNAVAILABLE | PASS |
| T39 Advisor | PASS |
| T40 Supervisor | PASS |
| T41 Operator Authentication | PASS |
| T42 Public Isolation | PASS |
| T43 Null / Zero / False | PASS |
| T44 MM Calculation Preservation | PASS |
| T45 No Account Sync | PASS |
| T46 No Real Orders | PASS |

## ACCEPTANCE_MATRIX

| ID | Item | Result |
| --- | --- | --- |
| A01 | Producer Invalidation | PASS |
| A02 | One-time Revision Increment | PASS |
| A03 | Timestamp Preservation | PASS |
| A04 | as_of Preservation | PASS |
| A05 | MM Metrics Preservation | PASS |
| A06 | PAPER Auto Entry | PASS |
| A07 | PAPER Auto Close | PASS |
| A08 | PAPER Price Update | PASS |
| A09 | PAPER Manual Entry | PASS |
| A10 | PAPER Manual Close | PASS |
| A11 | PAPER Emergency Flatten | PASS |
| A12 | PAPER Capital Reset | PASS |
| A13 | PAPER Stop | PASS |
| A14 | LIVE Balance Cache | PASS |
| A15 | LIVE Position Cache | PASS |
| A16 | LIVE Partial Cache | PASS |
| A17 | LIVE Source Change | PASS |
| A18 | LIVE Authentication Change | PASS |
| A19 | LIVE Stale Change | PASS |
| A20 | LIVE NO-OP Cases | PASS |
| A21 | Mode Transition | PASS |
| A22 | Revision Consistency | PASS |
| A23 | Observation Failure Safety | PASS |
| A24 | Owner Snapshot | PASS |
| A25 | Runtime Evidence | PASS |
| A26 | Advisor / Supervisor | PASS |
| A27 | Operator Authentication | PASS |
| A28 | Public Isolation | PASS |
| A29 | No False CURRENT | PASS |
| A30 | No MM Calculation Change | PASS |
| A31 | No Execution Authority Change | PASS |
| A32 | No Account Sync | PASS |
| A33 | No Real Orders | PASS |
| A34 | No New Regression | PASS |
| A35 | Canonical Reconciliation | PASS |

## Canonical reconciliation

hostname: `vmi3480936`

merge-base with `origin/main`: `39273a115637edaba42ea49bde732f1ae6436399`

`git diff --name-status HEAD...origin/main` does not list `loss_authoritative_runtime_metrics.py`, `bot_manager.py`, or `tests/test_mm_observation_invalidation.py`. Main did not edit those paths after the merge-base. The content difference of those three paths against `origin/main` is the BB branch's own history, including the implementation commit. There is no same-function edit from main to reconcile. No merge and no cherry-pick was performed.

The sixteen `MAIN_ONLY` paths remain `Bot/engine/execution_engine.py`, `backend/api/money_management.py`, `backend/money_management/loss_execution_integration.py`, `backend/money_management/loss_http_api.py`, `backend/runtime/cycle_diagnostics.py`, `backend/supervisor/runtime_snapshot_adapter.py`, `backend/supervisor/snapshot_builder.py`, the trading-cycle frontend files, `frontend/src/styles/dashboard.css`, and the four listed tests. They were not edited in this acceptance worktree.

Canonical HEAD stayed `f344864344b0b99a598f674b3e2e4a367bc9fb25`.

## REMAINING_GAPS

PAPER manual entry still leaves fragment numbers at the previous observe until a later cycle observe. The completion clock is unpublished in that interval.

LIVE engine position and LIVE emergency flatten still do not refresh `real_account_snapshot`. The completion describes the cache.

F01–F09 and the 85 exchange-status failures remain. They match the design commit and were not fixed.

BLOCK_REASON: none

DEPENDENCY: implementation commit `004de5fddf81932a036549685455017af3b53403`

RESUME_CONDITION: start the freshness-policy design from this acceptance commit. Do not start it in this pass.

NEXT_RECOMMENDED_TASK: BB_MM_F3_FRESHNESS_POLICY_DESIGN
