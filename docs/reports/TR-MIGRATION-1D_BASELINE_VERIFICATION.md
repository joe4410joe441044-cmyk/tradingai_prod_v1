# TR-MIGRATION-1D Baseline Verification Report

**Date**: 2026-08-02
**Target**: New Contabo Cloud VPS 8
**Hostname**: tradingai-prod-v1

---

## 1. Safety Checks

| Item | Value |
|------|-------|
| Hostname | tradingai-prod-v1 |
| User | joe4410joe |
| Working Directory | /home/joe4410joe/tradingai_prod_v1 |
| Kernel | 6.1.0-51-cloud-amd64 |
| Architecture | x86_64 |
| OS | Debian GNU/Linux 12 (bookworm) |

---

## 2. Hardware Summary

### CPU
| Item | Value |
|------|-------|
| vCPUs | 2 |
| Model | Intel(R) Xeon(R) CPU @ 2.20GHz |
| Sockets/Cores/Threads | 1 / 1 / 2 |
| Virtualization | KVM (full) |
| L3 Cache | 55 MiB |

### Memory
| Item | Value |
|------|-------|
| Total RAM | 3.8 GiB |
| Available | 2.1 GiB |
| Used | 1.7 GiB |
| Swap | 2.0 GiB (112 MiB used) |

### Disk
| Filesystem | Size | Used | Avail | Use% |
|------------|------|------|-------|------|
| /dev/sda1 (/) | 20G | 11G | 8.6G | 55% |
| /dev/sda15 (/boot/efi) | 124M | 12M | 112M | 10% |

| Filesystem | Inodes | IUsed | IFree | IUse% |
|------------|--------|-------|-------|------|
| /dev/sda1 (/) | 1,302,528 | 205,294 | 1,097,234 | 16% |

---

## 3. OS & System

| Item | Value |
|------|-------|
| Distribution | Debian 12 (bookworm) |
| systemd | 252.39 |
| Timezone | Asia/Tokyo (JST, +0900) |
| NTP Sync | Active (synchronized) |

---

## 4. Network

| Item | Value |
|------|-------|
| Primary IP | 10.146.0.7/32 (ens4) |
| Docker Bridge | 172.17.0.1/16 (docker0) |
| Default Gateway | 10.146.0.1 |

### Listening Ports
| Port | Service | Process |
|------|---------|---------|
| 22 | SSH | — |
| 80 | HTTP | — |
| 8001 | HTTP (python) | pid:392 |
| 25 | SMTP | — |
| 53 | DNS | systemd-resolved |

---

## 5. Python

| Item | Value |
|------|-------|
| Version | Python 3.11.2 |
| pip | 23.0.1 |
| venv | Available |

---

## 6. Node.js

| Item | Value |
|------|-------|
| Version | v20.20.2 |
| npm | 10.8.2 |

---

## 7. Docker

| Item | Value |
|------|-------|
| Docker Engine | 29.7.1 |
| Docker Compose | v5.3.1 |
| Running Containers | None |
| containerd | Installed |

---

## 8. Git

| Item | Value |
|------|-------|
| Version | 2.39.5 |
| User | joe4410joe |
| Email | your_email@example.com |
| Credential Helper | store |

---

## 9. Security

| Item | Status |
|------|--------|
| ufw | Not installed |
| fail2ban | Installed but not running (socket inaccessible) |

---

## 10. Migration Target Directories

| Path | Status |
|------|--------|
| /opt/tradingai | Does not exist |
| /opt/market-recorder | Does not exist |

---

## 11. Directory Layout

### /opt
- containerd/ (Docker runtime)
- google-cloud-ops-agent/ (GCP monitoring agent)

### /home
- joe4410joe/ (primary user)
- user/ (secondary user)

---

## 12. Ready for Repository Transfer

| Criterion | Status |
|-----------|--------|
| Python 3.11+ | PASS |
| Node.js 20+ | PASS |
| Docker Engine | PASS |
| Docker Compose | PASS |
| Git | PASS |
| systemd | PASS |
| venv support | PASS |
| Disk space (8.6G free) | PASS |
| RAM (2.1G available) | MARGINAL |
| ufw | NOT INSTALLED |
| fail2ban active | NOT RUNNING |

### Overall Verdict: READY for TradingAI deployment

The system meets all core requirements. Recommendations:
1. Install and configure ufw for firewall
2. Start and enable fail2ban service
3. Monitor memory usage (3.8G total, 2.1G available — sufficient for modest workloads but tight for heavy Docker usage)

---

## 13. Git Safety Checklist

| Rule | Status |
|------|--------|
| Commit | No |
| Push | No |
| Deploy | No |
| Copy | No |
| Delete | No |
