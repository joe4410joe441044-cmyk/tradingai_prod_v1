# RECORDER PROXY LIVE CONNECTION PREFLIGHT

**Task:** TR-RECORDER-UI-1F-1
**Status:** AUDIT COMPLETE / LIVE TEST NOT PERFORMED
**Version:** 1.0
**Date:** 2026-08-01

> 本TaskではLive接続を実施しない。本文書はGoogle Cloud Backend Proxyから
> Contabo Recorder Read APIへのLive Read-only接続を安全に実施するための
> 前提条件・承認事項・Fail-Closed設計を定義する。
> 実値・Credential・Certificate・秘密情報は本文書に記載しない。

---

## 1. Purpose

TradingAI Backend Proxy（`/api/market-recorder/*`）からContabo Recorder Read API
（`/api/recorder/*`）へLive Read-only接続するための前提条件を明確化する。

- Google CloudからContaboへの接続に必要な設定と安全条件を監査する。
- 接続に必須となる入力値を実値を作成・配置せず一覧化する。
- 不明項目は推測せずUNKNOWNとして明示する。
- Live Test実施前に必要な承認事項を定義する。
- Fail-Closed Readinessを確認する（未設定・不正値時は一切通信しない）。

本Taskの対象外: 実値設定 / Live通信 / Deploy / 環境変更 / Credential / Certificate / Firewall変更。

---

## 2. Current Architecture

```
Browser
  ↓  GET /api/market-recorder/health|status|storage|archives   （Same-Origin）
TradingAI Backend (Google Cloud, FastAPI)
  ├─ backend/api/recorder_proxy.py         Route（GET固定・固定Path・Error正規化）
  │    └─ backend/services/recorder_proxy/service.py   Service（enabled判定・Query検証・DTO検証）
  │         └─ backend/services/http/recorder_http_client.py  Client（GET-only httpx）
  │              └─ backend/services/http/recorder_url_builder.py  URL Builder（固定allowlist）
  ↓  GET /api/recorder/health|status|storage|archives
Recorder Read API (Contabo, /opt/market-recorder)
```

設計特性:

- Base URLは環境変数 `RECORDER_API_BASE_URL` のみが保持する。Client入力はURL構築に一切連結しない（SSRF防止）。
- 上流Endpoint Pathは固定allowlist（`health` / `status` / `storage` / `archives`）のみ。
- GET専用・Request Bodyなし・Cookie/Authorization/Host/Raw Header転送なし・Redirect追従なし・Retryなし。
- 応答はEnvelope `{ok, data, error}` とDTOを検証後、安全な形でUIへ返却する。

---

## 3. Required Configuration

### 3.1 Configuration Contract（監査結果）

| Env | 必須 | 既定 | 検証 |
|---|---|---|---|
| `RECORDER_API_ENABLED` | - | `false`（Fail-closed） | true/false/1/0/yes/no/on/off。不正値・空値はError（Fail-closed） |
| `RECORDER_API_BASE_URL` | enabled時必須 | なし | http/httpsのみ。credential/query/fragment/path禁止。trailing slash正規化。host必須 |
| `RECORDER_API_TIMEOUT` | - | `5.0`（秒） | 正の数値のみ。0 / 負 / 非数値はError（Fail-closed） |
| `RECORDER_API_VERIFY_TLS` | - | `true` | boolean。不正値はError（Fail-closed） |

### 3.2 監査結果（Confirmed）

- 未設定時はdisabledとなり通信しない（`RECORDER_API_ENABLED` 未設定 = 無効）。
- `RECORDER_API_ENABLED=true` でもBase URLが無ければ `configuration_error` でFail-closed。
- URL Schemeはhttp/httpsのみ。Credential（userinfo）・Query・Fragment・PathをBase URLへ埋め込めない。
- Trailing Slashは正規化（`http://host/` → `http://host`）。
- Timeoutの下限は `> 0`。最大値の上限は未定義（要確認項目、下記13.参照）。
- Loopback（localhost）・Private IPへの明示的制限は設定に無い。Base URLは環境変数のみ供給のためSSRFリスクは限定的だが、運用上の確認事項とする（下記13.参照）。
- 本Taskで新規設定名は追加しない。

---

## 4. Required Network Inputs

Live接続に必要となる入力。**実値を本Taskで作成・配置しない**。

| # | Input | 現状 |
|---|---|---|
| 1 | Recorder Hostname または IP | **UNKNOWN** |
| 2 | Recorder Read API Port | **UNKNOWN** |
| 3 | HTTP または HTTPS | **UNKNOWN**（Contractは両対応） |
| 4 | TLS Certificate発行元 | **UNKNOWN** |
| 5 | Certificate CN / SAN | **UNKNOWN** |
| 6 | Google Cloudからの到達経路 | **UNKNOWN**（推奨: Backend Proxy案B / nginx `/api/` 経路） |
| 7 | Contabo Firewall許可元 | **UNKNOWN**（Google Cloud egress IPが候補だが未承認） |
| 8 | Read APIのListen Address | **UNKNOWN** |
| 9 | Reverse Proxy有無（Contabo側） | **UNKNOWN** |
| 10 | Authentication Header有無 | **UNKNOWN**（現Contractは認証Headerを送信しない） |
| 11 | API Version / Base Path | Contract上は `/api/recorder/*`。Contabo側の実Base Pathは **UNKNOWN** |
| 12 | Read API認証の要否（Control APIと別か） | **UNKNOWN** |

