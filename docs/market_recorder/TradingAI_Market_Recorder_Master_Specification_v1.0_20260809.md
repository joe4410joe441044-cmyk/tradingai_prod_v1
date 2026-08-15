# TradingAI Market Recorder Master Specification v1.0

作成日: 2026-08-09
Status: Active Draft / Phase 1 Completion Baseline

---

## 0. この文書の位置づけ

本書は TradingAI Market Recorder の現行実装、完成済み機能、セキュリティ境界、TradingAI との接続、今後の残作業を一つにまとめた基準文書である。

今後の OpenCode / ChatGPT / VS Code 作業は、本書の Project Profile と Phase 1 方針を優先し、個人利用・検証用途を超える Enterprise 向け要件を勝手に追加しない。

---

# 1. Project Profile

## 1.1 利用者
- 個人利用のみ
- 単一開発者
- 外部顧客なし
- 複数ユーザー運用なし
- マルチテナントなし

## 1.2 利用目的
Market Recorder の目的は、TradingAI の検証・学習・バックテスト・Replay 用に市場データを安定して保存することである。

最優先事項:
1. 正しく記録できる
2. 安定して長時間動作できる
3. TradingAI から状態を確認できる
4. TradingAI から開始・停止できる
5. 記録結果を後続検証へ利用できる

## 1.3 非目標
Phase 1 では以下を完成条件としない。

- Enterprise PKI
- Mandatory mTLS
- 複数組織向け認証
- Public Control API
- Multi-tenant authorization
- HA Redis cluster
- Distributed control plane

これらは必要になった場合のみ Phase 2 で扱う。

---

# 2. System Architecture

```text
┌──────────────────────────────────────────────┐
│              TradingAI Contabo              │
│              vmi3480936                     │
│                                              │
│  Market Recorder UI                         │
│        │                                     │
│        ▼                                     │
│  TradingAI Backend Recorder Proxy            │
│        │                                     │
└────────┼─────────────────────────────────────┘
         │ HTTPS
         │ Source IP: 169.58.111.142
         ▼
┌──────────────────────────────────────────────┐
│              Recorder Contabo               │
│              vmi3473655                     │
│                                              │
│  Nginx / TLS / UFW                           │
│        │                                     │
│        ▼                                     │
│  Recorder Read / Control API :8090           │
│        │                                     │
│        ├── Runtime                           │
│        ├── Storage / Manifest                │
│        ├── Redis Replay / Rate Limit         │
│        └── Audit / Idempotency / Lock        │
│                                              │
└──────────────────────────────────────────────┘
```

---

# 3. Repository / Server Ownership

## 3.1 Recorder Contabo

Hostname:
`vmi3473655`

Repository:
`/opt/market-recorder`

担当:
- Recorder Runtime
- Event Pipeline
- Binance Adapter
- JSONL Recording
- Manifest
- Storage
- Archive
- Recorder Read API
- Recorder Control API
- Redis-backed security state
- Recorder-side Nginx / TLS / UFW

## 3.2 TradingAI Contabo

Hostname:
`vmi3480936`

Repository:
`/home/joe4410joe/tradingai_prod_v1`

担当:
- Recorder Backend Proxy
- DTO / Error Mapping
- Market Recorder UI
- Status / Storage / Archive visualization
- 将来の Control Proxy
- 将来の START / STOP UI

---

# 4. Recorder Runtime

完成済み要素:

- Runtime Coordinator
- Recording Session
- JSONL Writer
- Manifest
- Storage Repository
- Lifecycle State Machine
- Runtime Orchestration
- Clean Shutdown
- Live Binance WebSocket接続
- Market frame受信
- Pipeline受け渡し
- Coordinator記録

Live Smoke では実 Binance public WebSocket を利用し、実 market event の end-to-end 記録が確認済み。

---

# 5. Event Pipeline

対応済みイベントファミリ:

- ticker
- trade
- orderbook
- candle
- execution
- order
- balance
- position
- runtime
- system
- error

主要構成:
- validator
- normalizer
- pipeline
- BinanceMarketDataAdapter
- combined-stream unwrap
- deterministic IDs

---

