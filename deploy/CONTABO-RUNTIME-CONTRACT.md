# Contabo Runtime Reconstruction Guide

**Task:** TR-CONTABO-BUILD-1E
**Status:** Verified 2026-08-02

This document describes how to reconstruct the verified Contabo runtime from
the repository templates. No secrets, credentials, or `.env` values are stored
in these templates.

## Canonical Templates

| Purpose | Repository Path | Install Destination |
|---------|----------------|---------------------|
| Backend service | `systemd/tradingbot.service` | `/etc/systemd/system/tradingbot.service` |
| HTTP reverse proxy | `deploy/nginx-tradingai.conf` | `/etc/nginx/sites-available/tradingai` |

`frontend/tradingai.conf` is a duplicate reference copy. The canonical source
is `deploy/nginx-tradingai.conf`.

## Prerequisites

- Redis installed and running (loopback-only, port 6379)
- Python venv at `/home/joe4410joe/tradingai_prod_v1/venv`
- `.env` present at `/home/joe4410joe/tradingai_prod_v1/.env` (mode 600, owner joe4410joe)
- nginx installed (`apt install nginx`)
- Frontend build present at `frontend/dist/`

## Listener Boundaries

| Service | Bind | Port | Visibility |
|---------|------|------|------------|
| Redis | 127.0.0.1, ::1 | 6379 | loopback only |
| Backend (uvicorn) | 127.0.0.1 | 8001 | loopback only |
| nginx (HTTP) | 0.0.0.0, :: | 80 | public |
| TLS (443) | — | — | not configured |

## Installation

### 1. Backend systemd Service

```bash
sudo cp systemd/tradingbot.service /etc/systemd/system/tradingbot.service
sudo systemctl daemon-reload
sudo systemctl enable tradingbot.service
sudo systemctl start tradingbot.service
```

### 2. nginx Reverse Proxy

```bash
# Install site
sudo cp deploy/nginx-tradingai.conf /etc/nginx/sites-available/tradingai
sudo ln -s /etc/nginx/sites-available/tradingai /etc/nginx/sites-enabled/tradingai

# Disable default site if conflicting
sudo rm /etc/nginx/sites-enabled/default

# Ensure nginx can traverse home directory
sudo chmod o+x /home/joe4410joe

# Validate and start
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl start nginx
```

### 3. Per-Environment Configuration

Edit `server_name` in `/etc/nginx/sites-available/tradingai`:

```nginx
server_name YOUR_PUBLIC_IP _;
```

The repository template uses `server_name _;` for portability.

## Validation Commands

```bash
# Service status
systemctl is-active redis-server tradingbot.service nginx
systemctl is-enabled redis-server tradingbot.service nginx

# Listener verification
sudo ss -lntp | grep -E ':(80|443|6379|8001|5173)'

# Backend smoke
curl -s http://127.0.0.1:8001/health

# Frontend smoke
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/

# API proxy smoke
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/api/governance/status

# Security boundary
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/.env

# Systemd verification
systemd-analyze verify systemd/tradingbot.service

# nginx syntax check
nginx -t -c /etc/nginx/nginx.conf
```

## Contract Tests

```bash
# Run repository contract verification
venv/bin/python -m pytest tests/test_contabo_runtime_contract.py -v
```

## TLS

TLS/HTTPS is a separate task. Do not add port 443 listeners or SSL directives
to these templates. TLS configuration should be applied via a separate nginx
site file or drop-in override.

## Secrets

Secrets (API keys, tokens, credentials) are never stored in repository
templates. They are provided via `.env` (loaded by systemd `EnvironmentFile`)
and are never committed to Git.