> 既知事実: `recorder-contabo` は本環境でDNS解決不能（既存報告 1C/1D）。SSH alias・接続先IP/Portは本環境に存在しない。承認済み接続経路が無いためLive接続は不実施。

---

## 5. TLS Requirements

- `RECORDER_API_VERIFY_TLS` 既定は `true`（証明書検証ON）。本番既定は検証ONを維持する。
- HTTPS利用時: `httpx.AsyncClient(verify=True)` によりCertificate検証・Hostname検証を実施（システムCA Bundle）。
- Self-signed Certificateは黙って許可しない。verify ON時は検証失敗 → `market_recorder_upstream_unavailable`（Fail-closed）。
- `verify_tls=false` を本番既定にしない。LAN・承認済み経路の一時テスト時のみ許容（下記10.承認事項）。
- Expired Certificate: verify ON時は検証失敗 → Fail-closed（安全なエラーへ正規化）。
- Certificate / CA Bundle / Hostname検証のカスタム指定は現Contractに存在しない（新規設定追加はしない）。
- TLS Failureは `httpx.RequestError` 系として捕捉され `market_recorder_upstream_unavailable`（503, retryable）へ安全にマップされる。Raw詳細は公開しない。

---

## 6. Header / Authentication Boundary

現Contract（Google Cloud Proxy → Contabo）が送信するHeader:

- `Accept: application/json`（固定）
- `Host`（httpxがBase URLから自動設定）
- `User-Agent`（httpx既定。推測でカスタム追加しない）
- `Content-Type`（GET・Bodyなしのため送信しない）

送信しないもの（現Contractで必要とされないため追加しない）:

- `Authorization` Header
- `Cookie`
- `Request ID`（無い場合は追加しない）
- mTLS Client Certificate（現Contractに無い）
- 上流以外の任意のRaw Header

境界:

- Control API認証とRead API認証は混同しない。現Contractはどちらも認証Headerを送信しない。
- Read APIに認証が必要と判明した場合、Credentialは環境変数経由で管理し、Repository・`.env`・URL・Logへ配置・表示しない（要承認事項）。
- Credential未設定時はFail-closed（`RECORDER_API_ENABLED=true` でも認証情報が無ければ接続しない）。

---

## 7. Fail-Closed Behavior

| 状態 | 挙動 |
|---|---|
| `RECORDER_API_ENABLED` 未設定 / `false` | Proxy無効。`market_recorder_proxy_disabled`（503）。通信しない |
| `RECORDER_API_ENABLED=true` + Base URLなし | `market_recorder_proxy_configuration_error`（503）。通信しない |
| Base URL不正（scheme/credential/query/fragment/path） | Config Error。Fail-closed |
| Timeout不正（0/負/非数値） | Config Error。Fail-closed |
| `VERIFY_TLS`不正 | Config Error。Fail-closed |
| 上流未到達（DNS/接続拒否） | `market_recorder_upstream_unavailable`（503） |
| 上流Timeout | `market_recorder_upstream_timeout`（504） |

- Disabled状態ではService層がClient呼び出し前に停止するため、上流への通信は発生しない（Testで検証済み）。

---

## 8. Expected Error Mapping

| 事象 | Safe Code | HTTP | retryable |
|---|---|---|---|
| Configuration Disabled | `market_recorder_proxy_disabled` | 503 | No |
| Base URL Missing / Invalid URL | `market_recorder_proxy_configuration_error` | 503 | No |
| Query不正 | `market_recorder_query_invalid` | 400 | No |
| DNS Failure | `market_recorder_upstream_unavailable` | 503 | Yes |
| Connection Refused | `market_recorder_upstream_unavailable` | 503 | Yes |
| Timeout | `market_recorder_upstream_timeout` | 504 | Yes |
| TLS Failure | `market_recorder_upstream_unavailable` | 503 | Yes |
| Redirect | `market_recorder_upstream_protocol_error` | 502 | No |
| HTTP 4xx | `market_recorder_upstream_rejected` | 502 | No |
| HTTP 5xx | `market_recorder_upstream_unavailable` | 503 | Yes |
| Invalid JSON / Content-Type不正 / サイズ超過 | `market_recorder_upstream_invalid_response` | 502 | No |
| Envelope `ok !== true` | `market_recorder_upstream_rejected` | 502 | No |
| DTO Contract Mismatch | `market_recorder_upstream_invalid_response` | 502 | No |

- Path・Stack Trace・Credential・内部Exceptionは一切公開しない。
- 未知のError Codeは `market_recorder_internal_error`（500）へフォールバック。

---

## 9. Contabo graceful-200 Behavior

Contabo Integration AuditのFindingを反映:

