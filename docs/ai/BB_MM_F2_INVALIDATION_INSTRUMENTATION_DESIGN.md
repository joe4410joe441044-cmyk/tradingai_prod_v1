# BB-MM-F2 Invalidation Instrumentation Design

TASK_ID: TRADINGAI-WORK-BB-MM-F2-INVALIDATION-INSTRUMENTATION-DESIGN-1

VERDICT: BB_MM_F2_INVALIDATION_DESIGN_PASS

CANONICAL_HEAD: f344864344b0b99a598f674b3e2e4a367bc9fb25

ORIGIN_MAIN: f344864344b0b99a598f674b3e2e4a367bc9fb25

WORKTREE: /home/joe4410joe/tradingai_prod_v1.worktrees/ai-mm-invalidation-design

BRANCH: design/ai-mm-invalidation-instrumentation

BASE_COMMIT: f6ba7bfb7447d2bed3d6a84061303947e8d0c157

HEAD_BEFORE: f6ba7bfb7447d2bed3d6a84061303947e8d0c157

HEAD_AFTER: the docs-only commit on this branch whose message is `work-bb: design mm observation invalidation`. The external report records that commit hash after the commit. This file does not contain its own hash.

CHANGED_FILES:

- docs/ai/BB_MM_F2_INVALIDATION_INSTRUMENTATION_DESIGN.md

COMMIT: work-bb: design mm observation invalidation

PREVIOUS_TASK: TRADINGAI-WORK-BB-MM-F1-OBSERVATION-INSTRUMENTATION-ACCEPTANCE-1

PREVIOUS_VERDICT: BB_MM_F1_OBSERVATION_ACCEPTANCE_PASS

IMPLEMENTATION_COMMIT: ac1f1d4dc2ab6f7d83f6377d4510465eed532a4f

ACCEPTANCE_COMMIT: f6ba7bfb7447d2bed3d6a84061303947e8d0c157

This document is design only. It does not change application code, freshness policy, or CURRENT judgment.

## D01 CURRENT_EVIDENCE_CONTRACT

The F1 contract stays in force.

Producer: `AuthoritativeLossRuntimeMetricsState` in `backend/money_management/loss_authoritative_runtime_metrics.py`.

Completion write: `note_mm_observation_completed`. It stores `mm_observation_completed_at`, `mm_observation_input_completeness`, `mm_observation_input_scope`, and `mm_observation_evidence_revision` only when the stored `_revision` equals the revision returned by the observation, `observation_valid` is true, `input_completeness` is `COMPLETE`, and `input_scope` is `PAPER_ENGINE_ACCOUNT` or `LIVE_ACCOUNT_CACHE`. The note does not change equity, drawdown, peak, `as_of`, or `_revision`.

Publication: `owner_snapshot._copy_mm_observation_completion` copies `mmObservationCompletedAt`, `inputCompleteness`, `inputScope`, and `evidenceRevision` only when `evidenceRevision == revision`, completeness is `COMPLETE`, and the scope is one of those two names. `producerObservedAt` remains `as_of`. `publishedAt` remains the publication clock. `freshness` stays `UNKNOWN`. `freshnessPolicy` is not added.

Runtime evidence: `backend/context/runtime_evidence.py` `_judge`. A money-management fragment with no freshness policy is `UNKNOWN`. A missing fragment is `UNAVAILABLE`. `CURRENT` is forbidden. A matching revision is not `CURRENT`.

PAPER note gate, in `BotManager._observe_money_management_runtime_metrics`: the `account_snapshot` object returned by `_capture_account_snapshot` and assigned to `self.account_snapshot` must be a new object, `observation_valid` must be true, and `observe` must return. The same-object exception path does not note.

Stopped PAPER note gate, in `BotManager.initialize_money_management_runtime_metrics`: after `observe_stopped_paper_maintenance`, note only when the store observation freshness is `FRESH` and `observation_valid` is true.

LIVE note gate: `BotManager._live_account_input_completeness` returns `COMPLETE` only when both `balanceSource` and `positionSource` are `KUCOIN_FUTURES_READ_ONLY`, at least one of balance, equity, or available balance is present, `positions` is present and not null, `authenticated` is true, and `stale` is false. The classifier reads the copy passed into `observe`. It does not call `_refresh_real_account_snapshot`.

`begin_runtime_session`, first `restore`, and `apply_validated_peak_recovery` increment `_revision` and do not call the note. A later observe that fails the note gate also increments `_revision` without replacing the stored timestamp. The old timestamp remains in producer memory and is omitted from the owner snapshot.

## Invalidation model

A. Observation completion is the existing note. It is the only writer of `mmObservationCompletedAt`.

B. Input mutation is a change to an input the money-management fragment actually reads.

PAPER fragment inputs are the engine account fields read by the PAPER observe path: balance, realized PnL, unrealized PnL, position, and mark price, as captured into `account_snapshot`.

LIVE fragment inputs are `real_account_snapshot` fields read by the LIVE observe path: balance, equity, available balance, positions, `balanceSource`, `positionSource`, `authenticated`, and `stale`. `engine.actual_position` is not a LIVE fragment input.

C. Evidence invalidation means the stored completion no longer identifies the current metrics revision. The timestamp value stays unchanged. Publication omits the four completion names because `mm_observation_evidence_revision != revision`.

D. Re-observation is a later `observe` or `observe_stopped_paper_maintenance` that returns and passes the existing note gate. That note writes a new timestamp for the new revision.

Required order when a mutation and an observe share a call:

1. Input mutation returns.
2. Revision-only invalidation, when a completion is currently published.
3. Observe.
4. Note only if the existing success gate passes.

Input mutation does not write a new `mmObservationCompletedAt`. Invalidation does not move the old timestamp to a new time. A failed or partial observe must leave the old timestamp unpublished.

## D07 REVISION_STRATEGY

No new field is added. `mmInputRevision` and `mmInvalidationRevision` are not introduced.

The existing metrics `_revision` is the invalidation signal. The existing `mm_observation_evidence_revision` remains the revision the note last accepted. Publication already treats inequality as omission. Runtime status remains `UNKNOWN` or `UNAVAILABLE`. Revision inequality is not `CURRENT`.

New producer method, owner `AuthoritativeLossRuntimeMetricsState`:

`invalidate_mm_observation_evidence()`

WRITE_POINT: inside the metrics lock.

INCREMENT_RULE:

- If `mm_observation_evidence_revision` is absent, return the current snapshot and do not increment. There is no published completion to withdraw.
- If `mm_observation_evidence_revision != _revision`, return the current snapshot and do not increment. The completion is already unpublished. A second call is a no-op.
- Otherwise increment `_revision` by one.

The method does not change `as_of`, equity, peak, drawdown, session counts, observation validity, the timestamp, completeness, scope, or evidence revision.

READ_POINT: the existing owner-snapshot comparison `evidenceRevision == revision`. No new reader is added.

SERIALIZATION: no new serialized name. The four existing names disappear from the fragment when the revisions differ. The timestamp remains available on the producer snapshot object as history.

