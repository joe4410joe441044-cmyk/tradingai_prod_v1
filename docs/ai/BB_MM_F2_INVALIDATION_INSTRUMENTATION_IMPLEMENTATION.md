# BB-MM-F2 Invalidation Instrumentation Implementation

TASK_ID: TRADINGAI-WORK-BB-MM-F2-INVALIDATION-INSTRUMENTATION-IMPLEMENTATION-1

VERDICT: BB_MM_F2_INVALIDATION_IMPLEMENTATION_PASS

CANONICAL_HEAD: f344864344b0b99a598f674b3e2e4a367bc9fb25

ORIGIN_MAIN: f344864344b0b99a598f674b3e2e4a367bc9fb25

WORKTREE: /home/joe4410joe/tradingai_prod_v1.worktrees/ai-mm-invalidation-implementation

BRANCH: feature/ai-mm-invalidation-instrumentation

BASE_COMMIT: 06550215aa3b0354946b7be0bc315090e8788d1c

HEAD_BEFORE: 06550215aa3b0354946b7be0bc315090e8788d1c

HEAD_AFTER: the commit on this branch whose message is `work-bb: implement mm observation invalidation`. The external report records that commit hash after the commit. This file does not contain its own hash.

CHANGED_FILES:

- backend/money_management/loss_authoritative_runtime_metrics.py
- backend/bot_manager/bot_manager.py
- tests/test_mm_observation_invalidation.py
- docs/ai/BB_MM_F2_INVALIDATION_INSTRUMENTATION_IMPLEMENTATION.md

COMMIT: work-bb: implement mm observation invalidation

DESIGN_VERDICT: BB_MM_F2_INVALIDATION_DESIGN_PASS

DESIGN_COMMIT: 06550215aa3b0354946b7be0bc315090e8788d1c

F1_IMPLEMENTATION_COMMIT: ac1f1d4dc2ab6f7d83f6377d4510465eed532a4f

F1_ACCEPTANCE_COMMIT: f6ba7bfb7447d2bed3d6a84061303947e8d0c157

## PRODUCER_INVALIDATION_METHOD

`AuthoritativeLossRuntimeMetricsState.invalidate_mm_observation_evidence` advances `_revision` by one only when a completion is currently publishable under the F1 contract:

- `mm_observation_completed_at` is present
- `mm_observation_evidence_revision == _revision`
- `observation_valid` is true
- completeness is `COMPLETE`
- scope is `PAPER_ENGINE_ACCOUNT` or `LIVE_ACCOUNT_CACHE`

The method leaves `as_of`, equity, peak, drawdown, the timestamp, the evidence revision, the scope, and the completeness unchanged. A second call sees the revision mismatch and does not increment. It does not delete the timestamp and it does not create a new one. No new revision field was added.

`BotManager._invalidate_mm_observation_evidence` is the only caller wrapper. `owner_snapshot.py` is unchanged. The existing `evidenceRevision == revision` check omits `mmObservationCompletedAt`, `inputCompleteness`, `inputScope`, and `evidenceRevision`.

## PAPER_INVALIDATION_RESULTS

PAPER market updates go through `on_update` inside `BotManager.start`. After `ExecutionEngine.on_price` returns, `_invalidate_mm_observation_if_paper_inputs_changed` compares the MM signature, `latest_price`, and `unrealized_pnl`. A PAPER change invalidates before the existing authority check and the existing observe. A LIVE engine change takes the no-op branch.

`_manual_entry_locked` invalidates only after a confirmed PAPER `MANUAL_ENTRY_FILLED`. It does not observe. A rejected entry does not invalidate. A confirmed LIVE entry does not invalidate, because that path changes `engine.actual_position` and not the account cache.

`_manual_close_locked` invalidates after a confirmed close and before `_finalize_manual_close_money_management`. A rejected close returns before that call.

The PAPER branch of `_run_emergency_orchestrator_locked` invalidates when the before/after signature differs, then calls the existing observe. The LIVE emergency branch does not invalidate for an engine position change.