- OpenAPI上、`/status` `/storage` `/archives` のHTTP 503は実装上ほぼ発生せず、**graceful HTTP 200**でunavailable状態が返る可能性が高い。
- **Google Cloud ProxyはHTTP 503のみに依存してはならない。**
- 現Proxyの対応（監査結果）:
  - HTTP 200 + Envelope `ok:true` + `data.status:"unavailable"` 等 → DTO検証を通過し、`data`としてそのまま返す（エラー化しない）。UI側がデータ状態として表示する。
  - HTTP 200 + Envelope `ok:false` → Envelope検証で `market_recorder_upstream_rejected`（502）としてFail-closed。
  - HTTP 200 + 不正DTO → `market_recorder_upstream_invalid_response`（502）。
- 結論: 現ProxyはEnvelope/DTO検証により、graceful-200を正しく扱う。503依存ではない。Live Testではgraceful-200応答（unavailable状態）が正常系として期待されることを明記する。

---

## 10. Live Test Preconditions

Live Testは以下をすべて満たす場合のみ実施可能。

1. Contabo接続先（Host/IP・Port・HTTPS）が正式に承認済み。
2. Google Cloud→ContaboのNetwork Route / Firewall許可（egress）が設定済み・確認済み。
3. Contabo側Read APIがListen状態である（Reverse Proxy有無を含めて確認）。
4. TLS要件が確認済み（HTTPS利用時はCertificate・Hostname検証が通る状態）。
5. Read APIの認証境界が確認済み（認証が無い、または承認済みの認証方式）。
6. `RECORDER_API_BASE_URL` を一時設定する承認が得られている（実値はRepositoryへ保存しない。一時環境変数のみ）。
7. `RECORDER_API_ENABLED=true` への切替承認が得られている。
8. テスト対象EndpointはRead-onlyのみ: `GET /api/recorder/health` `/status` `/storage` `/archives?page=1&page_size=1`。
9. 承認済みのテスト実施者・実施時刻・観測方法が定まっている。
10. 障害時のFail-Closed確認手順（下記12.）が周知されている。

Live Testで期待する結果:

- 正常系: HTTP 200 + 検証済みEnvelope/DTO。
- graceful-200: HTTP 200 + `ok:true` + unavailable状態（エラー扱いしない）。
- エラー系: 各Safe Error Codeへ正規化されること（Raw詳細非公開）。

---

## 11. Explicit Approval Required

Live接続の実施には以下を含む承認が必要（本Taskでは未承認）。

- Contabo Recorder Read APIへのRead-only接続経路構築の承認
- Google Cloud egress（Backend Host）のContabo Firewall許可の承認
- `RECORDER_API_BASE_URL` / `RECORDER_API_ENABLED=true` の一時設定の承認
- Contabo側のRead API公開条件（TLS / Reverse Proxy / 認証境界）確認の承認
- Read APIに認証が必要な場合、Credential管理方法の承認（Repository・`.env`・Logに配置しない）
- 実環境への接続テスト実施の承認

---

## 12. Rollback / Disable Procedure

Live接続の異常時・完了時は以下で安全にFail-closedへ戻す。

1. `RECORDER_API_ENABLED=false`（または環境変数削除）に戻す。
2. `RECORDER_API_BASE_URL` の実値を一時環境変数から削除する。
3. Proxyは `market_recorder_proxy_disabled`（503）でFail-closed状態へ戻る。
4. UIは無効状態表示へ戻る（Downstream変更不要）。
5. 異常が継続する場合もProxyは同様にFail-closed（個別のSafe Error Code）。Live接続への依存がUIを壊さないことを確認済み。

---

## 13. Unknown Items

Live接続に必要な情報のうち、本Task時点で不明な項目（推測で埋めない）。

- Recorder Hostname / IP / Port
- HTTP または HTTPS
- TLS Certificate発行元・CN / SAN・有効期限
- Google CloudからContaboへの到達経路（VPC / Firewall / NAT / DNS / Reverse Proxy）
- Contabo Firewall許可元（Google Cloud egress IPの承認状態）
- Read APIのListen Address / Reverse Proxy有無
- Read API認証の要否・方式（Control API認証との境界）
- API Version / Contabo側の実Base Path
- `RECORDER_API_TIMEOUT` の許容最大値（現Contractは `> 0` のみ。運用上の上限は未定義）
- Loopback / Private IP指定の運用方針（現Contractはenv専用のためSSRFリスクは限定的だが明示制限は無い）

---

## 14. Next Task Handoff

次Task（Live接続実施または接続経路構築）への引継ぎ事項。

1. 承認済み接続先情報（Host/IP・Port・HTTPS）を入力として受領する。
2. 受領後、`RECORDER_API_BASE_URL` を一時環境変数で設定し、`RECORDER_API_ENABLED=true` でLive Read-only Testを実施する（承認後）。
3. `/health` `/status` `/storage` `/archives?page=1&page_size=1` のRead-only Endpointのみ。
4. graceful-200応答（unavailable状態）を正常系として扱うこと。
5. テスト後は即Fail-closed（`RECORDER_API_ENABLED=false` / Base URL削除）へ戻す。
6. Timeout上限・Loopback/Private IP制限・認証境界は正式な設計判断を経てContractへ反映する。