COMPATIBILITY: callers that already increment `_revision` without noting (`begin_runtime_session`, first `restore`, `apply_validated_peak_recovery`, and an observe that fails the note gate) already unpublish the clock. They must not also call the new method. The idempotent rule makes an accidental second call a no-op only after the first mismatch exists; calling it before those methods would add an extra increment. The implementation must not insert the call on those three paths.

TEST: a published completion becomes absent from the owner fragment after one call; the timestamp value on the producer snapshot is unchanged; `as_of` and equity are unchanged; a second call does not increment again; a later successful note publishes a new timestamp at the observe revision.

`begin_runtime_session`, `restore`, and peak recovery stay as they are. They move `as_of` and other session or peak fields, so they are not reused as the mutation invalidation write.

## Proposed call helper

`BotManager._invalidate_mm_observation_evidence()` calls the producer method when `money_management_runtime_metrics` exposes it. It does not observe, capture an account, refresh a cache, or place an order. A log reason may be recorded for tests. The reason is not a fragment field and is not copied to public context.

MM-relevant LIVE projection, used only to decide whether a cache assignment is a mutation: balance, equity, available balance, positions, `balanceSource`, `positionSource`, `authenticated`, `stale`. `loading`, `lastAttempt`, and `generation` alone are not fragment inputs.

## D02 INVALIDATION_TRIGGER_MATRIX

Class meanings: `REQUIRED` means the next implementation adds the revision-only invalidation. `NOT_REQUIRED` means the current code already unpublishes the completion, or the event does not change a fragment input. `CONDITIONAL` means the invalidation runs only when the stated mutation is observed. `UNKNOWN` means the code did not establish the point. No row below is `UNKNOWN`.

### E01 PAPER Auto Entry

CLASS: REQUIRED

ACTUAL_SOURCE_FILE: `Bot/engine/execution_engine.py`; caller `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: `ExecutionEngine.on_price`; caller nested `on_update` inside `BotManager.start`

ACTUAL_CALL_PATH: market update -> `on_update` -> `engine.on_price` -> signature compare -> authority recheck -> `_observe_money_management_runtime_metrics`

MM_INPUT_AFFECTED: yes, when `actual_position` changes from empty to a position

INPUT_FIELDS_AFFECTED: engine position, and the balance or realized PnL fields the signature reads

EXISTING_OBSERVE_TRIGGER: yes, after `on_price`, only while `_money_management_runtime_observation_authority` still holds the runtime id and session

EXISTING_REVISION_CHANGE: `observe` increments `_revision` when it returns; the note runs only if the PAPER gate passes

INVALIDATION_REQUIRED: yes

INVALIDATION_REASON: `on_price` can commit the entry before observe. If the authority recheck returns at the early exit after `on_price`, observe does not run and the old completion stays published. If observe raises before its own increment, the same publication remains.

PROPOSED_INSTRUMENTATION_POINT: in `on_update`, after `on_price` returns, if the before/after signature or `latest_price` / `unrealized_pnl` changed, call the revision-only invalidation before the authority recheck. If the recheck fails, return without observe. If it holds, observe and let the existing note write the new completion.

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: position signature changes, old timestamp value is kept, owner fragment omits the four names, then a successful observe publishes a new timestamp. An authority miss after `on_price` leaves the old timestamp unpublished and does not create a new one.

### E02 PAPER Auto Close

CLASS: REQUIRED

ACTUAL_SOURCE_FILE: `Bot/engine/execution_engine.py`; caller `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: `ExecutionEngine.on_price` / `ExecutionEngine.close_position`; caller `on_update`

ACTUAL_CALL_PATH: same as E01. Classifier returns `TRADE_CLOSE` when the signature position goes from present to absent.

MM_INPUT_AFFECTED: yes

INPUT_FIELDS_AFFECTED: engine position, balance, realized PnL

EXISTING_OBSERVE_TRIGGER: same callback observe as E01

EXISTING_REVISION_CHANGE: observe increments when it returns

INVALIDATION_REQUIRED: yes

INVALIDATION_REASON: same window as E01. A close already applied by `on_price` must not keep the pre-close completion if observe is skipped or raises.

PROPOSED_INSTRUMENTATION_POINT: same post-`on_price` invalidation as E01, before observe.

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: close signature change unpublishes the old timestamp before observe; observe success publishes a new timestamp; observe exception leaves it unpublished.

### E03 PAPER Price Update

CLASS: REQUIRED

ACTUAL_SOURCE_FILE: `Bot/engine/execution_engine.py`; caller `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: `ExecutionEngine.on_price`; caller `on_update`

ACTUAL_CALL_PATH: `on_update` assigns the callback price, then `on_price` sets `latest_price` and updates unrealized PnL when a position and multiplier exist. The event signature does not include unrealized PnL or `latest_price`, so the classifier can return null while the PAPER observe input still changed. Observe still runs when authority holds.

MM_INPUT_AFFECTED: yes when `latest_price` or `unrealized_pnl` changes

INPUT_FIELDS_AFFECTED: `latest_price`, `unrealized_pnl`

EXISTING_OBSERVE_TRIGGER: yes, including a null event type

EXISTING_REVISION_CHANGE: observe increments when it returns

INVALIDATION_REQUIRED: yes when price or unrealized PnL changed

INVALIDATION_REASON: the fragment can still publish the previous completion while the engine mark has already moved, until observe returns. An authority miss skips observe.

PROPOSED_INSTRUMENTATION_POINT: same post-`on_price` comparison as E01, including `latest_price` and `unrealized_pnl`. Early returns inside `on_price` that happen before `latest_price` is assigned do not invalidate.

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: unchanged early return keeps the published timestamp. A changed mark unpublishes it, then a successful observe publishes a new one.

### E04 PAPER Manual Entry

CLASS: REQUIRED

ACTUAL_SOURCE_FILE: `backend/bot_manager/bot_manager.py`; mutation in `Bot/engine/execution_engine.py`

ACTUAL_FUNCTION: `BotManager._manual_entry_locked`; `ExecutionEngine.try_entry`

ACTUAL_CALL_PATH: `execute_manual_trade` -> `_manual_entry_locked` -> `engine.try_entry`. PAPER success requires `entry_authority == MANUAL` and a matching `request_id`. The success return is `MANUAL_ENTRY_FILLED`. This function does not call `_observe_money_management_runtime_metrics`.

MM_INPUT_AFFECTED: yes on a confirmed fill

INPUT_FIELDS_AFFECTED: `engine.actual_position` and the related PAPER balance fields written by `try_entry`

EXISTING_OBSERVE_TRIGGER: none in this function. The next observe is a later `on_update` while authority holds.

EXISTING_REVISION_CHANGE: none on this path

INVALIDATION_REQUIRED: yes

INVALIDATION_REASON: after a confirmed fill the old completion still matches the current revision, so the owner snapshot can publish it until some later observe.

PROPOSED_INSTRUMENTATION_POINT: after the confirmed-fill checks and before the `MANUAL_ENTRY_FILLED` return, call the revision-only invalidation. Do not add observe. Do not change `try_entry` or the deny returns.

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: confirmed PAPER fill keeps the old timestamp value, omits it from the owner fragment, and does not call observe. A later successful cycle observe may note a new timestamp. A denied entry does not invalidate.

### E05 PAPER Manual Close

CLASS: REQUIRED

ACTUAL_SOURCE_FILE: `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: `BotManager._manual_close_locked`; `BotManager._finalize_manual_close_money_management`

