# BB-MM-F6 Canonical Integration Execution

TASK_ID: TRADINGAI-WORK-BB-MM-F6-CANONICAL-INTEGRATION-EXECUTION-1

VERDICT: BB_MM_CANONICAL_INTEGRATION_EXECUTION_PASS

Isolated integration on `integration/ai-mm-canonical`. Canonical `main`
was not committed, merged, cherry-picked, pushed, deployed, or restarted.
No exchange connection and no order.

CANONICAL_HEAD_START: `294f7d35c952d47921ffe09c442a3d3f88bad7f6`

CANONICAL_HEAD_END: `294f7d35c952d47921ffe09c442a3d3f88bad7f6`

ORIGIN_MAIN_HEAD: `f344864344b0b99a598f674b3e2e4a367bc9fb25`

WORKTREE: `/home/joe4410joe/tradingai_prod_v1.worktrees/ai-mm-canonical-integration`

BRANCH: `integration/ai-mm-canonical`

BASE_COMMIT: `294f7d35c952d47921ffe09c442a3d3f88bad7f6`

HEAD_BEFORE: `294f7d35c952d47921ffe09c442a3d3f88bad7f6`

HEAD_AFTER: the child of `HEAD_BEFORE` on this branch whose message is
`work-bb: integrate mm runtime evidence with canonical main`. The full
hash is recorded in the external audit copy only.

COMMIT: that integration commit. It contains the BB tree delta, the
`backend/main.py` registration resolution, and this document.

BB_SOURCE: `23684d9e7b910a4210198b9b2f4d84fb853ddb7a`

BB_BASE: `39273a115637edaba42ea49bde732f1ae6436399`

F5 audit commit `e2f77826ad50f3252a2fa626e8da69cf1c00f4a1` recommends
option C. Local main and origin/main matched the F5 baseline at
execution time, so no new shared-path review was required beyond
`backend/main.py`.

## APPLIED_DELTA

Direction: `39273a1` to `23684d9` only. The two-dot diff of local main
against F4 was not used.

`git diff --check` on that range reported one existing source note:
`docs/ai/CONTEXT_PACK_SPEC.md:540: new blank line at EOF`. The staged
integration diff reports that same line. The file blob still matches
F4. No conflict markers. No other whitespace error.

`backend/main.py` was excluded from the patch because both sides insert
at the same anchor. The other 87 paths were written to
`/tmp/work_bb_f6_delta.patch` (30180 lines). `git apply --check` passed.
`git apply` applied that patch once. Every one of those 87 blobs matches
F4. No BB path was applied twice.

Stat of the source range, including `backend/main.py`, remains
88 files, `+29229 / -19`.

## CONFLICT_RESOLUTION

Only `backend/main.py` needed a manual resolution. No `--reject` and no
`--3way`. No other hunk failed.

The resolved file keeps every `include_router` line from local main and
every `include_router` line from F4.

## BACKEND_MAIN_REGISTRATION

After the logs router:

1. Work AA block, once:
   `from backend.observation_auth.oidc_mount import mount_observation_oidc`
   and `mount_observation_oidc(app)`.
2. BB block, once:
   `from backend.context.api_router import context_router`
   and `app.include_router(context_router)`.

`context_router` prefix is `/api/ai-context`. Its router dependency is
`require_operator_session`. `PUBLIC_ENDPOINT_ENABLED` is false.
Importing `backend.context.api_router` and
`backend.observation_auth.oidc_mount` in one process completed without a
circular import. `backend.main` itself was not imported, so this check
did not start the production server.

## CONTEXT_FOUNDATION_RESULTS

Present and covered by the passing context suite:

| Piece | Location |
| --- | --- |
| Schema `tradingai-context/v1` | `backend/context/schema.py` |
| Source truth | `backend/context/source_truth.py`, `source_evidence.py` |
| Runtime truth | `backend/context/runtime_truth.py`, `runtime_evidence.py` |
| Project truth | `backend/context/project_truth.py`, `project_evidence.py` |
| Decision truth | `backend/context/decision_evidence.py` |
| Registry | `tests/test_ai_context_project_registry.py` |
| Reader | `backend/context/runtime_reader_adapter.py` |
| Builder | `backend/context/builder.py` |
| Serializer | `backend/context/serializer.py` |
| Router | `backend/context/api_router.py` |
| Owner snapshot injection | `backend/bot_manager/owner_snapshot.py`, `owner_context_bridge.py` |
| Advisor | `backend/ai_advisor/browser_gateway.py` calls `load_shared_operator_context` |
| Supervisor | `backend/api/supervisor_conversation.py` calls the same loader |

