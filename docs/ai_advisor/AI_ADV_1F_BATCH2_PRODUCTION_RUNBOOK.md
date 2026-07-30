# AI Advisor Browser Gateway Production Runbook

This runbook is documentation only. It does not authorize production changes.

## Preconditions

1. Keep the browser gateway disabled.
2. Bind Uvicorn to loopback (`127.0.0.1:8001`) or an equivalently isolated
   interface. Do not continue while it listens on `0.0.0.0`.
3. Configure and independently verify Nginx authentication.
4. Configure Nginx to discard `Authorization` and overwrite
   `X-TradingAI-Authenticated-User` with the authenticated server-side identity.
5. Set a fixed trusted-proxy peer allowlist containing only the actual direct
   Nginx peer.
6. Set exact production origins. Do not use wildcards, suffixes, or partial
   matches.
7. Confirm the provider remains offline unless a separately approved live
   connectivity procedure has completed.

## Configuration

The gateway reads only these non-secret policy values:

```text
AI_ADVISOR_BROWSER_GATEWAY_ENABLED=true
AI_ADVISOR_BROWSER_TRUSTED_PROXY_PEERS=127.0.0.1
AI_ADVISOR_BROWSER_ALLOWED_ORIGINS=https://approved.example
```

Do not place provider credentials or bearer tokens in frontend configuration.

## Isolated live-validation boundary

The Browser Gateway and its Production service do not receive live-validation
credentials. The only credential/unit contract is
`docs/ai_advisor/systemd-credential-smoke-runbook.md`: encrypted artifacts live
under `/etc/credstore.encrypted/tradingai-ai-advisor-live-validation`, and the
only runner is transient `tradingai-ai-advisor-live-validation.service` created
with `systemd-run --wait --collect`. No persistent unit, daemon reload,
Production-service restart, or Browser Gateway activation is part of that
procedure.

## Offline verification order

1. Validate the candidate Nginx configuration without reloading it.
2. Confirm direct Backend access with a forged identity is rejected.
3. Confirm missing authentication, Origin, and `X-TradingAI-Client` are rejected.
4. Confirm the status response contains only a coarse public state.
5. Confirm `{ "prompt": "..." }` is the only accepted browser request shape.
6. Confirm no provider network call occurs in offline mode.
7. Enable the gateway only after every check above passes.

## Rollback

1. Set `AI_ADVISOR_BROWSER_GATEWAY_ENABLED=false`.
2. Restore the last reviewed Nginx configuration.
3. Validate configuration before any separately authorized reload.
4. Keep the existing server-to-server Bearer endpoint isolated.

If identity overwrite, loopback binding, exact Origin enforcement, or offline
verification fails, leave the gateway disabled.
