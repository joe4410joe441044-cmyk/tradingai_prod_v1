# PAPER/LIVE monitoring backend contract — Phase 2

Base: `653db4e2c23f0a7e7915f3bdc448394598be06c9`.
Branch: `feature/mm-paper-live-view-authority`.

## Authority and event identity

`MonitoringAuthority` explicitly defines PAPER, LIVE and UNKNOWN. The single
mapping in `monitoring.py` consumes `LossRuntimeMetrics.accounting_authority_source`:
PAPER_RUNTIME_EQUITY → PAPER; REAL_LIVE_ACCOUNT_EQUITY → LIVE; everything else →
UNKNOWN. Neither current runtime mode nor event amounts identify history.

New timeline JSON adds these top-level fields:

| Field | Meaning |
| --- | --- |
| authority | Monitoring authority derived from the stored accounting source |
| accountingAuthoritySource | Accounting source of the observation |
| accountScope | Persisted MM state scope, only when its authority matches the observation |
| runtimeInstanceId | Runtime identity from the observed metrics |
| sessionId | Session identity from the observed metrics |
| accountingRebaseId | Last recorded rebase in matching-authority MM state, if available |
| capturedAt | Metrics observation time, distinct from the timeline event timestamp |
| sourceRevision | Revision of the observed metrics |
| realizedPnlSemantics | PAPER_ENGINE_REPORTED_REALIZED_PNL, REALIZED_PNL_TODAY, or UNSPECIFIED |

`accountingRebaseId` is descriptive metadata, never rebase authorization. Missing
scope/rebase/session information stays null. No additional epoch is invented.
The runtime hook passes its existing lifecycle snapshot state to the recorder.
Runtime, loss/lock transitions, risk, exposure, positions and diagnostics share
the producing observation's identity. Configuration and recovery events copy the
identity and capture time alongside their existing copied metrics; their event
state describes the action, not a new financial observation. Application startup
has no financial observation and is UNKNOWN. These action events do not refresh
monitoring snapshots.

## Legacy policy and history API

`GET /api/money-management/history?authority=PAPER|LIVE|UNKNOWN|ALL`.
Default is ALL, retaining existing audit continuity within the existing 5,000-event
retention window. PAPER and LIVE require positively identified accounting sources;
UNKNOWN includes legacy/unrecognized sources. A mode/authority label alone is
insufficient proof. No read-time relabeling based on current runtime occurs.

No migration, amount-based inference, deletion, or broad historical rewrite is
introduced. Existing timeline retention behavior is unchanged. The legacy
7.91836966 equity / 100.0805801773 peak / approximately 92.088% drawdown remains in
ALL and UNKNOWN, excluded from PAPER and LIVE series. It never populates a snapshot.

All filters apply before page slicing. Ordering is descending `(sequence, eventId)`.
`nextCursor` is an opaque `sequence:eventId` string; pass it unchanged as `before`.
`after` also accepts this composite format. Original numeric cursors remain accepted
with their original strict sequence inequality semantics. Composite cursors repair
loss at duplicate sequence boundaries without rewriting sequences. Retention and
concurrent new appends retain existing behavior; this is not a frozen multi-page
transaction. Clients must keep the same filters across pages.

## Read-only monitoring API

`GET /api/money-management/monitoring?viewAuthority=PAPER|LIVE`.
The parameter is required; other values return 422. Missing boundary returns 503.
No snapshot returns HTTP 200 with availability/semantics/freshness UNAVAILABLE,
null dataAuthority/source/asOf/snapshot. No hidden authority fallback exists.

Responses provide viewAuthority, dataAuthority, source, asOf, availability,
semantics, freshness, staleAfterSeconds, snapshot, and fieldCategories.

Both PAPER and LIVE snapshots are independently persisted in
`money_management_monitoring.json`, beside the timeline, with schemaVersion 1.
Only runtime observations with recognized sources update them. They survive
restart, opposite-authority updates and timeline retention. Older observations
cannot replace newer observations. Writes use a private temporary file, file
fsync, atomic replace, and directory fsync. Snapshots are monitoring outputs;
nothing reads them to authorize execution or establish accounting baselines.
The store follows the timeline's single-process ownership convention.

Each snapshot carries the event identity above, recordedAt, metrics, riskState,
lifecycleContext, metricQuality, dailyPnl, weeklyPnl and monthlyPnl. Metrics include
equity, availableCapital, peakEquity, drawdownAmount, drawdownPercent, realizedPnl,
unrealizedPnl, currentRiskAmount, reservedRiskAmount, riskLimitAmount,
riskBudgetRemaining, riskUtilization, openExposure, exposureLimit,
exposureUtilization, positionCount and openPositionState. These are the existing
MM metrics/calculations. Missing observation fields remain null; existing derived
zero risk for explicitly flat/no-pending-order observations is unchanged.
`exposureLimit` is configured percentage, not an absolute currency amount.

