# TR-MIGRATION-1C: Google Cloud Dependency Audit

**Task ID:** TR-MIGRATION-1C
**Date:** 2026-08-02
**Source:** Google Cloud (tradingai-prod-v1)
**Destination:** New Contabo Cloud VPS 8
**Parent Tasks:** TR-MIGRATION-1A (Inventory), TR-MIGRATION-1B (Cleanup Plan)
**Status:** DEPENDENCY AUDIT COMPLETE

---

## 1. Safety Verification

| Check | Value |
|---|---|
| Working Directory | `/home/joe4410joe/tradingai_prod_v1` |
| Hostname | `tradingai-prod-v1` |
| User | `joe4410joe` |
| Platform | Linux Debian 12 (bookworm) |
| Kernel | 6.1.0-51-cloud-amd64 (GCP cloud kernel) |
| Virtualization | google |
| Hardware Vendor | Google |
| Hardware Model | Google Compute Engine |
| Machine Type | e2-custom-2-4096 |
| CPU | 2 vCPU (Intel Broadwell) |
| Memory | 3.8 GB |
| Disk | 20 GB Persistent Balanced (/dev/sda1, 55% used) |
| Zone | asia-northeast1-b |
| Project | named-haven-483407-j7 |
| Instance ID | 3978372250234409839 |
| Internal IP | 10.146.0.7 |
| External IP | 35.194.104.74 (Static / ONE_TO_ONE_NAT) |
| Branch | `main` |
| HEAD | `d57de0439576c1134a67ce6055f65fc4a1c084e0` |
| No copy/delete/commit | CONFIRMED |
| No deploy/systemctl change | CONFIRMED |

---

## 2. GCP Infrastructure Inventory

### 2.1 Google-Specific Systemd Services

| Service | State | Dependency Level |
|---|---|---|
| `google-cloud-ops-agent` | disabled / inactive | LOW - Not running |
| `google-cloud-ops-agent-fluent-bit` | static | NONE - Part of ops-agent |
| `google-cloud-ops-agent-opentelemetry-collector` | static | NONE - Part of ops-agent |
| `google-disk-expand` | enabled / one-shot (completed) | LOW - Disk resize |
| `google-guest-agent` | disabled / inactive | MEDIUM - OS Login keys |
| `google-guest-agent-manager` | **active (running)** | **HIGH** - Plugin manager |
| `google-guest-compat-manager` | **active (running)** | **HIGH** - Metadata / SSH compat |
| `google-osconfig-agent` | **active (running)** | **HIGH** - OS config/patching |
| `google-oslogin-cache` | timer-driven / one-shot | MEDIUM - NSS user cache |
| `google-shutdown-scripts` | enabled / one-shot (completed) | LOW - Shutdown hooks |
| `google-startup-scripts` | enabled / one-shot (completed) | LOW - Startup hooks |
| `gce-workload-cert-refresh` | static / inactive | NONE - Not used |

**GCP services running on this instance: 3 (guest-agent-manager, guest-compat-manager, osconfig-agent)**

### 2.2 Installed GCP Packages

| Package | Purpose |
|---|---|
| `google-cloud-cli` (563.0.0) | gcloud CLI |
| `google-cloud-ops-agent` (2.66.0) | Monitoring/Logging agent |
| `google-guest-agent` (20260329.00) | Guest OS agent |
| `google-cloud-packages-archive-keyring` | GCP GPG keyring |

### 2.3 GCP Metadata Server

- **Endpoint:** `169.254.169.254` (reachable, full metadata exposed)
- **DNS:** Nameservers point exclusively to `169.254.169.254`
- **Search domains:** `asia-northeast1-b.c.named-haven-483407-j7.internal`, `c.named-haven-483407-j7.internal`, `google.internal`
- **Service Account:** `152878496504-compute@developer.gserviceaccount.com`
- **Scopes:** devstorage.read_only, logging.write, monitoring.write, service.management.readonly, servicecontrol, trace.append

### 2.4 GCP Networking

