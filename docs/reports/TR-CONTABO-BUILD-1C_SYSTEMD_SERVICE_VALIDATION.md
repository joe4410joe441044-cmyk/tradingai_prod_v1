# TR-CONTABO-BUILD-1C: TradingAI systemd Activation and Service Validation

**Status:** PASS
**Date:** 2026-08-02 17:37 JST

## 1. Safety Check

| Check | Required | Actual | Result |
|-------|----------|--------|--------|
| hostname | vmi3480936 | vmi3480936 | PASS |
| whoami | joe4410joe | joe4410joe | PASS |
| pwd | /home/joe4410joe/tradingai_prod_v1 | /home/joe4410joe/tradingai_prod_v1 | PASS |
| branch | main | main | PASS |
| HEAD | d57de0439576c1134a67ce6055f65fc4a1c084e0 | d57de0439576c1134a67ce6055f65fc4a1c084e0 | PASS |
| Redis | active | active | PASS |

## 2. Preflight: Repository Unit Inspection

**File:** `systemd/tradingbot.service` (in-repo)

### Discrepancies Found

| Directive | Repo Value | Required Value | Status |
|-----------|------------|----------------|--------|
| WorkingDirectory | /home/joe4410joe/TradingAI_Bot_Prod_v1 | /home/joe4410joe/tradingai_prod_v1 | MISMATCH |
| ExecStart | /home/joe4410joe/TradingAI_Bot_Prod_v1/venv/bin/python run_prod.py | venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 | MISMATCH |
| Environment | TELEGRAM_CHAT_ID=1040943428 (hardcoded secret) | should use EnvironmentFile | MISMATCH |
| Group | not set | joe4410joe | MISSING |
| EnvironmentFile | not set | /home/joe4410joe/tradingai_prod_v1/.env | MISSING |
| After | network.target only | +redis-server.service | MISSING |

The repository unit file was authored for the legacy GCP deployment (`TradingAI_Bot_Prod_v1`). It could not be activated as-is.

### Available Assets

| File | Path | Purpose |
|------|------|---------|
| Main unit | systemd/tradingbot.service | Legacy GCP unit (needs correction) |
| Loopback drop-in | deploy/systemd/tradingbot-loopback.override.conf.example | Candidate ExecStart fix |
| AI Advisor unit | deploy/systemd/tradingai-ai-advisor-live-validation.service | AI Advisor only (not for this task) |

## 3. Installation

Created corrected unit at `/etc/systemd/system/tradingbot.service` (outside repository):

```
[Unit]
Description=Trading AI Bot Service
After=network.target redis-server.service
Wants=redis-server.service

[Service]
Type=simple
User=joe4410joe
Group=joe4410joe
WorkingDirectory=/home/joe4410joe/tradingai_prod_v1
EnvironmentFile=/home/joe4410joe/tradingai_prod_v1/.env
ExecStart=/home/joe4410joe/tradingai_prod_v1/venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
UMask=0077

[Install]
WantedBy=multi-user.target
```

No files in the git repository were modified.

## 4. Activation

```
sudo systemctl daemon-reload
sudo systemctl enable tradingbot.service  →  enabled
sudo systemctl start tradingbot.service   →  active
```

## 5. Service State Validation

| Metric | Value | Required | Result |
|--------|-------|----------|--------|
| Loaded | loaded, enabled | enabled | PASS |
| ActiveState | active | active | PASS |
| SubState | running | running | PASS |
| MainPID | 28310 | non-zero | PASS |
| Result | success | success | PASS |
| NRestarts | 0 | 0 | PASS |

## 6. Backend Smoke Tests (via systemd)

| Endpoint | HTTP Status | Response |
|----------|-------------|----------|
| GET / | 200 | `{"status":"ok","runtime":"production_execution_cognition"}` |
| GET /health | 200 | `{"status":"ok","runtimeHealthy":true}` |
| GET /docs | 200 | Swagger UI |
| GET /openapi.json | 200 | 30,533 bytes |

## 7. Lifecycle Validation

| Operation | Command | Result |
|-----------|---------|--------|
| Restart | systemctl restart tradingbot.service | active, /health 200 |
| Stop | systemctl stop tradingbot.service | inactive |
| Start after stop | systemctl start tradingbot.service | active, /health 200 |

## 8. Journal Inspection

```
Started tradingbot.service
Started server process [28221]
Application startup complete.
Uvicorn running on http://127.0.0.1:8001
GET /health 200 OK
Shutting down (via stop)
Application shutdown complete.
Deactivated successfully.
Started tradingbot.service (via start)
Application startup complete.
```

- Error count: 0
- Crash loop: none
- Credential failure: none
- Import failure: none
- Configuration failure: none
- Restart storm: none (NRestarts=0)

## 9. Final Safety Check

| Check | Result |
|-------|--------|
| Branch | main (unchanged) |
| HEAD | d57de0439576c1134a67ce6055f65fc4a1c084e0 (unchanged) |
| Staged files | None |
| .env owner:group | joe4410joe:joe4410joe (unchanged) |
| .env mode | 600 (unchanged) |
| Redis | active |
| tradingbot.service | active |
| nginx | inactive / disabled |
| Port 80 | no listener |
| Port 443 | no listener |
| Port 5173 | no listener |
| Port 8001 | 127.0.0.1 only |

## 10. Summary

The tradingbot systemd service was activated successfully. The repository unit file had incorrect paths from the legacy GCP deployment — a corrected unit was installed to `/etc/systemd/system/`. All lifecycle operations (enable, start, restart, stop, start) succeed. All smoke endpoints return 200. Journal is clean with zero errors. No application ports are exposed beyond 127.0.0.1:8001. Redis remains active. Git state unchanged.