ACTUAL_CALL_PATH: confirmed close -> `_finalize_manual_close_money_management` -> `_observe_money_management_runtime_metrics`. The observe call is inside `try/except Exception` and a failure is logged, not re-raised. Unconfirmed and `ALREADY_CLOSED` returns happen before the finalizer.

MM_INPUT_AFFECTED: yes when the close commits

INPUT_FIELDS_AFFECTED: engine position, balance, realized PnL

EXISTING_OBSERVE_TRIGGER: yes, after a confirmed close

EXISTING_REVISION_CHANGE: only if observe returns. An exception before the increment leaves the revision unchanged.

INVALIDATION_REQUIRED: yes

INVALIDATION_REASON: the finalizer can swallow an observe failure after the position is closed. The pre-close completion must not stay published.

PROPOSED_INSTRUMENTATION_POINT: after the PAPER history confirmation, before `_finalize_manual_close_money_management`. The finalizer then observes. If the signature changed on a deny path that skips the finalizer, invalidate there as well and do not observe. Do not change `close_position`.

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: confirmed close unpublishes the old timestamp before observe. Observe success publishes a new timestamp. A raised observe leaves the old timestamp unpublished and does not write a new one.

### E06 PAPER Emergency Flatten

CLASS: REQUIRED

ACTUAL_SOURCE_FILE: `backend/bot_manager/bot_manager.py`; mutation in `Bot/engine/execution_engine.py`

ACTUAL_FUNCTION: `BotManager._run_emergency_orchestrator_locked`; `ExecutionEngine.flatten_paper_position`

ACTUAL_CALL_PATH: paper branch captures the signature, calls `flatten_paper_position`, classifies the signature, then calls `_observe_money_management_runtime_metrics` even when flatten did not complete.

MM_INPUT_AFFECTED: yes when the flatten changes the engine position or PnL

INPUT_FIELDS_AFFECTED: engine position and the signature balance / realized PnL fields

EXISTING_OBSERVE_TRIGGER: yes, after flatten returns

EXISTING_REVISION_CHANGE: only if observe returns

INVALIDATION_REQUIRED: yes when the signature changed

INVALIDATION_REASON: observe is not guarded. A raise before the revision increment would keep the pre-flatten completion after the engine position changed.

PROPOSED_INSTRUMENTATION_POINT: after `flatten_paper_position` returns, if the signature changed, invalidate, then keep the existing observe call. Do not change the flatten primitive.

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: changed signature unpublishes the old timestamp; observe success notes a new one; observe failure does not restore or rewrite the old timestamp.

### E07 PAPER Account Snapshot Replacement

CLASS: CONDITIONAL

ACTUAL_SOURCE_FILE: `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: `BotManager.reset_paper_capital`; `BotManager._stop_locked` via `_capture_account_snapshot`

ACTUAL_CALL_PATH: `reset_paper_capital` mutates the engine balance, PnL, and position, assigns `self.account_snapshot`, calls `_publish_context_snapshot`, then observes with `PAPER_CAPITAL_RESET`. Stop captures a snapshot before `engine.stop()` and does not observe.

MM_INPUT_AFFECTED: yes when the assigned snapshot identity or PAPER account fields change

INPUT_FIELDS_AFFECTED: `account_snapshot` balance, equity, position

EXISTING_OBSERVE_TRIGGER: capital reset observes after publish. Stop does not observe.

EXISTING_REVISION_CHANGE: capital-reset observe increments when it returns. Stop does not increment.

INVALIDATION_REQUIRED: yes when this replacement happens outside the observe call itself

INVALIDATION_REASON: capital reset publishes the owner snapshot after the account replacement and before observe, so the fragment can still carry the pre-reset completion. Stop can replace `account_snapshot` and later drop the engine without moving the metrics revision.

PROPOSED_INSTRUMENTATION_POINT: in `reset_paper_capital`, invalidate after the snapshot assignment and before `_publish_context_snapshot`, then keep the existing observe. In `_stop_locked`, invalidate after a capture that replaces the snapshot or after the engine is removed, and do not add observe. The capture inside `_observe_money_management_runtime_metrics` is part of observe and is not a second invalidation site.

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: capital reset publish omits the old completion; a successful observe publishes a new one. Stop omits the old completion and does not write a new timestamp.

### E08 PAPER Position Mutation

CLASS: REQUIRED

This is the shared rule for E01, E02, E04, E05, and E06. Any confirmed PAPER engine position change uses the instrumentation point of that event. There is no separate position writer to instrument.

### E09 LIVE Balance Cache Update

CLASS: CONDITIONAL

ACTUAL_SOURCE_FILE: `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: `BotManager._refresh_real_account_snapshot` nested `commit`; `BotManager._prepare_real_account_snapshot_for_exchange`

ACTUAL_CALL_PATH: refresh builds a loading snapshot, reads the existing account client, then `commit` assigns `self.real_account_snapshot` when generation and exchange still match. This method does not call observe.

MM_INPUT_AFFECTED: yes when the committed projection's balance, equity, or available balance differs

INPUT_FIELDS_AFFECTED: `balance`, `equity`, `availableBalance`, `balanceSource`

EXISTING_OBSERVE_TRIGGER: none in the refresh

EXISTING_REVISION_CHANGE: none until a later observe

INVALIDATION_REQUIRED: yes when the MM projection changes

INVALIDATION_REASON: the fragment reads this cache. A new balance can sit under the previous completion until a later observe passes the LIVE gate.

PROPOSED_INSTRUMENTATION_POINT: after an assignment whose MM projection differs, call the revision-only invalidation. Do not add an exchange call or an account sync. A later observe notes only through the existing LIVE gate.

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: a changed balance projection omits the old timestamp. An identical projection does not increment. No observe is added in the refresh.

### E10 LIVE Position Cache Update

CLASS: CONDITIONAL

ACTUAL_SOURCE_FILE: `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: same cache assignment functions as E09

ACTUAL_CALL_PATH: `commit` and the exchange-change assignment in `_prepare_real_account_snapshot_for_exchange`

MM_INPUT_AFFECTED: yes when `positions` or `positionSource` in the assigned snapshot differ

INPUT_FIELDS_AFFECTED: `positions`, `positionSource`

EXISTING_OBSERVE_TRIGGER: none in the refresh

EXISTING_REVISION_CHANGE: none until a later observe

INVALIDATION_REQUIRED: yes when that projection changes

INVALIDATION_REASON: LIVE observe reads cache positions, not `engine.actual_position`

PROPOSED_INSTRUMENTATION_POINT: same projection comparison as E09

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: a changed positions list or position source omits the old timestamp without a new refresh call.

### E11 LIVE Partial Cache Update

CLASS: CONDITIONAL

ACTUAL_SOURCE_FILE: `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: `BotManager._refresh_real_account_snapshot`