`reset_paper_capital` compares the PAPER MM projection and, when it changed, invalidates before `_publish_context_snapshot`. The capital calculation is unchanged. The publish that follows no longer carries the pre-reset completion.

`_stop_locked` invalidates when `_capture_account_snapshot` replaces `account_snapshot`, and again when the engine is removed. The second call is a no-op after the first. Stop does not add an observe. The stopped PAPER `observation_valid` rule is unchanged.

## LIVE_CACHE_INVALIDATION_RESULTS

`_assign_real_account_snapshot` compares balance, equity, available balance, positions, `balanceSource`, `positionSource`, `authenticated`, and `stale`. It invalidates only when that projection changes.

The comparison is used by:

- `_prepare_real_account_snapshot_for_exchange`
- the loading assignment and the successful `commit` inside `_refresh_real_account_snapshot`
- `_mark_real_account_stale_if_needed`

A loading-only copy, a generation-only rewrite, and an identical copy do not increment. A balance change, a positions change, a partial source change, an authentication change, a stale change, and an exchange source replacement do increment. No exchange client and no account sync were added.

## MODE_TRANSITION_RESULTS

`/set_mode` was not modified. A config-only mode write does not move the metrics revision and does not call the new method. `begin_runtime_session`, `restore`, and `apply_validated_peak_recovery` still move revision themselves and still do not write a completion timestamp. Those three paths do not call `invalidate_mm_observation_evidence`.

## REVISION_CONSISTENCY

Invalidation increments `_revision` once and leaves `mm_observation_evidence_revision` on the old note. A later successful observe still uses the F1 note gate and can publish a new timestamp at the new revision. A failed or partial observe does not replace the old timestamp. The same published completion cannot be invalidated twice. An observe that follows an invalidation may increment revision again. That second increment belongs to observe, not to a second invalidation.

## OWNER_SNAPSHOT_RESULTS

After invalidation, the money-management fragment keeps its numeric fields and `producerObservedAt`. The four completion names are absent. `freshness` stays `UNKNOWN`. `freshnessPolicy` is absent.

## RUNTIME_EVIDENCE_RESULTS

`runtime_evidence.py` is unchanged. A fragment that remains after invalidation is `UNKNOWN`. A missing fragment is `UNAVAILABLE`. `CURRENT` is not produced.

## ADVISOR_SUPERVISOR_RESULTS

Advisor and Supervisor both read `load_shared_operator_context`. After invalidation, the money-management runtime status is `UNKNOWN`, the completion name is absent from the rendered block, `authority` is `NONE`, and `tradingControl` is `FORBIDDEN`.

## SECURITY_RESULTS

The operator route without a session returns 401. `PUBLIC_ENDPOINT_ENABLED` is false. The public view does not contain `mmObservationCompletedAt`, `evidenceRevision`, or `runtimeEvidence`. Invalidation does not call account refresh and does not call an order method. No freshness policy, TTL, CURRENT rule, trading authority, exchange API, or account sync was added.

## TEST_RESULTS

New file `tests/test_mm_observation_invalidation.py`: T01–T46 passed.

Also passed in this worktree:

- `tests/test_mm_observation_completion_evidence.py`
- `tests/test_money_management_loss_authoritative_runtime_metrics.py`
- `tests/test_paper_capital_reset.py`
- `tests/test_mm_runtime_session_rehydration.py`
- `tests/test_mm_live_peak_authority_recovery.py`
- `tests/test_mm_live_peak_authority_separation.py`
- `tests/test_ai_context_owner_snapshot.py`
- `tests/test_ai_context_owner_wiring.py`
- `tests/test_ai_context_owner_cache.py`
- `tests/test_ai_context_owner_integration.py`
- `tests/test_ai_context_runtime_evidence.py`
- `tests/test_ai_context_runtime_producer.py`
- `tests/test_ai_context_snapshot_copy.py`
- `tests/test_ai_advisor_mm_authority_preservation.py`
- `tests/test_paper_mm_capital_authority.py`
- `tests/test_account_status_financial_contract.py`
- `tests/test_account_view_dual_projection.py`
- `tests/test_current_position_view.py`
- `tests/test_bot_manager.py`

