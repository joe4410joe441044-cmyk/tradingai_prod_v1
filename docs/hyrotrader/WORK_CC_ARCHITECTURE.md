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

The fixed-scenario preview derives its view model from static fabricated data. The
CC-4A/4B input mode adds one dedicated browser client that can call only the
loopback synthetic evaluator on 127.0.0.1:4188 from the exact preview origin. The
preview contains no Production endpoint, WebSocket, browser storage, credential,
exchange, runtime, or order mutation. Existing operational trading screens are
neither imported nor modified.

The local evaluator is an unauthenticated development boundary. Loopback binding,
exact Host/Origin checks, minimal routes, JSON/body limits, duplicate-key rejection,
and body-read timeout reduce accidental local misuse, but do not turn it into an
authenticated multi-user service. It must not be exposed beyond the local preview.
Its process-local session serializes account creation, revision, and evaluation so a
threaded HTTP request cannot mix account revisions.

CC-4D adds a second adapter for the application without changing the local preview.
Its route and navigation are strict default OFF behind independent frontend/backend
flags. The adapter reuses the existing operator-session and CSRF middleware, checks
same-origin `Origin`/Host/scheme, parses strict bounded JSON while streaming, and
calls the same `OfflinePropSession` pure conversion/evaluation path. Its browser
client has only three fixed relative `/api/prop-accounts/synthetic/...` paths; no
arbitrary host or CORS allowance exists.

Because account creation, revision, and evaluation are separate preserved actions,
the application adapter uses a bounded per-operator-session in-memory registry.
Session expiry is the entry lifetime, expired entries are removed on access, and an
LRU cap of 64 bounds retained sessions. There is no persistence or background task.
The application page suppresses the global trading WebSocket while active and does
not import runtime, order, exchange, credential, registry, or settings mutation
services. Account Status remains a PAPER/REAL read-only projection with only a
separate conditional link.

## Deferred integration

The synthetic PROP rule engine is an isolated pure calculation layer. It reuses the v1 rule, observation, result, and evaluation DTOs and an explicit caller-supplied daily baseline. Calculation v2 uses an engine-local exact Decimal context and explicit entry risk gates. Static maximum loss, daily loss, and profit-target progress are supported only under an explicit synthetic policy. Profit target is informational/completion progress, never an entry gate. `entry_allowed` is calculation compatibility, not runtime or execution authority.

Immutable Rules Snapshot and Baseline Source v1 contracts form the evidence foundation. Evidence Link v1 remains readable legacy provenance but does not bind the complete evaluation result. Evidence Link v2 binds complete evaluation and Bundle digests and validates as-of information availability. Canonical unkeyed digests detect content changes but provide no authentication.

Active Selection v1 is an immutable explicit selection record and pure validator, not a repository or activation. Required-rule Coverage v1 is checked against the fixed evaluator-v2 capability set. Complete Bundle v1 validates the account/selection/snapshot/baseline/observation/policy/coverage/time graph. The pure wrapper calculates from that one Bundle and emits a linked Complete Outcome without accepting an injected result. Historical as-of and retroactive analysis are separate purposes.

The existing projection remains fail-closed context v2: Complete Bundle/Link v2 is not wired into it, so it remains PARTIAL with `RULES_SNAPSHOT_REQUIRED`. No durable selector, source provider, runtime composition, execution authority, or BB integration is added.

Official account profiles, consistency, minimum-day, phase completion, payout authority, trailing persistence, Bollinger Band strategy integration, and production runtime composition are intentionally deferred. Those concerns must be reviewed in separately approved tasks; they must not be duplicated inside the fixture UI or inferred from a calculation PASS.

## CC-3G invariant ownership

Temporal availability belongs to Complete Bundle validation rather than the low-level
calculation API. The Bundle compares both observation source time and final receipt
time with its explicit knowledge cutoff. Aggregate producers are responsible for using
the last required page/endpoint receipt. This keeps clock-skew tolerance inside the
Engine from becoming an as-of provenance exception.

Operational candidate status is a derived projection, not caller authority. One pure
backend derivation function is used by the wrapper and Complete Outcome validation.
The Outcome still grants no execution authority. Content digests bind deterministic
content, while evidence authenticity and trusted execution origin remain separate
governance concerns.

These invariants add no runtime composition. Context v2 remains PARTIAL and the
fixture UI and BB context chain remain disconnected.


## CC-3H projection path

`CompleteEvaluationOutcome` -> strict round-trip validation -> `project_outcome_read_only_context` -> generated JSON -> fixture-only `PropAccountsPanel`. The same JSON is the proposed BB sample, so UI and handoff do not duplicate calculation logic. Connection scenarios and evaluation scenarios remain separate axes. No provider, event bus, API route, storage, runtime, MM, or execution composition was added.

## CC-3I consumer boundary

The read-only projection carries the canonical account id, identity revision,
execution mode, execution venue, program, plan, phase, and currency. Consumer scope
matching is fail-closed and never falls back across accounts. Freshness is retained as
a generation-time state; current-time staleness remains a consumer responsibility.