ACTUAL_CALL_PATH: a failed side can keep the previous value and still `commit` a snapshot with `stale` true when an older `lastSync` exists. The loading assignment at the start of refresh changes `loading` and `lastAttempt` on a copy of the previous snapshot.

MM_INPUT_AFFECTED: yes when balance, positions, sources, `authenticated`, or `stale` differ. A loading-only or generation-only assignment is not an MM input change.

INPUT_FIELDS_AFFECTED: the changed subset of the MM projection

EXISTING_OBSERVE_TRIGGER: none

EXISTING_REVISION_CHANGE: none

INVALIDATION_REQUIRED: yes for a changed MM projection, including a stale partial commit. Not required for loading-only or generation-only assignment.

INVALIDATION_REASON: a partial cache is not a completed LIVE observation. The old completion must not stay published against the new projection. The existing note gate already refuses `BALANCE_ONLY`, `POSITION_ONLY`, and `UNKNOWN`.

PROPOSED_INSTRUMENTATION_POINT: projection comparison on assignment. Do not invalidate a pure loading copy. Do not add a sync to complete the failed side.

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: partial commit with `stale` true omits the completion. A loading-only copy does not increment. The next observe does not note unless the existing COMPLETE gate passes.

### E12 LIVE Engine Position Mutation

CLASS: NOT_REQUIRED

ACTUAL_SOURCE_FILE: `Bot/engine/execution_engine.py`; LIVE emergency in `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: `ExecutionEngine.try_entry`, `ExecutionEngine.on_price`, `ExecutionEngine.close_position`; `BotManager._run_emergency_orchestrator_locked`

ACTUAL_CALL_PATH: LIVE manual entry and the market callback can change `engine.actual_position`. LIVE emergency calls `exchange.cancel_all_orders` and `exchange.flatten_current_position` and returns through `_classify_live_emergency_result`. That branch does not call observe and does not assign `real_account_snapshot`. The known-zero LIVE return also does not observe.

MM_INPUT_AFFECTED: no. LIVE observe reads `real_account_snapshot`.

INPUT_FIELDS_AFFECTED: none of the fragment inputs, unless a separate cache assignment also happens

EXISTING_OBSERVE_TRIGGER: the market callback still observes the cache after `on_price`. Manual LIVE entry does not observe. LIVE emergency does not observe.

EXISTING_REVISION_CHANGE: only when that cache observe runs and returns

INVALIDATION_REQUIRED: no, for an engine-only or exchange-flatten change that does not replace the cache

INVALIDATION_REASON: unpublishing the completion because the engine object changed would hide a completion that still matches the cache the fragment displays. Adding a cache refresh or exchange read here is out of scope. The completion scope `LIVE_ACCOUNT_CACHE` already says it is cache evidence, not engine-position evidence.

PROPOSED_INSTRUMENTATION_POINT: none on the engine write. If the same operation also assigns a changed `real_account_snapshot`, E09–E11 apply.

PRODUCER_OWNER: not applicable for a new write

TEST_STRATEGY: an engine-only position change does not call the invalidation method and does not call account refresh. A cache assignment in the same test still follows E09–E11.

### E13 PAPER to LIVE Transition

CLASS: NOT_REQUIRED

ACTUAL_SOURCE_FILE: `backend/routers/mode.py`; runtime mode in `Bot/engine/execution_engine.py` and `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: `set_mode`; `BotManager.start`; `ExecutionEngine.set_config`

ACTUAL_CALL_PATH: `/set_mode` writes `config.TRADE_MODE` and `config.ALLOW_LIVE` only. It does not assign `engine.mode`, does not read metrics, and does not observe. Runtime mode is assigned in `ExecutionEngine.set_config` from `dry_run`, called by `BotManager.start` after `stop`, the session increment, and `begin_runtime_session`.

MM_INPUT_AFFECTED: the config write does not change fragment inputs. The start path changes the process that will next be observed, after the session baseline has already moved `_revision`.

INPUT_FIELDS_AFFECTED: none for `/set_mode`. Start replaces the engine and later observes through the new `engine.mode`.

EXISTING_OBSERVE_TRIGGER: none in `/set_mode`. Start does not observe inside `set_config`.

EXISTING_REVISION_CHANGE: `begin_runtime_session` increments `_revision` and does not note

INVALIDATION_REQUIRED: no additional write

INVALIDATION_REASON: `/set_mode` is a next-start capability switch, not the fragment mode authority. The running completion belongs to `engine.mode` through the observe branch. Start already unpublishes the previous completion before `set_config` assigns the new mode. A second bump would double-count that session boundary.

PROPOSED_INSTRUMENTATION_POINT: none. Do not treat `config.TRADE_MODE` or a UI `selectedMode` as a metrics mutation. The fragment has no mode field. `inputScope` remains the record of which input the completion used.

PRODUCER_OWNER: existing `begin_runtime_session`

TEST_STRATEGY: `/set_mode` does not change the metrics revision or the published timestamp. A start that changes `dry_run` unpublishes the old timestamp through the existing session increment and does not note inside `set_config`.

### E14 LIVE to PAPER Transition

CLASS: NOT_REQUIRED

The same functions and call path as E13, with `config.TRADE_MODE = "paper"` and `ALLOW_LIVE = False`, or `set_config` assigning `engine.mode = "paper"` when `dry_run` is true. The same session-baseline rule applies. No additional invalidation write.

### E15 Session Start

CLASS: NOT_REQUIRED

ACTUAL_SOURCE_FILE: `backend/bot_manager/bot_manager.py`; producer `backend/money_management/loss_authoritative_runtime_metrics.py`

ACTUAL_FUNCTION: `BotManager.start`; `AuthoritativeLossRuntimeMetricsState.begin_runtime_session`

ACTUAL_CALL_PATH: `start` -> `stop` -> lifecycle `STARTING` -> `session_id += 1` -> `begin_runtime_session`

MM_INPUT_AFFECTED: the new session clears the observed flag and replaces `as_of`. It is not an account-cache mutation.

INPUT_FIELDS_AFFECTED: session id, session trade count, `as_of`, `_revision`, `_observed`

EXISTING_OBSERVE_TRIGGER: none in `begin_runtime_session`

EXISTING_REVISION_CHANGE: yes, unless the same runtime-session authority is already installed

INVALIDATION_REQUIRED: no additional write

INVALIDATION_REASON: the existing increment already makes `evidenceRevision != revision`, so the old completion is omitted. The method must continue not to call the note. A repeated call for the same session returns without a second increment.

PROPOSED_INSTRUMENTATION_POINT: none

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState.begin_runtime_session`

TEST_STRATEGY: existing session-start tests remain the check that no new completion timestamp is written. The new invalidation method is not called here.

### E16 Session Stop

CLASS: REQUIRED

ACTUAL_SOURCE_FILE: `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: `BotManager.stop`; `BotManager._stop_locked`

ACTUAL_CALL_PATH: `stop` -> `_stop_locked` -> `_capture_account_snapshot` -> `engine.stop()` -> `self.engine = None` on the success path. Observe is not called.

MM_INPUT_AFFECTED: yes when the capture replaces `account_snapshot` or the engine is removed

INPUT_FIELDS_AFFECTED: PAPER `account_snapshot`; the engine object observe would read next

