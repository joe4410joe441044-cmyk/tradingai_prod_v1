# TR-MIGRATION-1F-2: Contabo Runtime Dependency Foundation

## Result

**Success.** All approved OS-level runtime dependencies installed. Node.js 20 LTS available. No services running. Repository unchanged.

## Execution Summary

| Item | Value |
|------|-------|
| Task ID | TR-MIGRATION-1F-2 |
| Hostname | vmi3480936 |
| User | joe4410joe |
| Repository | /home/joe4410joe/tradingai_prod_v1 |
| Branch | main |
| HEAD | d57de0439576c1134a67ce6055f65fc4a1c084e0 |

## Safety Check Results

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| hostname | vmi3480936 | vmi3480936 | PASS |
| whoami | joe4410joe | joe4410joe | PASS |
| pwd | /home/joe4410joe/tradingai_prod_v1 | /home/joe4410joe/tradingai_prod_v1 | PASS |
| branch | main | main | PASS |
| HEAD | d57de0439576c1134a67ce6055f65fc4a1c084e0 | d57de0439576c1134a67ce6055f65fc4a1c084e0 | PASS |
| Git dirty state | Intentionally preserved | Identical | PASS |

## Installed Packages

| Package | Pre-installation | Post-installation | Version |
|---------|-------------------|-------------------|---------|
| build-essential | Absent | Installed | 12.10ubuntu1 |
| python3-dev | Absent | Installed | 3.12.3-0ubuntu2.1 |
| python3-venv | Absent | Installed | 3.12.3-0ubuntu2.1 |
| python3-pip | Absent | Installed | 24.0 |
| curl | Installed | Installed | 8.5.0-2ubuntu10.11 |
| ca-certificates | Installed | Installed | 20260601~24.04.1 |
| gnupg | Installed | Installed | 2.4.4-2ubuntu17.4 |
| rsync | Installed | Installed | 3.2.7-1ubuntu1.5 |
| nginx | Absent | Installed | 1.24.0-2ubuntu7.15 |
| redis-server | Absent | Installed | 7.0.15 |
| nodejs (Node.js 20 LTS) | Absent | Installed | 20.20.2 (from NodeSource) |

## Version Verification

```
python3 --version   → Python 3.12.3
pip3 --version      → pip 24.0 from /usr/lib/python3/dist-packages/pip (python 3.12)
node --version      → v20.20.2
npm --version       → 10.8.2
nginx -v            → nginx/1.24.0 (Ubuntu)
redis-server --version → Redis server v=7.0.15
rsync --version     → 3.2.7
gcc --version       → 13.3.0
```

## Service State

| Service | Pre-installation | Post-installation (auto) | Final (remediated) |
|---------|-------------------|--------------------------|--------------------|
| nginx | inactive / not-found | active / enabled | inactive / disabled |
| redis-server | inactive / not-found | active / enabled | inactive / disabled |

nginx and redis-server were automatically started and enabled by the Ubuntu package manager during apt-get install. Both were immediately stopped and disabled to comply with scope.

## Port Audit (Post-Installation)

| Port | Service | Status |
|------|---------|--------|
| 80 | HTTP | Not listening |
| 443 | HTTPS | Not listening |
| 6379 | Redis | Not listening |
| 8001 | App backend | Not listening |
| 5173 | Vite dev | Not listening |

Active listeners (unchanged from pre-installation):
- 127.0.0.1:53 (systemd-resolved DNS)
- 127.0.0.53:53 (systemd-resolved DNS stub)
- 0.0.0.0:22 (SSH)
- 127.0.0.1:45773 (system process)

## Repository Integrity

Git status, HEAD, and dirty state verified identical to pre-installation baseline.

## Git Safety

- Commit: No
- Push: No
- Deploy: No
- Branch Changed: No
- Staged Changes: No
- Out-of-Scope Files Modified: No