## MM_OBSERVATION_RESULTS

`tests/test_mm_observation_completion_evidence.py` passed. The owner
copy still publishes `mmObservationCompletedAt` only when the evidence
revision equals the metrics revision, completeness is `COMPLETE`, and
the scope is `PAPER_ENGINE_ACCOUNT` or `LIVE_ACCOUNT_CACHE`. A mismatched
revision does not publish the old completion.

## MM_INVALIDATION_RESULTS

`tests/test_mm_observation_invalidation.py` passed. Covered reasons
include `PAPER_INPUT_MUTATION`, `PAPER_MANUAL_ENTRY`, manual close,
`PAPER_RUNTIME_STOP`, and `LIVE_ACCOUNT_CACHE_MUTATION`. A second
invalidate on the same unpublished revision does not advance revision
again. A rejected entry does not invalidate. After invalidation the
completion fields and LIVE source fields are absent from the published
fragment.

## MM_FRESHNESS_RESULTS

`tests/test_mm_freshness_evidence_gap.py` passed. A present MM fragment
stays `UNKNOWN`. A missing fragment stays `UNAVAILABLE`. An explicit
`freshness=STALE` on another domain stays `STALE`, and the same explicit
label is honored for a domain that carries it. `CURRENT` is not
selected from `freshnessPolicy`, `as_of`, `publishedAt`, revision
equality, or an invalidation reason. No MM heartbeat, TTL, or age bound
was added.

## ADVISOR_RESULTS

Advisor gateway still calls `load_shared_operator_context`. The
integration tests assert the Advisor attachment uses that runtime
evidence. `RUNTIME_FRESHNESS_SECONDS = 10` remains the bot-summary clock
in `backend/ai_advisor/service.py` and is not the MM runtime status.
No Advisor MM freshness authority was added.

## SUPERVISOR_RESULTS

The conversation route still calls `load_shared_operator_context` when
an operator identity is present. The same owner document yields the same
`runtimeEvidence` as the Advisor path in the passing consistency tests.
`backend/supervisor/snapshot_builder.py` and
`runtime_snapshot_adapter.py` are unchanged from local main.
`tests/test_supervisor_snapshot_builder.py` and
`tests/test_supervisor_runtime_snapshot_adapter.py` passed (46 tests).
That snapshot freshness rule was not copied into Canonical MM runtime
status.

## SECURITY_RESULTS

Passing tests assert HTTP 401 without an operator session
(`test_t34_operator_route_is_401` and the completion-evidence route
check) and assert `runtimeEvidence` is absent from the public view.
`PUBLIC_ENDPOINT_ENABLED` is false. No public MM route was added.

## AUTHORITY_RESULTS

Passing tests assert `authority=NONE` and `tradingControl=FORBIDDEN` on
both readers. `Bot/engine/execution_engine.py` is unchanged from local
main. Manual trading and emergency stop code were not edited. No order
was sent. Observation tests keep `refresh_calls == 0`.

## WORK_AA_OIDC_RESULTS

`mount_observation_oidc(app)` remains one call. These offline files
passed:

- `tests/test_work_aa_observation_oidc_offline.py`
- `tests/test_work_aa_oidc_router_jwks_http_offline.py`
- `tests/test_work_aa_oidc_preconnect_offline.py`
- `tests/test_work_aa_oidc_nginx_logout_candidate_offline.py`

80 tests. The OIDC package under `backend/observation_auth/` and
`tools/work_aa/` matches local main.

## MAIN_ONLY_REGRESSION_RESULTS

Unchanged from `HEAD_BEFORE`, confirmed by an empty diff for:

- `backend/money_management/loss_execution_integration.py`
- `backend/money_management/loss_http_api.py`
- `backend/supervisor/runtime_snapshot_adapter.py`
- `backend/supervisor/snapshot_builder.py`
- `backend/api/money_management.py`
- `Bot/engine/execution_engine.py`
- `backend/runtime/cycle_diagnostics.py`
- frontend runtime card files
- Work AA paths

`tests/test_money_management_execution_entry_preview.py`: 13 passed.
Supervisor snapshot files: 46 passed. Work AA offline files: 80 passed.
Combined command: 139 passed, 6 subtests passed.