EXISTING_OBSERVE_TRIGGER: none

EXISTING_REVISION_CHANGE: none

INVALIDATION_REQUIRED: yes when a completion is currently published

INVALIDATION_REASON: stop can change the PAPER snapshot and remove the engine while the old completion still matches the metrics revision

PROPOSED_INSTRUMENTATION_POINT: after the capture replacement or the engine removal, call the revision-only invalidation. Do not add observe and do not write a new timestamp. A later stopped-PAPER maintenance observe may note only through the existing FRESH and `observation_valid` gate.

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: stop omits the old completion and leaves its timestamp value unchanged.

### E17 Session Restore

CLASS: NOT_REQUIRED

ACTUAL_SOURCE_FILE: `backend/bot_manager/bot_manager.py`; producer `backend/money_management/loss_authoritative_runtime_metrics.py`

ACTUAL_FUNCTION: `BotManager.initialize_money_management_runtime_metrics`; `AuthoritativeLossRuntimeMetricsState.restore`; `observe_stopped_paper_maintenance`

ACTUAL_CALL_PATH: `restore` runs first. The first restore increments `_revision`, sets source `RESTORED_*`, and does not note. A second restore on an initialized state returns without an increment. Stopped PAPER maintenance may then call `observe_stopped_paper_maintenance` and note only when freshness is `FRESH` and `observation_valid` is true.

MM_INPUT_AFFECTED: the first restore replaces period and peak fields from persistence. It is not a new account observation.

INPUT_FIELDS_AFFECTED: period PnL, peak, authority source, `as_of`, `_revision`

EXISTING_OBSERVE_TRIGGER: only the stopped PAPER maintenance branch

EXISTING_REVISION_CHANGE: first restore increments; observe_stopped increments again when it runs

INVALIDATION_REQUIRED: no additional write on `restore`

INVALIDATION_REASON: a new metrics object has no prior completion. The first restore increment unpublishes anything that was already stored. The maintenance note remains the only way to publish a new completion, and only under the existing gate.

PROPOSED_INSTRUMENTATION_POINT: none on `restore`. Do not call the note from `restore`.

PRODUCER_OWNER: existing `restore` and the existing maintenance note

TEST_STRATEGY: restore does not publish `mmObservationCompletedAt`. A FRESH valid stopped observation can publish one. A STALE or invalid stopped observation cannot.

### E18 Peak Equity Recovery

CLASS: NOT_REQUIRED

ACTUAL_SOURCE_FILE: `backend/money_management/loss_http_api.py`; producer `backend/money_management/loss_authoritative_runtime_metrics.py`

ACTUAL_FUNCTION: HTTP recovery handler; `AuthoritativeLossRuntimeMetricsState.apply_validated_peak_recovery`

ACTUAL_CALL_PATH: the handler persists a validated checkpoint, then calls `apply_validated_peak_recovery`

MM_INPUT_AFFECTED: the peak and `as_of` change. This is not an account-cache refresh.

INPUT_FIELDS_AFFECTED: `_peak_equity`, `_as_of`, `_revision`

EXISTING_OBSERVE_TRIGGER: none

EXISTING_REVISION_CHANGE: yes

INVALIDATION_REQUIRED: no additional write

INVALIDATION_REASON: the existing increment already unpublishes the completion. The method must not call the note and must not be replaced by the new invalidation method, because it also changes the peak and `as_of`.

PROPOSED_INSTRUMENTATION_POINT: none

PRODUCER_OWNER: `apply_validated_peak_recovery`

TEST_STRATEGY: peak recovery omits the completion and does not write a new timestamp.

### E19 Observation Failure

CLASS: REQUIRED

ACTUAL_SOURCE_FILE: `backend/money_management/loss_authoritative_runtime_metrics.py`; callers in `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: `observe`; `note_mm_observation_completed`; `_finalize_manual_close_money_management`

ACTUAL_CALL_PATH: observe can return with `observation_valid` false after incrementing `_revision`. It can also raise, including `close_event_id invalid`, after field writes and before the increment. The note returns without writing when the revision mismatches or `observation_valid` is not true. Manual close swallows observe exceptions.

MM_INPUT_AFFECTED: the failed observe may already have changed stored metrics fields

INPUT_FIELDS_AFFECTED: the fields observe assigned before the failure

EXISTING_OBSERVE_TRIGGER: this event is the observe

EXISTING_REVISION_CHANGE: yes when observe returns; no when it raises first

INVALIDATION_REQUIRED: yes on mutation paths before observe

INVALIDATION_REASON: a raise before the increment would otherwise leave the previous completion published. The note must not turn a failure into a new timestamp.

PROPOSED_INSTRUMENTATION_POINT: the pre-observe invalidation on E01–E07 and E16. The note gate stays unchanged. Failure does not call the note.

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: a raised observe after invalidation leaves the old timestamp unpublished. A returned invalid observation also leaves it unpublished and does not replace the timestamp.

### E20 Observation Partial Success

CLASS: REQUIRED

ACTUAL_SOURCE_FILE: `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: `BotManager._live_account_input_completeness`; `BotManager._note_mm_observation_completion`

ACTUAL_CALL_PATH: LIVE observe classifies the copied cache. `BALANCE_ONLY`, `POSITION_ONLY`, and `UNKNOWN` fail the note. An empty positions list with both sources, authentication, and `stale` false remains `COMPLETE` and is a flat read, not a partial success.

MM_INPUT_AFFECTED: yes when the cache projection is partial

INPUT_FIELDS_AFFECTED: the recorded side only

EXISTING_OBSERVE_TRIGGER: a later or same-callback observe

EXISTING_REVISION_CHANGE: observe increments when it returns; the note does not write

INVALIDATION_REQUIRED: yes when the partial cache assignment changed the MM projection

INVALIDATION_REASON: a partial cache must not inherit the previous completion. The note already refuses a non-complete scope.

PROPOSED_INSTRUMENTATION_POINT: E11 assignment rule, then the existing observe gate. Do not add a new completeness value.

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: `BALANCE_ONLY` and `POSITION_ONLY` omit the completion. A complete flat positions list can still note.

### E21 Metrics Revision Change

CLASS: NOT_REQUIRED

ACTUAL_SOURCE_FILE: `backend/money_management/loss_authoritative_runtime_metrics.py`; publication in `backend/bot_manager/owner_snapshot.py`

ACTUAL_FUNCTION: every `_revision += 1` path; `_copy_mm_observation_completion`

ACTUAL_CALL_PATH: publication compares `mm_observation_evidence_revision` with `revision`

MM_INPUT_AFFECTED: depends on the writer

INPUT_FIELDS_AFFECTED: `_revision`

EXISTING_OBSERVE_TRIGGER: not by the increment itself

EXISTING_REVISION_CHANGE: this event is that change

INVALIDATION_REQUIRED: no new mechanism

INVALIDATION_REASON: inequality already omits the four names. The note is the only writer that sets `evidenceRevision` to the current revision, and only after the success gate. The new invalidation method increments without moving `evidenceRevision`.

