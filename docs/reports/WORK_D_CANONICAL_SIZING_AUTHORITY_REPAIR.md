# WORK-D-SIZING-1: Canonical entry sizing repair

Base: `51810083b6027c29c02625928bf6e84b3fd59f13`.
Implementation branch: `fix/manual-live-sizing-authority`.

The engine previously treated balance × risk percent as notional, ignored SL
in sizing, and raised candidates to the exchange minimum. The UI's default
100 USDT fixed request was independently named a cap, even though the MM cap
is a separate policy field. Adapter rounding could increase approved size.

BOT and MANUAL now use `money_management/order_sizing.py` through the same
ExecutionEngine preview/admission path. LIVE order capital is fresh authenticated
KuCoin USDT equity and available balance. PAPER order capital is its portfolio
equity/balance. Performance/reference and PAPER compounding calculations retain
their existing reference-capital semantics. LIVE capital eligibility and LIVE
risk-budget projections no longer substitute that reference capital.

Risk budget = equity × min(requested risk percent, MM risk percent) / 100.
Risk-limited notional = budget / ((SL percent + estimated round-trip taker fee
percent) / 100). This is a fee estimate, not a slippage/funding guarantee.
Notional is also bounded by the independent MM position cap, current-equity
single-symbol and total exposure limits, 80% of available balance × leverage,
and exchange market maximum contracts. Leverage changes margin, not price risk.
This entry path requires FLAT local position and zero LIVE position/order margin;
it does not estimate cross-symbol open exposure or permit adding to a position.

Zero position size selects risk mode. Positive size remains requested fixed
notional: requests violating risk, MM, margin or exchange maximum fail closed;
permitted requests normalize downward to the contract step. The existing fixed
contract is covered by the original fixed-position execution tests. UI defaults
now select zero, while explicit nonzero values serialize unchanged. No persisted
operator settings are migrated or edited. The misleading Position Size Cap label
now identifies position size and the zero risk-mode convention.

Normalization uses Decimal floor in contracts. A result below the minimum is a
rejection, never a request to increase quantity. The engine validates the candidate
before MM admission. Immediately before the adapter constructs a LIVE order,
a required callback rechecks the exact normalized contracts, current price,
fresh LIVE account, current MM policy, canonical symbol, linear USDT contract
metadata, effective leverage, available margin and the MM entry gate. No quantity
transformation occurs between this callback and serialization. Preview account
and metadata reads have a two-second cache; final account validation bypasses it
and the adapter supplies freshly fetched metadata. Missing authority fails closed.

The canonical reduceOnly close path is unaffected and passes regression. The old
non-reduceOnly `close_position` wrapper routes through entry creation; it now fails
closed without final sizing authority, rather than gaining a validation bypass.

## Validation

- Required snapshot: equity/available 7.91836966, risk 0.5%, SL 1%, leverage 5,
  price 1.5205, multiplier 10, minimum/step 1 → NO_VALID_QUANTITY_FOR_RISK_POLICY.
- 376 affected Python tests and 73 subtests passed; 2 baseline failures excluded.
- The two excluded tests, `test_live_order_submit_is_not_called_when_not_ready`
  and `test_live_readiness_blocks_until_all_gates_are_ready`, both fail unchanged
  on the base commit in a separate baseline worktree. No authority repair was
  attempted as part of this sizing task.
- After refining failure-reason selection, 113 focused/Manual LIVE/adapter tests
  passed again, including the low-balance case and final wire quantity checks.
- 176 frontend BotControl/OperationPreparation tests passed.
- Production frontend build passed (existing large-chunk warning only).
- Python regression runs blocked real HTTP at Requests' session boundary;
  exchange POSTs in successful execution cases were test doubles only.
- Complete mocked MANUAL → engine → actual KuCoin adapter → fake HTTP regression
  confirms MM admission and final normalized-quantity MM revalidation.
- Existing PAPER entry/close, Manual LIVE Authority/Governance, MM integration,
  leverage, compounding, PAPER capital and sizing regressions passed.

Release procedure: explicit source-only staging; commit/push repair branch;
fast-forward canonical main only if its base remains unchanged; preserve existing
dirty artifacts; back up and install the reviewed frontend build; restart
tradingbot.service; GET-only verification of stopped/disarmed state and unchanged
MM settings. No runtime START, ARM, mode change, real order or funding action.
