# FINAL REPORT

TASK=TRADINGAI-WORK-D-MM-FUTURES-POLICY-AMENDMENT-RANGE-REPAIR-2

VERDICT=PASS_MM_FUTURES_POLICY_AMENDMENT_AND_RANGE_REPAIR_READY_FOR_INTEGRATION

NEXT_ACTION=RETURN_TO_CHATGPT_FOR_CONTROLLED_CANONICAL_INTEGRATION

## Scope and continuation

Resumed from the operator-confirmed canonical base
`12e28ec8340b5cc7de294d55e16f0c8bc33d46d1` in
`/home/joe4410joe/tradingai_prod_v1.worktrees/manual-live-mm-futures-range`,
branch `fix/manual-live-mm-futures-range`. The prior Safety Gate was accepted,
not repeated. Completed the two requested document reads before amending policy.
The original instruction's Section 25 template was not available in this
conversation or located in the searched documents; this report uses the supplied
verdict/next-action fields and records evidence explicitly. Full conformance to
unavailable Sections 5–25 cannot be independently asserted.

## Approved policy and implementation

ADD_CAPITAL=NO
DEFAULT_RISK_PER_TRADE=0.5%
STANDARD_RISK_POLICY_MAX=1%
ABSOLUTE_CONFIGURABLE_RISK_MAX=5%
ABSOLUTE_CONFIGURABLE_EXPOSURE_MAX=500%
EXPOSURE_SEMANTICS=GROSS_NOTIONAL_DIVIDED_BY_EQUITY

Amended the canonical Master Specification and normative Additions. Risk above
1% through 5%, and exposure above 100% through 500%, remain explicit operator
leveraged-futures configurations. No automatic increase or new elevated default.

Backend configuration model and HTTP validators accept the approved ranges and
reject invalid values, absolute-cap violations, and single-symbol > total
exposure. Simulation input validation accepts the same elevated configuration;
its calculation is unchanged. Frontend validation, error text and policy
explanations match. Trade Settings numeric risk input has maximum 5 and fallback
0.5. Operation Preparation includes elevated choices and retains its existing
arbitrary-current-value preservation; regression covers 2.1/180, 2.37/183 and
5/500 in the controls and Final Preparation display, without emitting a change.

Defaults remain risk 0.5%, single 10%, total 20%, maximum position notional 100,
maximum leverage 5. Order sizing mathematics, exposure calculation, position cap,
leverage enforcement and minimum-quantity behavior are unchanged.

## Deterministic current-capital regression

| Input | Value |
| --- | --- |
| Equity / available | 7.91836966 / 7.91836966 |
| Price | 1.39938 |
| Contract multiplier / minimum / step | 10 / 1 / 1 |
| Stop loss / leverage | 1% / 5 |
| Trade risk / MM risk | 2.1% / 2.1% |
| Single / total exposure | 180% / 180% |
| Maximum position notional | 100 |
| Risk budget | 0.16628576286 |
| Single / total notional capacity | 14.253065388 / 14.253065388 |
| Calculated contract quantity | 1 |
| Base quantity / notional | 10 / 13.9938 |
| Required margin | 2.79876 |

CALCULATED_CONTRACT_QTY=1

The existing ExecutionEngine sizing authority also returns 1 with an explicit
fixture taker fee of 0.06% per side (0.12% round trip). This is a deterministic
test assumption, not a newly fetched exchange fee. Exchange account/contract
responses are mocked; network requests are forbidden by the test fixture and
no create_order call occurs in this regression.

DEFAULT_CALCULATED_CONTRACT_QTY=0 / REJECTED
DEFAULT_REJECTION=NO_VALID_QUANTITY_FOR_RISK_POLICY

Default risk 0.5%, single 10%, total 20% still rejects. Increasing only risk or
only exposure also rejects; neither constraint overrides the other.

## Validation evidence

- Backend focused tests: 122 passed, 40 subtests passed.
  Files: test_mm_futures_policy_range.py, test_money_management_models.py,
  test_money_management_api.py, test_money_management_simulation.py,
  test_canonical_order_sizing.py.
- Frontend focused tests: 330 passed, zero failures.
  Files: moneyManagementContracts.test.js,
  moneyManagementInteractionViewModel.test.js,
  operationPreparationModel.test.js, OperationPreparation.test.js,
  BotControl.test.js, MoneyManagementInteractionCards.test.js.
- Vite build: PASS, output only to
  `/tmp/tradingai-mm-futures-range-build-20261014`; non-blocking chunk-size warning.
- `git diff --check`: PASS.
- Logs: `/tmp/mm-futures-backend-tests.log`,
  `/tmp/mm-futures-frontend-tests.log`, `/tmp/mm-futures-build.log`.
- Existing frontend dependencies were read through an ignored node_modules
  symlink created in this dedicated worktree; no dependency installation.

## Operational boundary

REAL_ORDER_AUTHORIZATION=NONE
PRODUCTION_INTEGRATION=NOT_PERFORMED
DEPLOY=NOT_PERFORMED
PRODUCTION_SETTINGS_CHANGE=NONE
BACKEND_RESTART=NOT_PERFORMED
NGINX_RELOAD=NOT_PERFORMED
SAVE_SETTINGS=NOT_PERFORMED
START_RUNTIME=NOT_PERFORMED
ARM=NOT_PERFORMED
BUY_SELL=NOT_PERFORMED
MARGIN_MODE_CHANGE=NONE
API_PERMISSION_CHANGE=NONE
REAL_ORDER_SUBMISSION=NONE

All configuration updates and UI actions in tests use isolated in-memory
fixtures/mocks. Production dist, dist backups, untracked files and other
worktrees were not cleaned, reset, restored, stashed, deleted or edited.
The commit is local to the dedicated branch, with no push or main integration.