| Item | Value | GCP Dependency |
|---|---|---|
| External IP | 35.194.104.74 | GCP Static IP / ONE_TO_ONE_NAT |
| Internal IP | 10.146.0.7/32 | GCP VPC DHCP |
| Gateway | 10.146.0.1 | GCP VPC default gateway |
| Interface | ens4 (mtu 1460) | GCP VIRTIO_NET |
| MAC | 42:01:0a:92:00:07 | GCP assigned |
| DNS | 169.254.169.254 (x2) | GCP metadata DNS |
| Network Tags | `allow-8000`, `http-server` | GCP Firewall rules |
| Firewall | ufw: inactive, iptables: Docker only | GCP Firewall (external) |
| Netplan | DHCP on en*/eth* | Standard (portable) |

---

## 3. Application-Level Google Cloud Dependencies

### 3.1 Hardcoded IP: `35.194.104.74` (GCP Static External IP)

**HIGH SEVERITY - Must change on migration**

| # | File | Line | Content | Type |
|---|---|---|---|---|
| 1 | `deploy/nginx-tradingai.conf` | 3 | `server_name 35.194.104.74;` | Nginx after-IP |
| 2 | `frontend/vite.config.js` | 12 | `target: "http://35.194.104.74:8001"` | Dev proxy |
| 3 | `frontend/tradingai.conf` | 3 | `server_name 35.194.104.74;` | Nginx after-IP |
| 4 | `frontend/_legacy_hooks/useEventWS.js` | 3 | `const WS_URL = "ws://35.194.104.74:8001/ws/events"` | WS URL |
| 5 | `frontend/_legacy_hooks/useBotData.js` | 22 | `const wsUrl = "ws://35.194.104.74:8001/ws"` | WS URL |
| 6 | `frontend/_legacy_hooks/useWebSocket.js` | 10 | `const wsUrl = "ws://35.194.104.74:8001/ws"` | WS URL |
| 7 | `frontend/src/components/control/TradeConfigPanel.jsx` | 79 | `fetch("http://35.194.104.74:8001/config")` | API call |
| 8 | `frontend/deploy/deploy_all.bat` | 13 | `set VPS_IP=35.194.104.74` | Deploy script |
| 9 | `frontend/e2e/support/networkIsolation.js` | 7 | `"35.194.104.74"` in PRODUCTION_HOSTS | Test isolation |
| 10 | `frontend/e2e/production-isolation.spec.js` | 25,95 | Hardcoded in test | E2E test |
| 11 | `./.env` (not tracked) | 1 | `REACT_APP_API_BASE=http://169.58.111.142:8000` | Env config |

**Total hardcoded IP references: 11 locations across 10 files**

### 3.2 Hardcoded IP: `34.85.66.137` (Old GCP IP)

| # | File | Content |
|---|---|---|
| 1 | `sample.env` | `REACT_APP_API_BASE=http://34.85.66.137:8000` |

### 3.3 GCP Metadata Server Reference: `169.254.169.254`

| Location | Usage |
|---|---|
| `/etc/resolv.conf` | DNS nameserver (2x) |
| Route table | Static route via 10.146.0.1 |

### 3.4 GCP Project & Service Account References

