# Work D — Manual LIVE authority and Governance repair

Task: WORK-D-MANUAL-LIVE-AUTHORITY-GOVERNANCE, 2026-09-22.
Base: 1c3c623a15b10aa45cbefb766869d042d43735ed.

## Problem and ownership

The shared LIVE readiness gate treated `governance_state.execution_enabled`
(Auto Trade) as a requirement for human orders. Manual admission separately
called MM and ExecutionEngine without a canonical Governance decision.

- Automated decision: strategy output (`executionAllowed`, direction), passed
  through TradingRuntime/ExecutionRuntime. This does not authorize human intent.
- Runtime Loop: BotManager `loop_state`, start/stop loop lifecycle.
- Auto Trade: BotManager `set_execution_enabled`, mirrored in
  `governance_state.execution_enabled`. Enabling it requires a running Loop.
- Governance: GovernanceRuntime. Its strategy-facing `process_governance`
  validates strategy intent, then delegates to shared `evaluate_entry` rules.
- LIVE ARM: BotManager `set_live_order_entry_authority`, then ExecutionEngine;
  explicit operator session/CSRF protected endpoint, independent of automation.
- Human authority: authenticated Manual request, backend control revision,
  runtime/mode/symbol/Emergency/pending validation, serialized manager reservation.
- Final LIVE gate: ExecutionEngine validates manager-returned origin context,
  MM-bound intent, local risk, LIVE permissions and exchange readiness.

`execution_enabled` remains an automation switch, not a Governance ALLOW result.
The change separates its formerly conflated use in universal LIVE readiness.

## Contract

Manual entry: authenticated request -> manager admission -> MM preflight ->
canonical Governance decision -> manager final authority revalidation (including
current Governance) -> ExecutionEngine -> LIVE adapter.

The manager binds request ID, trace, side, MM quantity, symbol, runtime identity,
control revision and Governance result to the reservation. A frontend origin
label cannot create that reservation. Missing callbacks, unknown LIVE origins,
unreserved Manual signals and missing Governance approval fail closed.
Approval is cleared on every exit; MM's existing five-second validity remains.

The shared Governance rules retain Emergency and no-trade-zone denials.
Automated entry additionally requires Auto Trade. The existing strategy-facing
API delegates to the same rules. No suspension/risk policy is invented: existing
MM and local-risk denials remain independently mandatory.

| Entry source | Control | Runtime | Loop | Auto Trade | LIVE ARM | MM | Governance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BOT | BOT | RUNNING | ON | ON | ON | ALLOW | ALLOW |
| Human | MANUAL | RUNNING | OFF permitted | OFF permitted | ON | ALLOW | ALLOW |

BOT admission explicitly rechecks Loop and Auto Trade. Manual control still
blocks automatic BOT entry. ARM remains persistent authority, not a one-order
capability. It never creates an order or automatically enables automation.

The read-only readiness projection identifies backend control authority and
preserves the independent ARM check while reporting Auto Trade accurately.
A readiness projection alone cannot authorize an order.

## Request identity and unchanged behavior

`expectedMode`, `expectedSymbol`, and integer `expectedControlRevision` are
required at both HTTP schema and manager boundaries. Existing frontend sends
these fields; absent context now fails closed. Revision also participates in
idempotent request identity. Frontend source was not changed.

Close classification remains LONG+SELL=CLOSE_LONG and SHORT+BUY=CLOSE_SHORT,
with no reversal. Close does not require a new-entry MM/Governance approval;
existing Emergency, pending, position and exchange reconciliation still apply.
No sizing, leverage, SL, risk, minQty, rounding or exchange adapter code changed.
The separate live sizing blocker remains unresolved.

## Validation

Final combined command covers 17 relevant modules: Manual LIVE contract, PAPER
entry/close, D4, authenticated D6, execution control, operation authentication,
LIVE authority/normal close, runtime mode guard, LIVE start, MM execution guard,
MM Governance projection/dispatcher, MM execution integration, LIVE leverage,
LIVE environment, LIVE status consistency, and PAPER manual exit grace.

Result: **336 passed, 43 subtests passed**, with existing deprecation warnings.
All exchange submissions in tests use mocked boundaries. Tests ran in the
isolated repair worktree without Production credentials or runtime startup.

Additional legacy `test_exchange_live_status.py` comparison:
original Production base: 74 failed, 225 passed, 289 subtests passed;
repair: exactly the same 74 failed test/subtest identities, no additions or
removals. These pre-existing failures involve obsolete mocked control endpoints
and stopped-PAPER snapshot expectations; they are not repaired here.

Lower-level MM/leverage fixtures now explicitly model trusted BOT admission;
Manual fixtures carry required identity. The stale-MM test now expires approval
inside a real Manual reservation instead of bypassing the authority owner.

No Production ARM, BUY/SELL, order submission/cancellation, sizing change or
funding action is part of this repair. Backend restart is authorized deployment;
post-restart runtime must be left STOPPED for a fresh operator START.