## TEST_COMMANDS

Run from the integration worktree. No production process was used.

```text
python3 -m pytest -q --tb=line \
  tests/test_ai_context_schema.py \
  tests/test_ai_context_project_registry.py \
  tests/test_ai_context_source_truth.py \
  tests/test_ai_context_source_evidence.py \
  tests/test_ai_context_project_evidence.py \
  tests/test_ai_context_decision_evidence.py \
  tests/test_ai_context_runtime_truth.py \
  tests/test_ai_context_runtime_reader.py \
  tests/test_ai_context_runtime_evidence.py \
  tests/test_ai_context_runtime_producer.py \
  tests/test_ai_context_runtime_coverage.py \
  tests/test_ai_context_runtime_reacceptance.py \
  tests/test_ai_context_builder.py \
  tests/test_ai_context_serializer.py \
  tests/test_ai_context_collector.py \
  tests/test_ai_context_api.py \
  tests/test_ai_context_router_integration.py \
  tests/test_ai_context_owner_snapshot.py \
  tests/test_ai_context_owner_wiring.py \
  tests/test_ai_context_owner_cache.py \
  tests/test_ai_context_owner_integration.py \
  tests/test_ai_context_injection_boundary.py \
  tests/test_ai_context_snapshot_copy.py \
  tests/test_ai_context_integrated_knowledge.py \
  tests/test_ai_context_support.py \
  tests/test_ai_context_advisor_supervisor_integration.py \
  tests/test_mm_freshness_evidence_gap.py \
  tests/test_mm_observation_invalidation.py \
  tests/test_mm_observation_completion_evidence.py \
  tests/test_supervisor_runtime_acceptance.py \
  tests/test_supervisor_held_evaluation_cache.py \
  tests/test_money_management_loss_authoritative_runtime_metrics.py \
  tests/test_ai_advisor_mm_authority_preservation.py
```

```text
python3 -m pytest -q --tb=line \
  tests/test_money_management_execution_entry_preview.py \
  tests/test_work_aa_observation_oidc_offline.py \
  tests/test_work_aa_oidc_router_jwks_http_offline.py \
  tests/test_work_aa_oidc_preconnect_offline.py \
  tests/test_work_aa_oidc_nginx_logout_candidate_offline.py \
  tests/test_supervisor_snapshot_builder.py \
  tests/test_supervisor_runtime_snapshot_adapter.py
```

```text
python3 -m pytest --tb=line -q \
  tests/test_paper_trade_pipeline.py \
  tests/test_mm_stopped_paper_recovery_metrics.py \
  tests/test_mm_baseline_session_transition.py
```

`tests/test_exchange_live_status.py` was not run. The BB delta does not
contain that file, and F5 classified its 85 failures as pre-existing
and out of this gate.

## TEST_RESULTS

| Command | Result |
| --- | --- |
| Context, owner, MM evidence, Advisor, Supervisor readers, metrics | 625 passed, 2 subtests passed, 40 deprecation warnings from Starlette TestClient cookies |
| Entry preview, Work AA OIDC, supervisor snapshot | 139 passed, 6 subtests passed |
| Known-failure selection | 6 failed, 18 passed, 5 subtests passed |

## KNOWN_FAILURES

Same command as F4 acceptance. F4 recorded 9 failed, 15 passed, 5
subtests passed. This worktree recorded 6 failed, 18 passed, 5 subtests
passed.

The six failures match F04–F09:

| ID | Test | Signature | Class |
| --- | --- | --- | --- |
| F04 | `test_fresh_stopped_paper_is_available_complete_and_current_identity` | `AssertionError: False is not true` | PRE_EXISTING_FAILURE |
| F05 | `test_stale_store_reports_stale` | `INCONSISTENT != STALE` | PRE_EXISTING_FAILURE |
| F06 | `test_stop_boundary_ws_callback_never_overwrites_active_mm_authority` | `'error' == 'started'` at line 211 | PRE_EXISTING_FAILURE |
| F07 | `test_run_boundary_ws_callback_still_observes_when_authority_active` | `'error' == 'started'` at line 271 | PRE_EXISTING_FAILURE |
| F08 | `test_session_1_stop_2_stop_3_start_recovers_with_fresh_baseline` | `RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL` at line 621 | PRE_EXISTING_FAILURE |
| F09 | `test_monitoring_start_allowed_with_incomplete_pre_runtime_baseline` | `RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL` at line 722 | PRE_EXISTING_FAILURE |