The related set that includes the F1.9 baseline files reported 223 passed and 9 failed. Those nine are the known baseline.

## TEST_FAILURES

F01–F03: `tests/test_paper_trade_pipeline.py` still fails on `handoffExecuted` false and the following `actual_position is None`.

F04–F05: `tests/test_mm_stopped_paper_recovery_metrics.py` still fails because stopped FLAT PAPER leaves `observation_valid` false, and the stale reader reports `INCONSISTENT`.

F06–F09: `tests/test_mm_baseline_session_transition.py` still returns `error` from `BotManager.start` with `RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL`.

These nine were classified `PRE_EXISTING_FAILURE` in F1.9. This implementation does not change their signatures.

`tests/test_exchange_live_status.py` also has failures, including `RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL` and `FINAL_STATE_UNKNOWN` versus `SNAPSHOT_SOURCE_UNKNOWN`. The same two representative tests fail on the untouched design worktree at `06550215aa3b0354946b7be0bc315090e8788d1c`. They are not a new regression of this change.

## NEW_REGRESSIONS

None in the new invalidation file, the F1 evidence file, the authoritative metrics file, the owner and runtime context files, the capital reset file, or `tests/test_bot_manager.py`.

## ACCEPTANCE_MATRIX

| ID | Item | Result |
| --- | --- | --- |
| A01 | Producer invalidation method | PASS |
| A02 | One-time revision increment | PASS |
| A03 | Timestamp preservation | PASS |
| A04 | as_of preservation | PASS |
| A05 | MM metrics preservation | PASS |
| A06 | PAPER auto entry | PASS |
| A07 | PAPER auto close | PASS |
| A08 | PAPER price update | PASS |
| A09 | PAPER manual entry | PASS |
| A10 | PAPER manual close | PASS |
| A11 | PAPER emergency flatten | PASS |
| A12 | PAPER capital reset | PASS |
| A13 | PAPER stop | PASS |
| A14 | LIVE balance cache | PASS |
| A15 | LIVE position cache | PASS |
| A16 | LIVE partial cache | PASS |
| A17 | LIVE source change | PASS |
| A18 | LIVE authentication change | PASS |
| A19 | LIVE stale change | PASS |
| A20 | LIVE no-op cases | PASS |
| A21 | Mode transition | PASS |
| A22 | Revision consistency | PASS |
| A23 | Observation failure safety | PASS |
| A24 | Owner snapshot | PASS |
| A25 | Runtime evidence | PASS |
| A26 | Advisor / Supervisor | PASS |
| A27 | Operator authentication | PASS |
| A28 | Public isolation | PASS |
| A29 | No false CURRENT | PASS |
| A30 | No MM calculation change | PASS |
| A31 | No execution authority change | PASS |
| A32 | No account sync | PASS |
| A33 | No real orders | PASS |
| A34 | No new regression | PASS |
| A35 | Canonical reconciliation | PASS |

## Canonical reconciliation

merge-base with `origin/main`: `39273a115637edaba42ea49bde732f1ae6436399`.

`git diff --name-status HEAD...origin/main` at the design base does not include `loss_authoritative_runtime_metrics.py` or `bot_manager.py`. The sixteen differing paths are `MAIN_ONLY` and were not edited. No merge and no cherry-pick was performed. The canonical worktree and its uncommitted files were not modified.

## REMAINING_GAPS

After PAPER manual entry, the fragment numbers stay at the previous observe until a later cycle observe. The completion clock is unpublished during that interval.

A LIVE engine position change, including LIVE emergency flatten, does not invalidate the cache completion and does not refresh the cache.

An invalidation followed by a successful observe advances `_revision` twice. The published evidence revision is the observe revision.

F01–F09 remain unfixed.

BLOCK_REASON: none

DEPENDENCY: the F1 note gate and owner-snapshot publication gate at the design base.

RESUME_CONDITION: start the acceptance task from this implementation commit. Do not start it in this pass.

NEXT_RECOMMENDED_TASK: BB_MM_F2_INVALIDATION_INSTRUMENTATION_ACCEPTANCE