PROPOSED_INSTRUMENTATION_POINT: none beyond the method in D07. Do not reset `evidenceRevision` during invalidation.

PRODUCER_OWNER: existing publication rule

TEST_STRATEGY: any increment without a note removes the four names. The producer timestamp remains the old value.

### E22 Account Snapshot Source Change

CLASS: CONDITIONAL

ACTUAL_SOURCE_FILE: `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: `_prepare_real_account_snapshot_for_exchange`; `_refresh_real_account_snapshot`

ACTUAL_CALL_PATH: an exchange change increments `account_snapshot_generation`, clears the read client, and assigns `_empty_real_account_snapshot`, whose sources are null. A matching exchange keeps the current snapshot and may rewrite `generation` in place.

MM_INPUT_AFFECTED: yes when `balanceSource` or `positionSource` changes, including the empty-snapshot replacement

INPUT_FIELDS_AFFECTED: `balanceSource`, `positionSource`, and the cleared balance and positions on that empty snapshot

EXISTING_OBSERVE_TRIGGER: none

EXISTING_REVISION_CHANGE: none

INVALIDATION_REQUIRED: yes when the source fields change

INVALIDATION_REASON: the LIVE note requires both sources to be `KUCOIN_FUTURES_READ_ONLY`. An empty or changed source is no longer that observation.

PROPOSED_INSTRUMENTATION_POINT: the E09 projection comparison. A generation-only rewrite does not invalidate.

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: exchange switch omits the completion. Generation rewrite alone does not increment.

### E23 Account Snapshot Authentication Change

CLASS: CONDITIONAL

ACTUAL_SOURCE_FILE: `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: the cache `commit` path inside `_refresh_real_account_snapshot`

ACTUAL_CALL_PATH: `authenticated` is written on the snapshot that `commit` assigns. There is no separate authentication writer that changes the fragment without that assignment.

MM_INPUT_AFFECTED: yes when `authenticated` changes

INPUT_FIELDS_AFFECTED: `authenticated`

EXISTING_OBSERVE_TRIGGER: none in the writer

EXISTING_REVISION_CHANGE: none

INVALIDATION_REQUIRED: yes when the assigned value differs

INVALIDATION_REASON: the LIVE COMPLETE gate requires `authenticated is True`. A loss of authentication must not keep the previous completion.

PROPOSED_INSTRUMENTATION_POINT: same projection comparison. Do not add an authentication probe.

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: `authenticated` true to false omits the completion. A later observe does not note until the existing gate passes.

### E24 Account Snapshot Stale Change

CLASS: CONDITIONAL

ACTUAL_SOURCE_FILE: `backend/bot_manager/bot_manager.py`

ACTUAL_FUNCTION: `BotManager._mark_real_account_stale_if_needed`; refresh `commit`

ACTUAL_CALL_PATH: `_get_real_account_snapshot` calls `_mark_real_account_stale_if_needed`, which copies the snapshot, sets `stale` true when `lastSync` is older than `account_stale_after`, and always assigns the copy.

MM_INPUT_AFFECTED: yes only when `stale` or another MM field changes. The unconditional copy assignment is not itself a mutation.

INPUT_FIELDS_AFFECTED: `stale`

EXISTING_OBSERVE_TRIGGER: none

EXISTING_REVISION_CHANGE: none

INVALIDATION_REQUIRED: yes when `stale` changes

INVALIDATION_REASON: the LIVE COMPLETE gate requires `stale is False`

PROPOSED_INSTRUMENTATION_POINT: compare the MM projection before and after the assignment. A copy with the same projection does not increment.

PRODUCER_OWNER: `AuthoritativeLossRuntimeMetricsState`

TEST_STRATEGY: the age threshold flip omits the completion. A fresh copy with the same projection does not.

## D03 PAPER_MANUAL_ENTRY_DESIGN

Confirmed gap: `_manual_entry_locked` returns `MANUAL_ENTRY_FILLED` after `try_entry` without calling observe and without incrementing the metrics revision. The next observe is `on_update` in `BotManager.start`, and only while the observation authority still holds.

The design withdraws the old completion at the success return and does not add observe.

1. `try_entry` and the PAPER confirmation checks stay as they are.
2. On `MANUAL_ENTRY_FILLED` only, call `invalidate_mm_observation_evidence`.
3. The old timestamp remains stored. The owner fragment omits the four completion names.
4. The fragment numbers stay at the last observe until a later cycle observe. That lag is not a new completion and is not `CURRENT`.
5. Denied entry does not invalidate.
6. Manual trading control flow, quantity checks, and order construction are unchanged.

Until the next successful note, readers see the last valid metrics fragment without a completion clock. That is the safe state. This design does not refresh those numbers.

## D04 PAPER_AUTO_CLOSE_EMERGENCY_DESIGN

`on_update` already observes after `engine.on_price` when authority holds. `_manual_close_locked` observes only after a confirmed close. The paper emergency branch observes after `flatten_paper_position`, including an incomplete flatten. `reset_paper_capital` publishes and then observes.

Those observes are not removed. The missing guarantee is the gap before they return:

1. Detect the mutation from the existing signature, plus `latest_price` and `unrealized_pnl` for the market callback.
2. If those inputs changed and a completion is published, increment `_revision` without a new timestamp and without moving `as_of`.
3. Call the existing observe.
4. The existing note publishes a new timestamp only when its gate passes.
5. If the authority recheck returns, or observe raises, stop. The old timestamp stays unpublished. Do not write a replacement timestamp.

`reset_paper_capital` invalidates before `_publish_context_snapshot`, so that publish cannot carry the pre-reset completion. The capital math and the observe event name stay unchanged.

Same-callback success therefore has two revision increments: one invalidation and one observe. The published evidence revision is the observe revision. Callers that already increment inside observe do not get a third increment from session start, restore, or peak recovery.

## D05 LIVE_CACHE_INVALIDATION_DESIGN

The LIVE fragment input is `real_account_snapshot`, not `engine.actual_position`.

Assignment sites:

- `_prepare_real_account_snapshot_for_exchange` when the exchange changes and the empty snapshot is assigned
- `_refresh_real_account_snapshot` loading assignment and `commit` assignment
- `_mark_real_account_stale_if_needed`

Rule: if the MM projection differs, call the revision-only invalidation after the assignment. If it does not differ, do nothing. Do not call the exchange, do not add an account sync, and do not observe inside these methods.

A later cycle observe re-enables publication only when the existing LIVE COMPLETE gate passes on the copied snapshot. Partial, unauthenticated, stale, or sourceless caches do not note.

LIVE emergency flatten and an engine-only position change do not invalidate by themselves. They also do not gain a cache refresh in this design. The published scope remains `LIVE_ACCOUNT_CACHE`.

## D06 MODE_TRANSITION_DESIGN

Two different writes exist.

Config and UI selection: `backend/routers/mode.py` `set_mode` writes `config.TRADE_MODE` and `config.ALLOW_LIVE`. Status payloads also carry `selectedMode`. Neither write is the observe branch selector. Neither updates metrics. No invalidation is added. The old completion is not evidence of the newly selected config mode; its `inputScope` still names the input that was observed.

