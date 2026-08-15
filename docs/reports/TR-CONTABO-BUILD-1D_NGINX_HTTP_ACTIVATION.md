# TR-CONTABO-BUILD-1D: nginx HTTP Reverse Proxy Activation and Validation

**Status:** PASS
**Date:** 2026-08-02 17:50 JST

## 1. Safety Check

| Check | Required | Actual | Result |
|-------|----------|--------|--------|
| hostname | vmi3480936 | vmi3480936 | PASS |
| whoami | joe4410joe | joe4410joe | PASS |
| pwd | /home/joe4410joe/tradingai_prod_v1 | same | PASS |
| branch | main | main | PASS |
| HEAD | d57de0439576c1134a67ce6055f65fc4a1c084e0 | same | PASS |
| redis-server | active + enabled | active + enabled | PASS |
| tradingbot.service | active + enabled | active + enabled | PASS |

## 2. Pre-Activation Audit

| Item | Value |
|------|-------|
| nginx version | 1.24.0 (Ubuntu) |
| Initial state | inactive / disabled |
| /etc/nginx/nginx.conf | default Ubuntu, clean |
| /etc/nginx/sites-available | default only |
| /etc/nginx/sites-enabled | default only |
| GCP IPs in config | none |
| Frontend build | frontend/dist/index.html (552 bytes) |

### Repository nginx Configs Inspected

| File | server_name | proxy_pass | GCP IP | Assessment |
|------|-------------|------------|--------|------------|
| deploy/nginx-tradingai.conf | 35.194.104.74 | 127.0.0.1:8001 | YES | REJECTED — GCP IP |
| frontend/tradingai.conf | 35.194.104.74 | 127.0.0.1:8001 | YES | REJECTED — GCP IP |

Both repo configs reference the obsolete Google Cloud IP and needed adaptation.

## 3. Implementation

### Home Directory Permission Fix

The nginx worker (www-data) could not traverse `/home/joe4410joe` (mode 750).
Fixed: `chmod o+x /home/joe4410joe` → 751 (traverse-only for others).

### Installed nginx Site

Created `/etc/nginx/sites-available/tradingai` with:

```
server_name 169.58.111.142 _;
root /home/joe4410joe/tradingai_prod_v1/frontend/dist;

location /             → SPA fallback: try_files $uri $uri/ /index.html
location /assets/      → immutable cache, try_files $uri =404
location /api/         → proxy_pass http://127.0.0.1:8001 (preserves /api/ prefix)
location = /config     → proxy_pass http://127.0.0.1:8001/config
location /ws           → proxy_pass http://127.0.0.1:8001 (WebSocket upgrade)

Security:
  /.env               → 404
  /.git               → 404
  /docs/recovery/     → 404
  /tmp/chatgpt_reviews/ → 404
  /backend/           → 404
  /systemd/           → 404
```

Disabled Ubuntu default site (removed symlink, preserved source file).

### Design Decision: proxy_pass trailing slash

`/api/` uses `proxy_pass http://127.0.0.1:8001` (no trailing slash) to preserve
the `/api/` prefix. The Backend mounts all API routers with `prefix="/api"`.
Using a trailing slash would strip the prefix, breaking routing.

This matches the `deploy/nginx-tradingai.conf` approach (verified against
OpenAPI schema: 43 paths all under `/api/`).

### Backups

Created `/var/backups/tradingai-nginx/` (no files to back up — no prior
tradingai site existed).

### Validation

```
sudo nginx -t → syntax ok, test successful
```

## 4. Service Validation

| Metric | Value | Required | Result |
|--------|-------|----------|--------|
| ActiveState | active | active | PASS |
| SubState | running | running | PASS |
| MainPID | 29560 | non-zero | PASS |
| NRestarts | 0 | 0 | PASS |
| Result | success | success | PASS |
| Enabled | enabled | enabled | PASS |

## 5. Localhost Smoke Tests

### Frontend

| Test | Result |
|------|--------|
| GET / | HTTP 200, text/html, 552 bytes |
| GET /assets/index-*.js | HTTP 200, application/javascript |
| No directory listing | Confirmed |
| No .env exposure | HTTP 404 |
| No .git exposure | HTTP 404 |

### Backend Proxy

| Endpoint | HTTP | Notes |
|----------|------|-------|
| /api/governance/status | 200 | Full JSON response |
| /api/logs | 200 | |
| /api/history | 200 | |
| /api/bot/status | 200 | |

### Security Denials

| Path | HTTP |
|------|------|
| /.env | 404 |
| /.git/config | 404 |
| /docs/recovery/ | 404 |
| /tmp/chatgpt_reviews/ | 404 |
| /backend/ | 404 |
| /systemd/ | 404 |

## 6. Public IP Smoke

| Test | HTTP | Notes |
|------|------|-------|
| http://169.58.111.142/ | 200 | Frontend served |
| http://169.58.111.142/api/governance/status | 200 | Backend proxy |
| GCP IPs in HTML | 0 matches | Clean |
| Old repo references in HTML | 0 matches | Clean |

## 7. WebSocket Configuration (Static)

| Directive | Value | Status |
|-----------|-------|--------|
| location | /ws | Correct |
| proxy_pass | http://127.0.0.1:8001 | Loopback |
| proxy_http_version | 1.1 | Required for WS |
| Upgrade header | $http_upgrade | Correct |
| Connection header | upgrade | Correct |
| proxy_read_timeout | 86400 | Long-lived |

Backend WebSocket route confirmed: `@router.websocket("/ws")` at
`backend/api/websocket.py:126`. No prefix — matches `/ws` location.

## 8. Restart Test

| Operation | Result |
|-----------|--------|
| systemctl restart nginx | active |
| nginx NRestarts | 0 |
| Frontend after restart | HTTP 200 |
| /api/governance/status after restart | HTTP 200 |
| tradingbot.service | active (unchanged) |
| redis-server | active (unchanged) |

## 9. Journal Inspection

```
nginx restart → clean startup, no errors
No permission-denied loop (fixed pre-activation)
No upstream connection failure
No restart loop
No invalid host/path reference
No GCP IP dependency
```

## 10. Final Integrity Check

| Check | Result |
|-------|--------|
| Branch | main (unchanged) |
| HEAD | d57de0439576c1134a67ce6055f65fc4a1c084e0 (unchanged) |
| Staged files | None |
| .env owner:group | joe4410joe:joe4410joe (unchanged) |
| .env mode | 600 (unchanged) |
| Redis | active + enabled |
| tradingbot.service | active + enabled |
| nginx | active + enabled |
| Port 80 | listening (0.0.0.0 + [::]) |
| Port 443 | not listening |
| Port 5173 | not listening |
| Port 8001 | 127.0.0.1 only |
| Port 6379 | 127.0.0.1 + [::1] only |
| Source changes | None |
| Commits | None |

## 11. Summary

nginx 1.24.0 HTTP reverse proxy activated on Contabo. Contabo-specific site
installed with static frontend serving, Backend API proxy, and WebSocket
upgrade support. All GCP IP references removed. Security paths denied.
Restart test passes. All services healthy. Git state unchanged.
