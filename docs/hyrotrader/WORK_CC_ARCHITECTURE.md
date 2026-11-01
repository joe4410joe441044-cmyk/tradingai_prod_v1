# Work CC architecture

## Boundaries

The account layer defines identity, registry records, persistence contracts, and deterministic account resolution. PROP-specific contracts and context projection sit above that layer and do not replace the existing NORMAL-account behavior.

The execution foundation separates read authority from trade authority:

- read-only adapter contracts expose wallet, position, open-order, server-time, and key-readiness observations;
- signed transport permits only policy-approved GET requests to the configured Bybit demo host;
- credentials are injected through a redacted, one-shot boundary and can be supplied by the dedicated file provider;
- HTTP, retry, clock, egress, and redaction policies fail closed;
- normalized observations omit raw venue responses and secret material;
- execution-adapter contracts remain distinct from read-only contracts.

The authentication boundary is validated offline with fabricated credentials and injected fake transports. Nothing in this foundation performs an uncontrolled live request.

## UI isolation

The fixture preview derives its view model from static fabricated data. The component and preview contain no runtime endpoint, network client, WebSocket, browser storage, or order mutation. Existing operational trading screens are neither imported nor modified.

## Deferred integration

The PROP rule engine, including daily-loss, maximum-loss, consistency, phase, and payout authority, is not complete. Bollinger Band strategy integration and production runtime composition are intentionally deferred. Those concerns must be reviewed in a separately approved integration task; they must not be duplicated inside the fixture UI.