Runtime mode: `BotManager.start` calls `ExecutionEngine.set_config`, which sets `engine.mode` from `dry_run` after `begin_runtime_session`. That session method already unpublishes any prior completion and does not note. The next completion appears only after a later observe passes the gate for the new engine mode. No second invalidation is added in `set_config`. Trading-mode behavior is unchanged.

Mismatch rule: do not publish the completion as evidence that `config.TRADE_MODE`, `selectedMode`, and `engine.mode` agree. The completion is published only under the existing revision, completeness, and scope gate. If a future path assigns `engine.mode` outside `start`, that path must call the revision-only invalidation before publication. The current code has one `set_config` caller, and it is inside `start` after the session increment.

## D08 FAILURE_SEMANTICS

The timestamp may remain in producer memory in every row. Publishing it means copying the four names into the owner fragment. Runtime status stays `UNKNOWN` when a fragment exists and `UNAVAILABLE` when it does not. None of these rows produce `CURRENT`. Re-observation means a later observe or stopped observe that passes the existing note gate.

| Case | Keep timestamp value | Publish timestamp | Evidence status | Re-observation |
| --- | --- | --- | --- | --- |
| Observation failed and observe incremented | yes, old value | no | UNKNOWN or UNAVAILABLE | required before a new completion |
| Observation raised before its increment, after pre-observe invalidation | yes, old value | no | UNKNOWN or UNAVAILABLE | required |
| Partial LIVE observation | yes, old value | no | UNKNOWN or UNAVAILABLE | required; note stays closed unless COMPLETE |
| Input changed during observation, invalidation already incremented | yes, old value | no until the note writes the new value for the new revision | UNKNOWN while unpublished | the in-flight success note is the re-observation |
| Input changed after a published observation | yes, old value | no after the invalidation increment | UNKNOWN or UNAVAILABLE | required |
| Snapshot replaced with a changed MM projection | yes, old value | no | UNKNOWN or UNAVAILABLE | required |
| Source became stale | yes, old value | no | UNKNOWN or UNAVAILABLE | required; LIVE gate remains `stale is False` |
| Authentication lost | yes, old value | no | UNKNOWN or UNAVAILABLE | required; LIVE gate remains `authenticated is True` |
| Config mode differs from engine mode | yes | yes only if the existing revision gate still matches | UNKNOWN | not required for a config-only change |
| Runtime mode changed through start | yes, old value | no, because session start incremented revision | UNKNOWN or UNAVAILABLE | required under the new engine mode |
| Revision mismatch | yes, old value | no | UNKNOWN or UNAVAILABLE | required; mismatch itself is not CURRENT |

History and publication stay separate. The producer may retain the old datetime. The owner snapshot, runtime evidence, and canonical context do not receive it as the current completion while the revisions differ.

## D09 OWNER_SNAPSHOT_MAPPING

No owner-snapshot code change is required for the omission rule. `_copy_mm_observation_completion` already returns before writing the four names when the evidence revision does not equal `revision`.

Minimal published form after a new completion remains the existing four names:

- `mmObservationCompletedAt`
- `inputCompleteness`
- `inputScope`
- `evidenceRevision`

Invalidation does not add an invalidation flag, an invalidation reason, or an invalidation timestamp to the fragment. The absence of the four names, while the metrics fragment itself is still present, is the invalidation evidence. `producerObservedAt` continues to be `as_of` and is not a completion clock.

Operator-only evidence stays out of the public view. `build_public_context_view` does not copy runtime evidence.

## D10 RUNTIME_EVIDENCE_MAPPING

`runtime_evidence._judge` stays unchanged. A present money-management fragment without `freshnessPolicy` is `UNKNOWN`, whether or not the completion names are present. A missing fragment is `UNAVAILABLE`.

The completion names are data inside the fragment. They do not change `runtimeStatus`. Advisor and Supervisor both read the canonical context through `load_shared_operator_context`. They do not receive a second evidence channel. `authority` remains `NONE`. `tradingControl` remains `FORBIDDEN`.

## D11 SECURITY_BOUNDARY

- The invalidation method reads no account and places no order.
- No exchange API and no LIVE account sync are added.
- Manual entry, manual close, emergency flatten, and `set_mode` keep their current control decisions.
- The new call sits after a confirmed mutation or a changed cache projection. It does not decide whether the mutation is allowed.
- No secret, credential, or operator-only payload is added to the fragment or the public view.
- No freshness policy, TTL, staleness threshold, or execution authority is added.
- The completion clock and the revision mismatch do not grant `CURRENT` and do not grant trading control.
- The known F01–F09 failures stay untouched. F01–F03 are PAPER handoff failures. F04–F05 are stopped FLAT PAPER observations with `observation_valid` false. F06–F09 are `RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL`. They were classified `PRE_EXISTING_FAILURE` in F1.9. This design does not fix them and does not require a new regression run for them.

## D12 IMPLEMENTATION_FILE_MAP

Future implementation, not this task:

| File | Change |
| --- | --- |
| `backend/money_management/loss_authoritative_runtime_metrics.py` | Add `invalidate_mm_observation_evidence` under the D07 rule. Do not change `note_mm_observation_completed`, `observe`, `begin_runtime_session`, `restore`, or `apply_validated_peak_recovery`. |
| `backend/bot_manager/bot_manager.py` | Add the wrapper. Call it from `on_update` after a detected `on_price` input change and before observe; from `_manual_entry_locked` on confirmed fill; from `_manual_close_locked` before the finalizer when the close committed; from the paper emergency branch when the signature changed; from `reset_paper_capital` before publish; from `_stop_locked` after snapshot replacement or engine removal; from LIVE cache assignment when the MM projection changed. |
| `backend/bot_manager/owner_snapshot.py` | No change. The existing revision gate is the publication rule. |
| `backend/context/runtime_evidence.py` | No change. |
| `backend/context/context_views.py` | No change. Public view stays free of runtime evidence. |
| `backend/routers/mode.py` | No change. |
| `Bot/engine/execution_engine.py` | No change. |
| `backend/money_management/loss_http_api.py` | No change. |

Do not edit the canonical main worktree. The sixteen paths that differ from `origin/main` are `MAIN_ONLY` and are not implementation files for this design.

## D13 TEST_PLAN

The next implementation task adds tests. This design task does not add or run them. The existing nine pre-existing failures are not part of the new test requirement.

Future tests:

1. Producer invalidation keeps the timestamp, `as_of`, and equity, increments revision once, and a second call does not increment.
2. Owner snapshot omits the four names after invalidation and publishes a new timestamp only after a successful note at the new revision.
3. PAPER manual entry success invalidates and does not call observe. A denied entry does not invalidate.
4. PAPER auto entry, auto close, and price update invalidate after the detected mutation and before observe. Success notes a new timestamp. Authority miss or observe exception does not note.
5. PAPER manual close and paper emergency flatten follow the same order.
6. Capital reset publish omits the old completion. Stop omits it and does not note.
7. LIVE cache projection change invalidates without calling the exchange. An identical copy, loading-only change, or generation-only change does not.
8. Partial, stale, and unauthenticated cache results do not note.
9. Engine-only LIVE position change and LIVE emergency flatten do not invalidate and do not refresh the cache.
10. `/set_mode` does not change revision or the timestamp. Start still unpublishes through `begin_runtime_session` and does not note in `set_config`.
11. Restore and peak recovery still do not note.
12. Runtime status remains `UNKNOWN` with a fragment and `UNAVAILABLE` without one. `CURRENT` is absent. The public view still has no runtime evidence.
13. Advisor and Supervisor attachments keep `authority` `NONE` and `tradingControl` `FORBIDDEN`.

