# Work CC status

## Purpose

Work CC preserves an isolated foundation for PROP-account identity, read-only venue observations, and a fixture-only operator UI. It does not connect the existing trading runtime to a PROP account.

## Current scope

- Account kinds distinguish `NORMAL` from `PROP` without changing the established NORMAL path.
- Execution modes remain explicit: `PAPER`, `EXTERNAL_SIMULATION`, and `LIVE` are separate states; no mode is promoted implicitly.
- Durable registry contracts, account resolution, PROP context projection, read-only credential handling, signed GET boundaries, and redacted observations are implemented as isolated foundations.
- The PROP UI remains a standalone preview. Fixed scenarios have no API path; the CC-4A input mode uses only its dedicated loopback synthetic evaluator. Neither mode uses WebSocket, browser storage, Production backend, or order submission.
- Existing KuCoin/shared operational UI and runtime files are not part of this preservation commit.
- A synthetic-only PROP rule engine evaluates static maximum loss, daily loss, and profit-target progress from explicit immutable inputs. Entry compatibility requires explicit non-target risk gates; target-only and empty policies fail closed.
- Account-bound Rules Snapshot and Baseline Source v1 contracts provide strict immutable provenance, canonical change-detection digests, and DST fold resolution. Evaluation Evidence Link v1 is retained as legacy evidence and is not a complete result binding.
- Evidence Link v2 binds the full evaluation and Complete Bundle digests and enforces explicit as-of versus retroactive evidence timing.
- Immutable Active Selection, Required-rule Coverage, Complete Bundle, and Complete Outcome v1 contracts plus a pure evaluator wrapper are implemented only in the isolated CC layer. There is no selector store, activation, real source, runtime consumer, or caller-injected result.
- The existing rule definition, observation, daily baseline, evaluation, and PROP account context wire schemas remain unchanged; Engine calculation is v2 and the fail-closed read-only context projection remains v2.
- Missing or unsupported required-rule coverage cannot become operational-candidate compatible. Synthetic complete results remain non-operational.
- No HyroTrader profile is activated and no contract grants execution authority.
- CC-4A adds a standalone input-evaluation mode backed only by a loopback, process-local synthetic session. It issues IDs through the existing Account contract, preserves revision scope, calls the pure Complete Bundle wrapper, and displays the unchanged read-only projection. Reloading or stopping the entry discards every sample account.

## Readiness

This work is not production integration ready. CC-3D result-binding and future-baseline findings are fixed in Evidence Link v2 and Complete Bundle validation; v1 remains legacy rather than silently upgraded. The runtime remains disconnected, external observer-key eligibility is unconfirmed, no real account selection or official profile is activated, required HyroTrader rule coverage is externally unknown, and Bollinger Band/runtime strategy integration is not implemented. Manual visual acceptance is also pending because the review environment could not open the saved screenshots.

No production deployment, live credential use, real venue request, or order action is authorized or performed by Work CC.

CC-4A automated browser QA covers desktop, tablet, and mobile input-to-result operation. Manual screenshot rendering remains environment-blocked by the documented bwrap failure.

## CC-4A offline account workflow

The fixture-only scenarios remain available and are visually separated from the new
input-evaluation mode. The new mode creates only PROP / EXTERNAL_SIMULATION /
BYBIT_DEMO identities, fixes rule and provenance status to synthetic, accepts no
credential or external-reference fields, and has no persistence. Its HTTP adapter
binds to 127.0.0.1:4188, accepts only the preview origin at 127.0.0.1:4187,
limits request size and routes, and returns fixed safe errors.

This is an offline calculation demonstration. It is not a registered HyroTrader
account, an official rule profile, challenge approval, runtime readiness, or trade
authority.

## CC-4B acceptance and preservation

The CC-4A workflow received a same-agent, separate-stage acceptance review. Limited
fixes now enforce the existing Engine 64-significant-digit and adjusted-exponent
contract at the input boundary, reject duplicate JSON and slow/incomplete bodies,
return safe JSON for unsupported methods, serialize the threaded in-memory session,
and require current controller ownership plus mounted state before frontend updates.
Same-tick double evaluation submission is rejected.

Form help/error association, polite loading/result announcements, and account field
errors were added without changing the UI structure. Targeted final validation
passed 183 backend tests and 34 frontend tests; the isolated build transformed 25
modules. Browser acceptance covered field association, keyboard order, double
submit, error recovery, loading-time invalidation, and mobile overflow with zero
external requests. Manual screenshot viewing remains pending because the known
bwrap image-viewer failure was not repeated.

## CC-3G preservation status

The two CC-3F acceptance findings are fixed in the isolated contracts. Complete Bundle
rejects an observation observed or finally received after its knowledge cutoff, while
explicit retroactive analysis may use later receipt only up to its later cutoff.
Complete Outcome rederives candidate status during construction and deserialization;
a caller cannot promote a read-only, historical, incomplete, blocked, or unknown
outcome by changing the status and recomputing the content digest.

The low fail-closed official-profile limitation is retained, and unkeyed digest
authenticity remains an external prerequisite rather than being mislabeled as fixed.
The current preservation is synthetic/offline only. Official account profile activation,
runtime/MM/execution wiring, UI integration, BB integration, real API access, secrets,
registry mutation, and order authority remain absent.


## CC-3H fixture UI and handoff

A deterministic generator now evaluates synthetic Complete Bundles through the pure wrapper and emits the strict read-only projection v1 consumed by the isolated fixture UI. Evaluation scenarios are independent from the ten connection scenarios. Every scenario remains execution-disabled; BB integration, official profile activation, runtime, MM, real API, and Production UI remain absent.

## CC-3I projection acceptance and preservation

The projection boundary now explicitly retains execution mode, execution venue, and
generation-time freshness. The fixture consumer rejects wrong account scope,
unsupported schema, missing timestamps/freshness/coverage, authority promotion, and
malformed Decimal values. BB owner acceptance and integration remain unperformed.

## CC-3J BB acceptance-contract clarification

The isolated fixture consumer now binds all eight account-scope fields from the
selected PROP descriptor and rejects incomplete, null, mismatched, operational, or
unknown-purpose projections without fallback. The handoff separates diagnostic
projection fields, fixture display fields, and the future minimal BB AI-context
allowlist. BB reacceptance, BB code, runtime connection, Production application,
and execution authority remain absent.