# 6. Storage / Manifest / Archive

実装済み:
- recordings/
- recordings/tmp/
- recordings/manifests/
- recordings/archive/
- active recording management
- manifest finalization
- archive inventory
- checksum
- completed-session visibility

Read API では active `.part` を archive として扱わない。

---

# 7. Recorder Read API

公開Read API:

- `GET /api/recorder/health`
- `GET /api/recorder/status`
- `GET /api/recorder/storage`
- `GET /api/recorder/archives`

状態:
完成・Live運用中

Recorder API 本体:
`127.0.0.1:8090`

外部からの直接8090アクセス:
禁止

---

# 8. Network Security — Phase 1

採用済み:

## 8.1 HTTPS
- Nginx
- Let's Encrypt
- Public CA certificate
- TLS verification enabled

## 8.2 Firewall
- UFW active
- Recorder API 8090 public exposureなし
- 443 は TradingAI source IP allowlist
- TradingAI source: `169.58.111.142/32`

## 8.3 Public Surface
Read endpointsのみ外部公開。

Control endpointsは現時点で public Nginx surface には未公開。

---

# 9. Redis Persistence

Redis:
- installed
- active
- enabled
- localhost only
- no public 6379
- protected-mode enabled

Persistence:
- AOF enabled
- appendfsync everysec
- noeviction policy

用途:
- Replay protection
- Rate limiting

実Redis smoke:
PASS

Restart persistence:
PASS

---

# 10. Control Security Foundation

実装済み:

- Authentication foundation
- Authorization / Scope
- Replay Protection
- RedisReplayStore
- RateLimit
- RedisRateLimitStore
- Idempotency
- Async Lock
- State Machine
- Audit
- Dry-run
- Fail-closed
- Error Mapping

Production DI:
- `CONTROL_STORE_BACKEND=redis`
- Redis-backed stores active

Control test coverage:
- Authentication reject
- Authorization reject
- Replay reject
- Rate-limit reject
- Idempotent Start
- Idempotent Stop
- Concurrent Start
- Concurrent Stop
- Start/Stop race
- Invalid state
- Dry-run Start
- Dry-run Stop
- Audit success/failure
- Redis fail-closed
- Runtime start/stop success/failure
- Response contract
- Error mapping
- Read API regression

---

# 11. Control Runtime

Recorder内部の Start / Stop execution path は実装済み。

Local API:
- `/start`
- `/stop`

既存Control Gatewayを経由し、以下を通る。

```text
Request
  ↓
Authentication
  ↓
Authorization
  ↓
Replay Protection
  ↓
Rate Limit
  ↓
Idempotency
  ↓
Async Lock
  ↓
State Machine
  ↓
Dry-run / Execute
  ↓
Runtime
  ↓
Audit
  ↓
ControlResponse
```

Response:
既存 `ControlResponse.to_api_dict()` を再利用。

---

# 12. Authentication 方針変更

## 12.1 旧方針
Control Authentication Foundation は mTLS / client certificate / trusted proxy identity を想定していた。

その結果、Production activation が Credential Provisioning 待ちになった。

## 12.2 新しい Phase 1 方針
本Recorderは個人利用・TradingAI専用のため、mTLSをPhase 1完成条件から外す。

Phase 1 security boundary:

- HTTPS
- Nginx
- UFW
- TradingAI source IP allowlist
- Redis Replay Protection
- Redis Rate Limit
- Idempotency
- Lock
- Audit

## 12.3 Phase 2
必要になった場合のみ追加:

- mTLS
- Internal CA
- Client certificates
- Rotation
- Revocation

---

# 13. TradingAI Backend Proxy

完成済みRead methods:
- health
- status
- storage
- archives

Production connection:
Live HTTPS

Status contract correction済み:
- `subscribed_streams`: `list[str]`
- `uptime_seconds`: number / float

Storage:
- `runtime_bytes`: optional

---

# 14. Market Recorder UI

完成済み:

- Operation
- Status
- Storage
- Archives
- Runtime & Diagnostics

Production runtime data source:
API

Mock production fallback:
なし

UI表示:
Live Recorder data