F01, F02, and F03 in `tests/test_paper_trade_pipeline.py` passed here.
That file and `Bot/engine/execution_engine.py` are the local-main
versions, which F4 did not contain. The three additional passes are the
retained main behavior, not a rewritten assertion.

## NEW_REGRESSIONS

None. The context suite and the main-only suite passed. The known-failure
command added no failure beyond F04–F09.

## TEST_MATRIX

| ID | Item | Result |
| --- | --- | --- |
| T01 | Context schema | PASS |
| T02 | Context registry | PASS |
| T03 | Context reader | PASS |
| T04 | Context builder | PASS |
| T05 | Context serializer | PASS |
| T06 | Context router | PASS |
| T07 | Operator 401 | PASS |
| T08 | PUBLIC isolation | PASS |
| T09 | Owner snapshot | PASS |
| T10 | MM observation evidence | PASS |
| T11 | MM invalidation | PASS |
| T12 | MM freshness UNKNOWN | PASS |
| T13 | MM freshness UNAVAILABLE | PASS |
| T14 | Explicit STALE | PASS |
| T15 | No false CURRENT | PASS |
| T16 | No reason-only STALE | PASS |
| T17 | PAPER observation | PASS |
| T18 | PAPER mutation | PASS |
| T19 | PAPER manual entry | PASS |
| T20 | PAPER manual close | PASS |
| T21 | PAPER stop | PASS |
| T22 | LIVE observation | PASS |
| T23 | LIVE cache mutation | PASS |
| T24 | LIVE source evidence | PASS |
| T25 | Advisor reader | PASS |
| T26 | Supervisor reader | PASS |
| T27 | Advisor / Supervisor consistency | PASS |
| T28 | Authority NONE | PASS |
| T29 | Trading control FORBIDDEN | PASS |
| T30 | Work AA OIDC | PASS |
| T31 | MM entry preview | PASS |
| T32 | Existing supervisor snapshot | PASS |
| T33 | No exchange API | PASS |
| T34 | No real orders | PASS |
| T35 | No new regression | PASS |
| T36 | Integration delta completeness | PASS |
| T37 | No main-only deletion | PASS |
| T38 | `backend/main.py` both registrations | PASS |

T33 and T34 use the passing `refresh_calls == 0` assertions and the
absence of execution-engine edits. They are not a live exchange probe.

## ACCEPTANCE_MATRIX

| ID | Item | Result |
| --- | --- | --- |
| A01 | BB delta applied | PASS |
| A02 | Context foundation | PASS |
| A03 | Runtime evidence | PASS |
| A04 | Owner snapshot | PASS |
| A05 | MM observation | PASS |
| A06 | MM invalidation | PASS |
| A07 | MM freshness | PASS |
| A08 | Advisor integration | PASS |
| A09 | Supervisor integration | PASS |
| A10 | Advisor / Supervisor consistency | PASS |
| A11 | Operator authentication | PASS |
| A12 | PUBLIC isolation | PASS |
| A13 | Authority preservation | PASS |
| A14 | Work AA OIDC preservation | PASS |
| A15 | MM entry preview preservation | PASS |
| A16 | Supervisor snapshot preservation | PASS |
| A17 | No main-only deletion | PASS |
| A18 | No new regression | PASS |
| A19 | Integration worktree clean | PASS |
| A20 | Canonical main unchanged | PASS |

A19 is PASS after the integration commit. The external audit copy
records the clean status.

## REMAINING_GAPS

None that block this execution. Promotion onto canonical `main` is a
separate task. F04–F09 remain pre-existing and were not fixed.
`tests/test_exchange_live_status.py` was not repeated.

## BLOCK_REASON

None.

## DEPENDENCY

Base remains local main `294f7d35c952d47921ffe09c442a3d3f88bad7f6`.
BB source remains F4 `23684d9e7b910a4210198b9b2f4d84fb853ddb7a`.
Origin main is still one Work AA commit behind local main.

## RESUME_CONDITION

Not blocked. Promotion readiness can start only as a separate task.
This branch is not merged.

## NEXT_RECOMMENDED_TASK

BB_MM_CANONICAL_PROMOTION_READINESS

Do not start it automatically.