## D14 REMAINING_GAPS

- After PAPER manual entry, the fragment numbers stay at the previous observe until the next authorized cycle observe. The completion clock is unpublished. This design does not add the missing observe.
- LIVE `engine.actual_position` and LIVE emergency flatten can diverge from `real_account_snapshot`. The fragment and its completion describe the cache only. Closing that divergence would require an account sync, which is out of scope.
- A market callback that mutates inputs and then loses observation authority unpublishes the old completion and does not create a new one. The fragment numbers can lag until a later authorized observe.
- Invalidation plus a following observe increments `_revision` twice. Tests that assume one increment per cycle need to expect that pair on the instrumented paths.
- Config `TRADE_MODE` can differ from `engine.mode` until the next start. The completion is not a mode-agreement signal.
- F01–F09 remain pre-existing and unfixed.
- No row in the matrix is `UNKNOWN`. The remaining items are boundaries, not unidentified producers.

## D15 NEXT_IMPLEMENTATION_TASK

NEXT_RECOMMENDED_TASK: BB_MM_F2_INVALIDATION_INSTRUMENTATION_IMPLEMENTATION

This design task does not start that implementation.

BLOCK_REASON: none

DEPENDENCY: F1 producer, owner snapshot, and runtime evidence at `f6ba7bfb7447d2bed3d6a84061303947e8d0c157`. The implementation must preserve the note gate and the publication gate in D01.

RESUME_CONDITION: start the implementation task in a new worktree from this design commit. Do not implement it inside this design pass.

## Canonical reconciliation

hostname: `vmi3480936`

Design worktree pwd at preflight: `/home/joe4410joe/tradingai_prod_v1.worktrees/ai-mm-invalidation-design`

Canonical HEAD and `origin/main`: `f344864344b0b99a598f674b3e2e4a367bc9fb25`

`git cat-file -t f6ba7bfb7447d2bed3d6a84061303947e8d0c157`: commit

merge-base of this branch and `origin/main`: `39273a115637edaba42ea49bde732f1ae6436399`

The canonical worktree is dirty with `frontend/dist/index.html`, untracked docs, dist backups, and other untracked files. Those entries were not modified. Existing worktrees were listed and left in place. This branch was created only because `design/ai-mm-invalidation-instrumentation` and its worktree were absent.

`git diff --name-status HEAD...origin/main` shows sixteen paths. `git diff --name-only 39273a115637edaba42ea49bde732f1ae6436399 HEAD` for those paths is empty, so this branch did not edit them.

| Path | Class |
| --- | --- |
| `Bot/engine/execution_engine.py` | MAIN_ONLY |
| `backend/api/money_management.py` | MAIN_ONLY |
| `backend/money_management/loss_execution_integration.py` | MAIN_ONLY |
| `backend/money_management/loss_http_api.py` | MAIN_ONLY |
| `backend/runtime/cycle_diagnostics.py` | MAIN_ONLY |
| `backend/supervisor/runtime_snapshot_adapter.py` | MAIN_ONLY |
| `backend/supervisor/snapshot_builder.py` | MAIN_ONLY |
| `frontend/src/components/runtime/TradingDecisionCard.diagnostics.test.js` | MAIN_ONLY |
| `frontend/src/components/runtime/TradingDecisionCard.jsx` | MAIN_ONLY |
| `frontend/src/components/runtime/tradingCycleModel.js` | MAIN_ONLY |
| `frontend/src/components/runtime/tradingCycleModel.test.js` | MAIN_ONLY |
| `frontend/src/styles/dashboard.css` | MAIN_ONLY |
| `tests/test_contract_quantity_projection_repair.py` | MAIN_ONLY |
| `tests/test_manual_cycle_diagnostics.py` | MAIN_ONLY |
| `tests/test_money_management_execution_entry_preview.py` | MAIN_ONLY |
| `tests/test_paper_trade_pipeline.py` | MAIN_ONLY |

No path is `CONFLICTING` or `SHARED_PATH_REVIEW_REQUIRED`. The BB commits on this branch are not on `origin/main`; they are `BB_ONLY` relative to main and `ALREADY_CANONICAL` for this design base. No merge and no cherry-pick was performed.

Focus check: BotManager, money-management runtime metrics, owner snapshot, runtime evidence, and canonical AI context on this base are the F1 contract. Trading mode, PAPER position mutation, and LIVE account cache were read at the functions named in the matrix. Main's edits to the engine, loss HTTP API, and supervisor snapshot files were not brought into this branch and do not block the design.

## Freshness boundary

This design depends on the existing revision publication gate and the existing note gate. It does not define a TTL, a time-based `CURRENT` rule, a staleness threshold, a risk-evaluation freshness rule, or an execution-authority rule. A completion timestamp plus an invalidation revision does not make evidence `CURRENT`.

## Acceptance matrix

| ID | Item | Result |
| --- | --- | --- |
| A01 | Actual producer identified | PASS |
| A02 | Existing observation contract preserved | PASS |
| A03 | PAPER manual entry gap covered | PASS |
| A04 | PAPER auto entry covered | PASS |
| A05 | PAPER auto close covered | PASS |
| A06 | PAPER price update covered | PASS |
| A07 | PAPER manual close covered | PASS |
| A08 | PAPER emergency flatten covered | PASS |
| A09 | LIVE cache update covered | PASS |
| A10 | LIVE partial cache covered | PASS |
| A11 | LIVE engine position difference covered | PASS |
| A12 | Mode transition covered | PASS |
| A13 | Session start / restore covered | PASS |
| A14 | Revision strategy defined | PASS |
| A15 | Failure semantics defined | PASS |
| A16 | Owner snapshot mapping defined | PASS |
| A17 | Runtime evidence mapping defined | PASS |
| A18 | Advisor / Supervisor boundary preserved | PASS |
| A19 | Public isolation preserved | PASS |
| A20 | No false CURRENT | PASS |
| A21 | No trading logic change | PASS |
| A22 | No account sync | PASS |
| A23 | No real orders | PASS |
| A24 | Implementation file map complete | PASS |
| A25 | Test plan complete | PASS |
| A26 | Canonical reconciliation complete | PASS |

A11 is PASS because the design locates the engine and emergency writes, states that they are not fragment inputs, and refuses a cache refresh. A12 is PASS because config `/set_mode` and runtime `engine.mode` inside `start` are separated, and the session baseline already unpublishes the old completion.

## Verdict

BB_MM_F2_INVALIDATION_DESIGN_PASS

The fragment input mutations have identified write points. The producer update is one revision increment that does not move the old timestamp and does not write a new one. Successful re-observation continues to use the F1 note. No authority boundary has to be crossed.