START / STOP:
Control activation待ち

---

# 15. Phase 1 残作業

## STEP 1 — Private Control Enablement
目的:
個人利用向けtrust boundaryでControlを利用可能にする。

条件:
- mTLS不要
- 新規Enterprise認証方式を作らない
- HTTPS + IP allowlistを主要transport trust boundaryとして利用
- Replay / Rate Limit / Audit / Idempotency / Lockを維持

## STEP 2 — TradingAI Control Proxy
TradingAI BackendからRecorderへ:
- Start
- Stop

を安全にproxyする。

## STEP 3 — UI START / STOP
Market Recorder UIの:
- START
- STOP

を有効化。

## STEP 4 — Final E2E
実運用確認:

```text
TradingAI UI
  ↓
START
  ↓
TradingAI Backend
  ↓
Recorder Control API
  ↓
Recorder Runtime START
  ↓
Market Recording
  ↓
STOP
  ↓
Manifest Finalize
  ↓
Storage / Archive確認
  ↓
TradingAI UI更新
```

## STEP 5 — Completion
以下を満たした時点でPhase 1完成。

- UIからStartできる
- Recordingが開始される
- market dataが保存される
- UIからStopできる
- clean shutdown
- Manifest finalized
- Read APIへ反映
- Archiveへ反映
- Replay / Rate Limit / Audit維持
- public exposureなし

---

# 16. Phase 1 Completion Criteria

| 項目 | 状態 |
|---|---|
| Recorder Runtime | ✅ |
| Event Pipeline | ✅ |
| Binance Live Feed | ✅ |
| JSONL Recording | ✅ |
| Manifest | ✅ |
| Storage | ✅ |
| Archive | ✅ |
| Read API | ✅ |
| HTTPS | ✅ |
| Nginx | ✅ |
| UFW | ✅ |
| Source IP Allowlist | ✅ |
| Redis | ✅ |
| Replay | ✅ |
| Rate Limit | ✅ |
| Audit | ✅ |
| Idempotency | ✅ |
| Lock | ✅ |
| Control Runtime | ✅ |
| TradingAI Read Proxy | ✅ |
| TradingAI Live UI | ✅ |
| Private Control Enablement | ⏳ |
| TradingAI Control Proxy | ⏳ |
| UI START / STOP | ⏳ |
| Final E2E | ⏳ |

---

# 17. OpenCode Authoritative Project Profile

今後のRecorder / TradingAI Recorder関連指示書には以下を必ず適用する。

```text
PROJECT PROFILE — AUTHORITATIVE

This is an individual private development system.

One developer only.

Recorder is used only by TradingAI.

No public users.
No customers.
No multi-tenant deployment.
No enterprise PKI requirement.

Phase 1 does NOT require mTLS.

Reuse the existing security boundary:

- HTTPS
- Nginx
- UFW
- TradingAI source IP allowlist
- Redis replay protection
- Redis rate limiting
- Idempotency
- Lock
- Audit

Prefer the simplest architecture that safely achieves the functional goal.

Do not introduce enterprise-only infrastructure unless explicitly requested.

Primary goal:
Record market data reliably and make it usable for TradingAI verification.
```

---

# 18. Git / Work Safety

今後も以下を継続:

- 作業前に `cd` で正しいRepositoryへ移動
- hostname確認
- Git root確認
- branch確認
- HEAD確認
- `git status --short`
- staged確認
- 既存dirtyを保護

禁止:
- reset
- restore
- clean
- stash
- unrelated changes
- force operation without explicit approval

---

# 19. 最終目標

Phase 1の完成形は以下。

> TradingAI UIからMarket RecorderをSTARTし、実市場データを安定記録し、STOP後にManifest・Storage・Archiveへ正しく反映され、そのデータをTradingAIの検証・Replay・学習へ利用できること。

この目的を満たす限り、追加のEnterprise Security InfrastructureはPhase 1には要求しない。

---

# 20. 次回再開位置

次回作業開始位置:

**Private Control Enablement — Phase 1**

その後:

1. TradingAI Control Proxy
2. UI START / STOP
3. Final E2E
4. Recorder Phase 1 完成