| Item | Value | Found In |
|---|---|---|
| Project ID | `named-haven-483407-j7` | gcloud config, DNS, metadata |
| Service Account | `152878496504-compute@developer.gserviceaccount.com` | gcloud config, metadata |
| gcloud CLI | `/usr/bin/gcloud` (auth'd as service account) | System |
| gsutil CLI | `/usr/bin/gsutil` | System |

---

## 4. System-Level Google Cloud Dependencies

### 4.1 SSH Key Management

- **OS Login:** Disabled (google-oslogin-cache exists but one-shot only)
- **Metadata SSH keys:** Keys managed via GCP instance metadata
- **Expired keys detected in logs:** google-ssh keys with expiration (2026-08-01)
- **Current SSH config:** `PasswordAuthentication no`, `PermitRootLogin no`
- **Key types in metadata:** ssh-rsa, ecdsa-sha2-nistp256, ssh-ed25519
- **Users managed via metadata:** joe4410joe, user

### 4.2 DNS Resolution

```
Current resolv.conf:
  nameserver 169.254.169.254  (GCP metadata DNS - x2)
  search asia-northeast1-b.c.named-haven-483407-j7.internal
        c.named-haven-483407-j7.internal
        google.internal
```

### 4.3 Kernel

- **Running:** `6.1.0-51-cloud-amd64` (GCP-optimized cloud kernel)
- **Migration Impact:** On Contabo, standard Debian kernel will be used. No functional difference expected for this workload.

### 4.4 Network Interface

- **Current:** `ens4` with DHCP from GCP VPC
- **MTU:** 1460 (GCP VPC default, lower than standard 1500)
- **Netplan config:** Standard DHCP (portable - no GCP-specific settings)

### 4.5 Time Synchronization

- **Service:** `systemd-timesyncd` (active)
- **Time zone:** Asia/Tokyo (JST)
- **Status:** Synchronized via internal NTP
- **Migration Impact:** Standard systemd-timesyncd works on any VPS. No GCP dependency.

---

## 5. CORS / Allow-Origin Configuration

| Component | Setting | GCP Dependency |
|---|---|---|
| Backend (FastAPI CORS) | `allow_origins=["*"]` | No GCP dependency |
| Nginx | No CORS headers set | No GCP dependency |
| AI Advisor Gateway | No CORS headers (intentional) | No GCP dependency |

---

## 6. External Service Dependencies (Not GCP)

These are NOT Google Cloud dependencies but are relevant to migration:

| Service | Dependency | Notes |
|---|---|---|
| Binance API | Exchange | IP whitelist consideration |
| Bitget API | Exchange | IP whitelist consideration |
| KuCoin API | Exchange | IP whitelist consideration |
| Bybit API | Exchange | IP whitelist consideration |
| OpenAI API | AI Advisor provider | OPENAI_API_KEY (from systemd creds or env) |
| Telegram Bot API | Notification | TELEGRAM_TOKEN in .env |
| Market Recorder (Contabo) | Recorder Proxy upstream | Already on Contabo (per docs) |

---

## 7. Dependency Classification

### 7.1 Category ①: ���須移行 (Must Migrate)

These items are part of the application or the server runtime and must exist on Contabo:

| # | Item | Details |
|---|---|---|
| 1 | Project source code | Full repo (Category A: ~12-15 MB) |
| 2 | `systemd/tradingbot.service` | Systemd unit (path updates needed) |
| 3 | `deploy/nginx-tradingai.conf` | Nginx config (IP update needed) |
| 4 | `deploy/systemd/*` | Systemd templates |
| 5 | `deploy/nginx/*` | Nginx templates |
| 6 | `tools/*` | Shell tool scripts |
| 7 | `.env` template | Recreated with new IP |
| 8 | `frontend/.env.production` | Vite prod config |
| 9 | Python venv | Recreate: `pip install -r requirements.txt` |
| 10 | Node.js (v20+) | Install matching version |
| 11 | NPM packages | Recreate: `npm ci` in frontend/ |
| 12 | OpenSSH server | Standard on any Linux |
| 13 | systemd-timesyncd | Standard time sync |
| 14 | cron | Standard scheduler |

### 7.2 Category ②: Contaboで再設定 (Needs Reconfiguration on Contabo)

Items that exist on both platforms but need reconfiguration for the new environment:

| # | Item | Current Value | New Value | Priority |
|---|---|---|---|---|
| 1 | External IP (all hardcoded refs) | `35.194.104.74` | Contabo VPS IP | **CRITICAL** |
| 2 | `.env` REACT_APP_API_BASE | `http://169.58.111.142:8000` | Contabo VPS IP | **CRITICAL** |
| 3 | `sample.env` REACT_APP_API_BASE | `http://34.85.66.137:8000` | Contabo VPS IP | HIGH |
| 4 | `deploy/nginx-tradingai.conf` server_name | `35.194.104.74` | Contabo VPS IP | **CRITICAL** |
| 5 | `/etc/nginx/sites-available/tradingai` server_name | `35.194.104.74` | Contabo VPS IP | **CRITICAL** |
| 6 | `frontend/vite.config.js` proxy target | `http://35.194.104.74:8001` | `http://127.0.0.1:8001` (or new IP) | HIGH |
| 7 | `frontend/tradingai.conf` server_name | `35.194.104.74` | Contabo VPS IP | MEDIUM |
| 8 | `frontend/_legacy_hooks/*.js` WS URLs | `ws://35.194.104.74:8001/...` | Relative or new IP | MEDIUM |
| 9 | `frontend/src/components/control/TradeConfigPanel.jsx` | `fetch("http://35.194.104.74:8001/config")` | Relative API | **HIGH** |
| 10 | `frontend/deploy/deploy_all.bat` VPS_IP | `35.194.104.74` | Contabo VPS IP | LOW |
| 11 | `frontend/e2e/support/networkIsolation.js` | `"35.194.104.74"` in PRODUCTION_HOSTS | Contabo VPS IP | MEDIUM |
| 12 | DNS resolution | `169.254.169.254` (GCP metadata DNS) | Contabo/public DNS (e.g., 8.8.8.8) | **CRITICAL** |
| 13 | Systemd service WorkingDirectory | `/home/joe4410joe/tradingai_prod_v1` | Same or updated path | **CRITICAL** |
| 14 | Systemd service ExecStart | venv/python path | Updated path | **CRITICAL** |
| 15 | SSH keys | GCP metadata-based | Local `/home/user/.ssh/authorized_keys` | **CRITICAL** |
| 16 | Firewall | GCP Firewall tags (`allow-8000`, `http-server`) | Contabo Firewall or ufw/iptables | **CRITICAL** |
| 17 | Nginx | /etc/nginx/sites-available/tradingai | Copy + update config | **CRITICAL** |
| 18 | MTU | 1460 (GCP VPC) | 1500 (standard) | LOW |
| 19 | Exchange API IP whitelist | GCP IP whitelisted | Add Contabo IP | **HIGH** |
| 20 | AI Advisor systemd credentials | `/etc/credstore.encrypted/...` | Re-deploy on Contabo | **HIGH** |
| 21 | Recorder Proxy upstream config | RECORDER_PROXY env vars | Update if needed | MEDIUM |
| 22 | `backend/main.py` AI Advisor config | `EnvironmentProductionConfigLoader()` | Same, relies on env vars | LOW |

### 7.3 Category ③: 廃止可能 (Can Be Removed)

Items that are unnecessary on Contabo:

| # | Item | Reason |
|---|---|---|
| 1 | `google-cloud-ops-agent` + sub-services | GCP monitoring/logging agent |
| 2 | `google-osconfig-agent` | GCP OSConfig management |
| 3 | `google-guest-agent-manager` | GCP guest plugin management |
| 4 | `google-guest-compat-manager` | GCP guest compatibility layer |
| 5 | `google-guest-agent` (disabled) | GCP guest agent |
| 6 | `google-disk-expand` | GCP disk auto-resize |
| 7 | `google-shutdown-scripts` | GCP shutdown hooks |
| 8 | `google-startup-scripts` | GCP startup hooks |
| 9 | `google-oslogin-cache` + timer | GCP OS Login NSS caching |
| 10 | `gce-workload-cert-refresh` | GCP workload certificate |
| 11 | `google-cloud-cli` (gcloud) | GCP CLI tools |
| 12 | `gsutil` | GCP Cloud Storage CLI |
| 13 | `google-cloud-packages-archive-keyring` | GCP package repository key |
| 14 | `google-guest-agent` (package) | GCP guest agent binary |
| 15 | `/etc/default/instance_configs.cfg` | GCP instance configuration |
| 16 | Metadata server route (`169.254.169.254`) | GCP metadata endpoint |
| 17 | GCP-specific DNS search domains | `*.internal`, `google.internal` |
| 18 | GCP service account | `152878496504-compute@...` |
| 19 | GCP project references | `named-haven-483407-j7` |
| 20 | GCP network tags | `allow-8000`, `http-server` |
| 21 | GCP custom kernel (`-cloud-amd64`) | Automatically replaced on fresh install |

### 7.4 Category ④: Google専用 (Google-Only)

These items are inherently Google Cloud and have no equivalent on Contabo. They are simply not present or not needed:

| # | Item | Description |
|---|---|---|
| 1 | Instance Metadata Server (169.254.169.254) | GCP-proprietary metadata API |
| 2 | OS Login via metadata SSH keys | GCP SSH key management |
| 3 | Cloud NAT / ONE_TO_ONE_NAT | GCP external IP mapping |
| 4 | GCP VPC (10.146.0.0/20) | Internal GCP network |
| 5 | GCP Static IP reservation | Static external IP |
| 6 | GCP Persistent Disk (sda1) | Managed block storage |
| 7 | GCP Machine Type (e2-custom) | Instance sizing |
| 8 | GCP Service Account auth | gcloud auto-auth via metadata |
| 9 | GCP IAM scopes | Permission boundaries on GCP |
| 10 | GCP zones/regions (asia-northeast1-b) | GCP geography |
| 11 | GCP project hierarchy | named-haven-483407-j7 |
| 12 | Instance lifecycle hooks (startup/shutdown) | metadata scripts |

### 7.5 Category ⑤: 不明 (Uncertain)

Items requiring user clarification:

| # | Item | Question | Default Assumption |
|---|---|---|---|
| 1 | Recorder Proxy upstream | Is the Market Recorder already on Contabo? | Per docs (TR-RECORDER-UI-1D), upstream is on Contabo. OK. |
| 2 | AI Advisor credentials deployment | How to deploy `/etc/credstore.encrypted/` on Contabo? | Same procedure as documented in `systemd-credential-smoke-runbook.md` |
| 3 | Exchange API IP whitelist | Which exchanges whitelist the current GCP IP? | Likely Binance, Bitget, KuCoin, Bybit. Need manual check. |
| 4 | Telegram Bot | Any Google dependency? | No. Token-based auth, no IP binding needed. |
| 5 | `deploy_local.sh` vs `deploy_vps.sh` | Which deploy script is authoritative for Contabo? | Both reference `tradingbot` service. `deploy_vps.sh` is production. |
| 6 | `backend/main.py` runs AI Advisor in production mode | Does this work without systemd credential store? | Uses `EnvironmentCredentialLoader` which can read from env vars as fallback. |

---

## 8. Migration Blocker Analysis

### 8.1 Critical Blockers

| # | Blocker | Severity | Action Required |
|---|---|---|---|
| B1 | **11 hardcoded IP references** to `35.194.104.74` across 10 files | **BLOCKING** | Update all to new Contabo VPS IP before service start |
| B2 | **DNS resolution** hardwired to GCP metadata DNS (169.254.169.254) | **BLOCKING** | Replace with standard DNS (resolv.conf) |
| B3 | **SSH access** currently via GCP metadata key management | **BLOCKING** | Set up local `authorized_keys` on Contabo |
| B4 | **Firewall** managed exclusively via GCP tags | **BLOCKING** | Set up ufw/nftables on Contabo |
| B5 | **Systemd service paths** reference current home directory | **BLOCKING** | Update unit file paths if username/path differs |

### 8.2 High-Impact Blockers

| # | Blocker | Severity | Action Required |
|---|---|---|---|
| B6 | **Exchange API IP whitelist** likely restricts to GCP IP | HIGH | Add Contabo IP to each exchange API allowlist |
| B7 | **AI Advisor systemd credentials** stored in `/etc/credstore.encrypted/` | HIGH | Re-deploy credential store on Contabo per runbook |
| B8 | **Nginx config** references GCP IP as `server_name` | HIGH | Update to Contabo IP or domain |

### 8.3 Medium-Impact Items

| # | Item | Severity | Action Required |
|---|---|---|---|
| B9 | `TradeConfigPanel.jsx` fetches hardcoded external IP for `/config` | MEDIUM | Should use relative URL `/config` instead |
| B10 | Legacy hooks with hardcoded WS URLs | MEDIUM | Fix or remove (deprecated) |
| B11 | E2E tests reference production IP | MEDIUM | Update test fixtures |
| B12 | `.env` references IP `169.58.111.142` (not the GCP external IP) | MEDIUM | Verify and update |

---

## 9. Migration Risk Matrix

| # | Risk | Severity | Probability | Impact | Mitigation |
|---|---|---|---|---|---|
| R1 | Missed hardcoded IP breaks frontend connectivity | Critical | High | WS/API unreachable from browser | Full grep audit; run `grep -r "35.194.104.74"` on Contabo after migration |
| R2 | Exchange APIs reject connections from new IP | High | High | Trading bot cannot place orders | Whitelist Contabo IP on all exchange dashboards before cutover |
| R3 | DNS resolution fails on Contabo | High | Medium | All external API calls fail | Verify resolv.conf; test `curl https://api.binance.com` |
| R4 | SSH lockout on Contabo | Critical | Low | Cannot access server | Set up SSH keys before closing GCP session |
| R5 | AI Advisor OpenAI auth fails | High | Medium | AI signals stop | Migrate `OPENAI_API_KEY` credential to Contabo |
| R6 | Timezone mismatch causes timestamp errors | Medium | Low | Log/candle timing off | Set `timedatectl set-timezone Asia/Tokyo` |
| R7 | Firewall blocks port 8001 | Critical | Low | Backend unreachable | Pre-configure firewall rules on Contabo |
| R8 | Python/Node version mismatch | Medium | Medium | Runtime errors | Match versions: Python 3.11, Node v20 |
| R9 | MTU difference (1460 vs 1500) causes connectivity issues | Low | Low | Packet fragmentation | Standard 1500 MTU is fine for all endpoints |
| R10 | GCP kernel features depended upon | Low | Very Low | Unknown runtime issues | Standard Debian kernel handles all Python/Node workloads |

---

## 10. Migration Order (Recommended Sequence)

```
Phase 0: Pre-flight (On GCP - read only)
  [0.1] Capture snapshot of all running services
  [0.2] Record all IP addresses and current configuration
  [0.3] Verify git is fully pushed
  [0.4] Document all exchange API whitelist settings

Phase 1: Contabo VPS Setup
  [1.1] Install OS (Debian 12)
  [1.2] Create user `joe4410joe`
  [1.3] Configure SSH keys (local authorized_keys)
  [1.4] Set timezone Asia/Tokyo
  [1.5] Configure firewall (ports 22, 80, 443, 8001)
  [1.6] Install Python 3.11, Node v20, NPM 10, nginx

Phase 2: Code Transfer
  [2.1] Create tar.gz of Category A files (per TR-MIGRATION-1B)
  [2.2] Transfer to Contabo
  [2.3] Extract to target directory
  [2.4] Verify directory structure

Phase 3: Environment Setup
  [3.1] Create Python venv + pip install -r requirements.txt
  [3.2] cd frontend && npm ci
  [3.3] npm run build (generate dist/)
  [3.4] Create .env from template with Contabo IP
  [3.5] Deploy AI Advisor credentials to /etc/credstore.encrypted/

Phase 4: IP Rename (ALL 11 hardcoded references)
  [4.1] deploy/nginx-tradingai.conf: 35.194.104.74 → NEW_IP
  [4.2] frontend/vite.config.js: 35.194.104.74 → 127.0.0.1 or NEW_IP
  [4.3] frontend/tradingai.conf: 35.194.104.74 → NEW_IP
  [4.4] frontend/_legacy_hooks/useEventWS.js: 35.194.104.74 → NEW_IP
  [4.5] frontend/_legacy_hooks/useBotData.js: 35.194.104.74 → NEW_IP
  [4.6] frontend/_legacy_hooks/useWebSocket.js: 35.194.104.74 → NEW_IP
  [4.7] frontend/src/components/control/TradeConfigPanel.jsx: 35.194.104.74 → /api (relative)
  [4.8] frontend/deploy/deploy_all.bat: 35.194.104.74 → NEW_IP
  [4.9] frontend/e2e/support/networkIsolation.js: 35.194.104.74 → NEW_IP
  [4.10] frontend/e2e/production-isolation.spec.js: 35.194.104.74 → NEW_IP
  [4.11] .env: REACT_APP_API_BASE → http://NEW_IP:8000

Phase 5: Service Configuration
  [5.1] Update systemd unit file paths
  [5.2] Copy nginx config to /etc/nginx/sites-available/
  [5.3] nginx -t (validate config)
  [5.4] systemctl daemon-reload
  [5.5] systemctl enable tradingbot nginx

Phase 6: Exchange API Whitelist
  [6.1] Add Contabo IP to Binance API allowlist
  [6.2] Add Contabo IP to Bitget API allowlist
  [6.3] Add Contabo IP to KuCoin API allowlist
  [6.4] Add Contabo IP to Bybit API allowlist

Phase 7: Smoke Test
  [7.1] systemctl start tradingbot
  [7.2] Verify backend: curl http://127.0.0.1:8001/
  [7.3] Verify AI Advisor health
  [7.4] Verify Recorder Proxy connectivity
  [7.5] Verify WebSocket connection
  [7.6] Verify frontend loads via nginx
  [7.7] Verify Telegram notifications

Phase 8: Cutover
  [8.1] Monitor Contabo services for 1-2 hours
  [8.2] If stable, stop GCP services (systemctl stop tradingbot)
  [8.3] Keep GCP instance for 24-48 hours as rollback
  [8.4] Remove GCP Exchange API whitelist entries

Phase 9: GCP Cleanup
  [9.1] Cancel GCP Static IP (35.194.104.74)
  [9.2] Terminate GCP instance (tradingai-prod-v1)
  [9.3] Remove project resources if no longer needed
```

---

## 11. Quick Reference: Files to Modify

### 11.1 IP Address Change (35.194.104.74 → NEW_IP)

```
[ ] deploy/nginx-tradingai.conf                          # server_name
[ ] frontend/vite.config.js                               # proxy target
[ ] frontend/tradingai.conf                               # server_name
[ ] frontend/_legacy_hooks/useEventWS.js                  # WS_URL
[ ] frontend/_legacy_hooks/useBotData.js                  # wsUrl
[ ] frontend/_legacy_hooks/useWebSocket.js                # wsUrl
[ ] frontend/src/components/control/TradeConfigPanel.jsx  # fetch URL
[ ] frontend/deploy/deploy_all.bat                        # VPS_IP
[ ] frontend/e2e/support/networkIsolation.js              # PRODUCTION_HOSTS
[ ] frontend/e2e/production-isolation.spec.js             # fetch/WS URLs
```

### 11.2 Other Changes

```
[ ] .env: REACT_APP_API_BASE                             # Update IP
[ ] sample.env: REACT_APP_API_BASE                       # Update IP
[ ] /etc/resolv.conf                                     # Replace DNS
[ ] /etc/systemd/system/tradingbot.service               # Update paths
[ ] Exchange API dashboards                              # Whitelist new IP
[ ] /etc/credstore.encrypted/                            # Deploy credentials
```

---

## 12. Git Safety Confirmation

| Rule | Status |
|---|---|
| No git add | CONFIRMED |
| No git commit | CONFIRMED |
| No git push | CONFIRMED |
| No git restore | CONFIRMED |
| No git reset | CONFIRMED |
| No git clean | CONFIRMED |
| No scp/rsync/cp/mv/rm | CONFIRMED |
| No tar/zip | CONFIRMED |
| No systemctl restart/stop/disable/enable | CONFIRMED |
| No firewall change | CONFIRMED |
| No deploy | CONFIRMED |
| Repository unchanged (except report) | CONFIRMED |

---

*Report generated: 2026-08-02 | Task TR-MIGRATION-1C*
