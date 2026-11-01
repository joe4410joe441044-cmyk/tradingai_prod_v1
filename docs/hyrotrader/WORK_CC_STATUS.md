# Work CC status

## Purpose

Work CC preserves an isolated foundation for PROP-account identity, read-only venue observations, and a fixture-only operator UI. It does not connect the existing trading runtime to a PROP account.

## Current scope

- Account kinds distinguish `NORMAL` from `PROP` without changing the established NORMAL path.
- Execution modes remain explicit: `PAPER`, `EXTERNAL_SIMULATION`, and `LIVE` are separate states; no mode is promoted implicitly.
- Durable registry contracts, account resolution, PROP context projection, read-only credential handling, signed GET boundaries, and redacted observations are implemented as isolated foundations.
- The PROP UI is a standalone fixture preview. It has no API, WebSocket, browser-storage, or order-submission integration.
- Existing KuCoin/shared operational UI and runtime files are not part of this preservation commit.

## Readiness

This work is not production integration ready. The runtime remains disconnected, external observer-key eligibility is unconfirmed, the PROP rule engine is incomplete, and Bollinger Band/runtime strategy integration is not implemented. Manual visual acceptance is also pending because the review environment could not open the saved screenshots.

No production deployment, live credential use, real venue request, or order action is authorized or performed by Work CC.