This durable endpoint conservatively reports semantics LAST_KNOWN for every
available snapshot, even when the same runtime may currently be active. Freshness
is LAST_KNOWN through five minutes, STALE beyond five minutes or for a future capture
time. CURRENT is reserved for an independently validated active observation; this
endpoint never claims it. Lifecycle and risk labels are captured context, not
present execution permissions. The data remains readable while the bot is stopped.
A server with its MM boundary unavailable still returns 503.

No current PAPER account or authenticated LIVE account values are merged into a
snapshot. No real account provider is called. There is no start/stop, mode, Auto
Trade, Loop, governance, emergency, entry-gate, order or rebase dependency.

## PnL and analytics / Phase 3

The producer in `BotManager._observe_money_management_runtime_metrics` passes PAPER
snapshot.realizedPnl and LIVE snapshot.realizedPnlToday to the authoritative metric
source; `loss_runtime_metrics_source.py` preserves these values. PAPER's engine PnL
accumulates closed-position PnL over the engine's lifetime/reset boundary; it is
not promised to be lifetime account PnL. LIVE is the account's reported today value.
The timeline does not accumulate either value. Phase 3 must replace the universal
“Cumulative Realized PnL” label with period/source-aware labels (LIVE: “Realized PnL
Today”; PAPER: “Engine Reported Realized PnL”). UNKNOWN is unspecified.

Phase 3 must explicitly request PAPER/LIVE history for performance series, preserve
ALL as the Runtime History default, show capture time and freshness, and use the
new monitoring endpoint without changing runtime configuration. The frontend analytics loader accepts composite cursors as non-visible contract
plumbing; no visible controls change in Phase 2. The visible switch is a separate task.

`fieldCategories` distinguishes observed MM metrics from configured exposureLimit
and unavailable historicalMaximumDrawdown/projectionHistory. Risk limits and
utilization use the configuration attached to the observation. They are not
historical performance aggregates. Configuration maximum drawdown remains a limit;
Loss Period and dedicated Projection History are not invented. Metric quality and
lifecycle context here belong to the captured observation. Current governance
permission must never be labeled historical projection performance.

## Verification and review limitation

Required focused regression command:

```sh
python3 -m pytest tests/test_money_management_monitoring_authority.py tests/test_money_management_timeline.py tests/test_money_management_api.py tests/test_money_management_loss_accounting_rebase.py tests/test_money_management_loss_runtime_store.py tests/test_money_management_loss_runtime_authority_transition.py tests/test_money_management_loss_runtime_hook.py tests/test_money_management_loss_runtime_evaluation_bridge.py tests/test_money_management_loss_authoritative_runtime_metrics.py -q
```

Result: **135 passed, 38 subtests passed**. Includes 17 new monitoring tests covering
persistence/reload/API, UNKNOWN/~92% isolation, all authority filters, duplicate
sequences, retention, freshness, out-of-order observations, no runtime dependency,
PnL semantics, scope/rebase identity, and atomic replacement failure.

Additional broad check: `python3 -m pytest tests/test_money_management*.py -q`:
**407 passed, 3 failed, 131 subtests passed**, before the final three new tests were
added. All three failures are in the unchanged execution integration module:

- SharedExecutionBoundaryTests.test_live_governance_preflight_precedes_mm_and_submit
- SharedExecutionBoundaryTests.test_paper_and_live_allow_submit_once (LIVE subtest)
- SharedExecutionBoundaryTests.test_position_change_after_allow_is_rechecked_before_submit

An untouched `git archive 653db4e2c23f0a7e7915f3bdc448394598be06c9` export reproduced
all three using `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider
tests/test_money_management_execution_integration.py -q`:
**22 passed, 3 failed, 29 subtests passed**. LIVE_ORDER_ENTRY_DISARMED prevents the
mock entry path expected by these existing fixtures. This feature does not repair
or bypass that LIVE-owned guard. The full broad suite is not green; required
focused MM regressions are green. No tests were weakened or skipped.

Safety: VIEW_READ_MUTATES_RUNTIME=NO; VIEW_READ_MUTATES_EXECUTION_AUTHORITY=NO;
VIEW_READ_TRIGGERS_ACCOUNTING_REBASE=NO; VIEW_READ_CAN_CREATE_ORDER=NO.
LEGACY_AMOUNT_BASED_INFERENCE=NO; LEGACY_DESTRUCTIVE_REWRITE=NO.
No real/paper trading operations, production mutation, service restart, main
integration or push are performed. Test order paths use existing mocks only.

Frontend verification:

```sh
node --test frontend/src/features/money-management/analytics/moneyManagementAnalytics.test.js frontend/src/features/money-management/contracts/moneyManagementContracts.test.js
```

Result: **24 passed, 0 failed**. Original numeric cursors remain covered; the new
composite-cursor test preserves both events sharing sequence 52. `git diff --check`
also passed before commit.
