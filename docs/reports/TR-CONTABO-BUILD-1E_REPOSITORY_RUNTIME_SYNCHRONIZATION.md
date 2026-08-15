# TR-CONTABO-BUILD-1E: Repository Runtime Configuration Synchronization

**Status:** PASS
**Date:** 2026-08-02 18:01 JST

## 1. Safety Check

| Check | Required | Actual | Result |
|-------|----------|--------|--------|
| hostname | vmi3480936 | vmi3480936 | PASS |
| whoami | joe4410joe | joe4410joe | PASS |
| branch | main | main | PASS |
| HEAD | d57de0439576c1134a67ce6055f65fc4a1c084e0 | same | PASS |
| redis-server | active + enabled | active + enabled | PASS |
| tradingbot.service | active + enabled | active + enabled | PASS |
| nginx | active + enabled | active + enabled | PASS |

## 2. Installed Contract Inspection

### A. systemd Contract (installed)

From `/etc/systemd/system/tradingbot.service`:

```
User=joe4410joe
Group=joe4410joe
WorkingDirectory=/home/joe4410joe/tradingai_prod_v1
EnvironmentFile=/home/joe4410joe/tradingai_prod_v1/.env
ExecStart=.../venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
Restart=always, RestartSec=5
StandardOutput=journal, StandardError=journal
UMask=0077
After=network.target redis-server.service
Wants=redis-server.service
WantedBy=multi-user.target
```

### B. nginx Contract (installed)

From `/etc/nginx/sites-available/tradingai`:

- Listen: 80 (HTTP only, no TLS/443)
- server_name: 169.58.111.142 _
- Root: frontend/dist with SPA fallback
- /assets/ immutable cache
- /api/ → http://127.0.0.1:8001 (preserves prefix)
- /config → http://127.0.0.1:8001/config
- /ws → http://127.0.0.1:8001 (WebSocket upgrade, HTTP/1.1, 86400s timeout)
- Security denials: .env, .git, docs/recovery, tmp/chatgpt_reviews, backend/, systemd/

## 3. Consumer Audit

| Template File | Consumers |
|---------------|-----------|
| systemd/tradingbot.service | tests/test_telegram_disabled_security.py (reads) |
| deploy/nginx-tradingai.conf | Documentation references only (no scripts) |
| frontend/tradingai.conf | Documentation references only (no scripts) |

No deployment scripts consume the nginx templates. The systemd template is consumed by the Telegram security test.

## 4. Repository Changes

### 4.1 systemd/tradingbot.service

| Before (Legacy GCP) | After (Contabo Verified) |
|---------------------|--------------------------|
| WorkingDirectory=/home/joe4410joe/TradingAI_Bot_Prod_v1 | /home/joe4410joe/tradingai_prod_v1 |
| ExecStart=...TradingAI_Bot_Prod_v1/venv/bin/python run_prod.py | ...tradingai_prod_v1/venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 |
| Environment="TELEGRAM_CHAT_ID=..." (hardcoded) | EnvironmentFile=/home/joe4410joe/tradingai_prod_v1/.env |
| No Group | Group=joe4410joe |
| No UMask | UMask=0077 |
| No After/Wants redis | After=network.target redis-server.service / Wants=redis-server.service |

### 4.2 deploy/nginx-tradingai.conf

| Before | After |
|--------|-------|
| server_name 35.194.104.74 | server_name _ (portable, with deployment docs) |
| No security denials | .env/.git/recovery/backend/systemd → 404 |
| No SPA assets cache | /assets/ with immutable Cache-Control |
| No autoindex off | autoindex off |
| No deployment docs | Header comments with install/validate commands |

### 4.3 frontend/tradingai.conf

| Before | After |
|--------|-------|
| server_name 35.194.104.74 | server_name _ |
| No security denials | Same denials as canonical |
| Missing directives | Autoindex off, assets cache, consistent with canonical |
| Unmarked as duplicate | Header notes: canonical is deploy/nginx-tradingai.conf |

### 4.4 New Files

| File | Purpose |
|------|---------|
| tests/test_contabo_runtime_contract.py | 34 contract tests for systemd + nginx templates |
| deploy/CONTABO-RUNTIME-CONTRACT.md | Reconstruction guide with install/validate commands |

## 5. Validation

### A. systemd-analyze

```
systemd-analyze verify systemd/tradingbot.service
→ No output (success)
```

### B. nginx Syntax

```
sudo nginx -t
→ syntax ok, test successful
```

### C. Contract Tests

```
34 tests, 0 failures
```

| Test Group | Count | Result |
|------------|-------|--------|
| SystemdTemplateContractTest | 16 | PASS |
| NginxTemplateContractTest | 16 | PASS |
| NginxDuplicateTemplateConsistencyTest | 2 | PASS |

Key assertions verified:
- No legacy GCP paths/IPs in any template
- No 0.0.0.0 bind in systemd
- No port 443/TLS in nginx
- 127.0.0.1:8001 upstream
- WebSocket upgrade headers present
- Sensitive-path denials present
- Duplicate template matches canonical

### D. Existing Tests (Non-Regression)

```
tests/test_telegram_disabled_security.py → 5 tests OK
```

## 6. Non-Regression (Installed Runtime)

| Check | Result |
|-------|--------|
| redis-server | active + enabled |
| tradingbot.service | active + enabled |
| nginx | active + enabled |
| GET http://127.0.0.1/ | HTTP 200 |
| GET http://127.0.0.1/api/governance/status | HTTP 200 |
| Port 80 | listening (0.0.0.0 + [::]) |
| Port 8001 | 127.0.0.1 only |
| Port 6379 | 127.0.0.1 + [::1] only |
| Port 443 | closed |
| Port 5173 | closed |

No installed files under /etc were modified.

## 7. Final Git State

| Check | Result |
|-------|--------|
| Branch | main (unchanged) |
| HEAD | d57de0439576c1134a67ce6055f65fc4a1c084e0 (unchanged) |
| Staged files | None |
| In-scope modified | systemd/tradingbot.service, deploy/nginx-tradingai.conf, frontend/tradingai.conf |
| In-scope new | tests/test_contabo_runtime_contract.py, deploy/CONTABO-RUNTIME-CONTRACT.md |
| Out-of-scope modified | None (pre-existing dirty state preserved) |
| git diff --check | Pass |
| Commit | No |
| Push | No |

## 8. Summary

All three repository runtime templates synchronized with the verified Contabo
contract. Legacy GCP paths (`TradingAI_Bot_Prod_v1`) removed. Legacy GCP IPs
(`35.194.104.74`, `34.85.66.137`) removed. 34 contract tests added. Reconstruction
documentation created. Installed runtime untouched. Services healthy throughout.
