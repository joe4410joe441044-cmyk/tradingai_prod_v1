# RECORDER PROXY LIVE ENDPOINT APPROVAL

**Task:** TR-RECORDER-UI-1F-2A
**Status:** AUDIT COMPLETE / CONNECTION INPUT NOT APPROVED / LIVE TEST NOT PERFORMED
**Version:** 1.0
**Date:** 2026-08-01

> 本TaskはLive通信・実値設定を行わない。Repository内の既存文書・設定・Contractのみを
> 調査し、Contabo Recorder Read APIへの接続入力（Connection Input）を分類・一覧化し、
> 次のLive Smoke Testへ渡す接続承認パッケージを準備する。実値・Credential・
> Certificate・秘密情報は本文書に記載しない。

---

## 1. Purpose

Google Cloud Backend Proxy（`/api/market-recorder/*`）からContabo Recorder Read API
（`/api/recorder/*`）へLive Read-only接続するために必要な接続入力を、Repository内の
既存根拠に基づいて監査・分類する。

- 接続先候補を根拠とともに一覧化する。
- 確定済み項目（CONFIRMED）と未確定項目（UNKNOWN）を明確に分離する。
- 推測した値を確定扱いしない（承認済みの根拠が存在しない値はCANDIDATE / UNKNOWNのまま）。
- 複数の値が存在する場合はCONFLICTとして報告し、独自判断で選択しない。
- ユーザー承認が必要な項目を明示し、Fail-Closed設計を維持する。

本Taskの完了条件はLive通信ではなく、承認可能な接続入力の特定と分類である。

---

## 2. Source Documents Reviewed

| # | Document | Path |
|---|---|---|
| 1 | TradingAI Constitution | `docs/00_CONSTITUTION/`（README / 00 / 01 / 02 / 03 / 04 / 05 / CHANGELOG） |
| 2 | OpenCode Parallel Development Standard v2.0 | `docs/opencode/TradingAI_Platform_OpenCode_Parallel_Development_Standard_v2.0.md` |
| 3 | Market Recorder Master Specification | `docs/market_recorder/01_Market_Recorder_Master_Specification.md` |
| 4 | Recorder Proxy Live Connection Preflight（1F-1） | `docs/market_recorder/RECORDER_PROXY_LIVE_CONNECTION_PREFLIGHT.md` |
| 5 | Recorder UI 1B2 Report | `docs/market_recorder/TR-RECORDER-UI-1B2_REPORT.md` |
| 6 | Recorder UI 1C Report | `docs/market_recorder/TR-RECORDER-UI-1C_REPORT.md` |
| 7 | Recorder UI 1D Report | `docs/market_recorder/TR-RECORDER-UI-1D_REPORT.md` |
| 8 | Recorder UI 1E Report | `docs/reports/TR-RECORDER-UI-1E_REPORT.md` |
| 9 | Recorder Proxy Config Contract | `backend/config/recorder_proxy.py` |
| 10 | Recorder Proxy URL Builder Contract | `backend/services/http/recorder_url_builder.py` |
| 11 | Recorder Proxy Config Tests | `tests/test_recorder_proxy_config.py` |
| 12 | Recorder Proxy URL Builder Tests | `tests/test_recorder_proxy_url_builder.py` |
| 13 | Deploy Nginx Config（Google Cloud側） | `deploy/nginx-tradingai.conf` |

Repository内にContabo側の公式API Contract（OpenAPI `market-recorder-api-v0.1.0.yaml` /
`API_CONTRACT_v0.1.1.md`）は存在しない（Contabo側所管・本環境から参照不可）。

---

## 3. Endpoint Input Classification

各項目を `CONFIRMED` / `CANDIDATE` / `UNKNOWN` / `CONFLICT` / `NOT REQUIRED` に分類する。
実値は作成・配置しない。分類はRepository内の既存根拠のみに基づく。

| # | Input | Classification | 根拠（Source） |
|---|---|---|---|
| 1 | Host | **UNKNOWN** | `recorder-contabo` は本環境でDNS解決不能。Repository・docs・known_hosts・SSH configにHost/IPの記載なし（1C:198 / 1D:98-100 / 1E:159 / Preflight:95） |
| 2 | Port | **UNKNOWN** | Repository・docs・testsにContabo側Read API Portの記載なし（1D:100 / 1E:159 / Preflight:83） |
| 3 | Scheme（HTTP / HTTPS） | **UNKNOWN**（Contractは両対応） | Config Contractはhttp/httpsのみ許可。Contabo側の実Schemeは未承認（Preflight:84 / recorder_proxy.py:57） |
| 4 | Base Path | **CONFIRMED（Contract側）** / Contabo側実Base Pathは**UNKNOWN** | 上流Endpoint Path `/api/recorder/*` は固定allowlistとしてContract確定（recorder_url_builder.py:11-16 / 1E:98-101）。Contabo側の実Base Pathは未確認（Preflight:92） |
| 5 | API Version | **UNKNOWN** | OpenAPI v0.1.0 / API_CONTRACT v0.1.1 はContabo側所管で本Repositoryに不在（1D:35）。Path・URLにVersion情報なし |
| 6 | TLS Verification | **CONFIRMED**（`true` 既定） | `RECORDER_API_VERIFY_TLS` 既定 `true`、本番既定は検証ON（recorder_proxy.py:20 / Preflight:62,101） |
| 7 | Certificate Type | **UNKNOWN** | Public CA / Private CA / Self-signed の根拠なし。Preflight:85,87 にて発行元・CN/SAN不明 |
| 8 | Authentication（Read API要否） | **UNKNOWN**（現在のContractは認証Headerを送信しない = 現行境界では**NOT REQUIRED**） | Preflight:91,129-133。Read API認証要否・Control APIとの境界は未確認 |
| 9 | Authorization Header | **NOT REQUIRED**（現Contract境界） / 上流が必要とするかは**UNKNOWN** | 現ProxyはAuthorization Headerを送信しない（Preflight:121）。必要と判明時はCredential管理の承認が必要 |
| 10 | Firewall | **UNKNOWN** | Contabo側Inbound許可・Google Cloud側Outbound許可は未設定・未承認（Preflight:88） |
| 11 | Allowlisted Source（許可元IP） | **CANDIDATE** | Google Cloud Backend外部IP `35.194.104.74`（1D:15,210）。許可元として承認済みではなく候補 |
| 12 | Timeout | **CONFIRMED**（既定 `5.0`秒・`> 0`） / 上限は**UNKNOWN** | recorder_proxy.py:19,76-85 / Preflight:61,249 |
| 13 | Read API Availability | **UNKNOWN** | 本環境から到達不能・Live未実施（1C:198 / 1D:111 / 1E:160）。待機状態は不明 |
| 14 | Rollback Procedure | **CONFIRMED** | Preflight §12にFail-Closed復帰手順が確定（本文書§10に再掲） |

### 接続先候補（Host）

| 候補 | 種別 | Classification | 根拠 |
|---|---|---|---|
| `recorder-contabo` | SSH alias / Host名 | **UNKNOWN**（本環境で未設定・DNS解決不能） | 1C:198 / 1D:98-99 |
| `/opt/market-recorder` | Contabo側ディレクトリ（Base Pathではない） | **NOT REQUIRED**（接続入力ではない） | 1D:17 / 1E:16 |
| Google Cloud Backend `tradingai_prod1`（10.146.0.7 / 35.194.104.74） | 接続元 | **CONFIRMED（接続元）** / **CANDIDATE（許可元）** | 1D:15 |

### CONFLICT報告

本Taskの調査範囲では、同一入力に対して互いに矛盾する複数値は検出されなかった。
Repository内にContabo接続先の実値が存在しないため、CONFLICT該当項目なし。

---

## 4. Candidate Base URL Structure

承認対象となるBase URLの構造（Config Contractで強制される形式）:

```
<scheme>://<host>:<port>
```

- 実値は設定しない。Live Test時に一時環境変数のみで指定する。
- Base URLには **Pathを含めてはならない**（`/api/recorder` をBase URLへ含めるとConfig ErrorでFail-closed）。
- Base URLにQuery / Fragment / Userinfo（Credential埋め込み）を含めてはならない。
- Trailing Slashは正規化（`http://host/` → `http://host`）。
- Endpoint Path（`/api/recorder/*`）はURL Builderの固定allowlistが重複付加するため、
  Base URLへEndpoint Pathを重複追加しないこと。

各Proxy Endpointの展開（実通信は行わない）:

| 公開Endpoint | 展開後Upstream URL | 根拠 |
|---|---|---|
| `GET /api/market-recorder/health` | `<APPROVED_BASE_URL>/api/recorder/health` | url_builder.py:12 |
| `GET /api/market-recorder/status` | `<APPROVED_BASE_URL>/api/recorder/status` | url_builder.py:13 |
| `GET /api/market-recorder/storage` | `<APPROVED_BASE_URL>/api/recorder/storage` | url_builder.py:14 |
| `GET /api/market-recorder/archives` | `<APPROVED_BASE_URL>/api/recorder/archives`（Queryはallowlistのみ） | url_builder.py:15 |

---

## 5. TLS Decision

| 項目 | 分類 | 内容 |
|---|---|---|
| `RECORDER_API_VERIFY_TLS` 既定 | CONFIRMED | `true`（Certificate検証・Hostname検証ON）。本番既定は検証ONを維持 |
| HTTPS + Public CA | 推奨方針 | 検証ONで接続可。ただし証明書種別はUNKNOWN |
| HTTPS + Private CA | UNKNOWN | CA Bundle指定の仕組みは現Contractに存在しない。要設計判断 |
| HTTPS + Self-signed | 黙って許可しない | 検証ON時は検証失敗 → `market_recorder_upstream_unavailable`（Fail-closed）。`verify_tls=false` は恒久設定にしない |
| HTTP | 要正式設計承認 | HTTPを許可する場合は設計承認が必須（本Taskでは未承認） |
| Certificate / CA Bundle / Hostname要件 | UNKNOWN | Preflight §13にて不明項目として継続 |

---

## 6. Authentication Boundary

- Read API認証要否: **UNKNOWN**。現Contractは認証Headerを送信しないため、現行境界では認証なしで通信する設計。
- Control API認証とRead API認証を混同しない。両者の境界は未確認（**UNKNOWN**）。
- Authorization Header / API Key / mTLS: 現Contractは送信しない（**NOT REQUIRED**）。
  上流が必要と判明した場合は、Credentialを環境変数のみで管理し、Repository・`.env`・URL・Logへ配置・表示しない（要承認事項）。
- Source IP制限のみ: **CANDIDATE**（Google Cloud Backend IP `35.194.104.74` の許可を1D報告が推奨。未承認）。
- Credentialは作成・配置・表示しない。

---

## 7. Network / Firewall Preconditions

本TaskではFirewall・Networkを変更しない。前提を一覧化する。

| # | 項目 | 現状 |
|---|---|---|
| 1 | Google Cloud VMからのOutbound要件 | **UNKNOWN**（Backend `tradingai_prod1` のOutbound許可は未確認） |
| 2 | Contabo側Inbound要件 | **UNKNOWN**（許可Rule未設定・未確認） |
| 3 | 許可元IP | **CANDIDATE**: `35.194.104.74`（Google Cloud Backend外部IP。1D:210の推奨。未承認） |
| 4 | 宛先Port | **UNKNOWN** |
| 5 | Firewall Rule | **UNKNOWN**（設定しない） |
| 6 | Recorder API Listen Address | **UNKNOWN**（Preflight:90） |
| 7 | Reverse Proxy有無（Contabo側） | **UNKNOWN**（Preflight:90） |
| 8 | DNS名または固定IP | **UNKNOWN**（`recorder-contabo` はDNS解決不能） |
| 9 | IP変更時の運用 | **UNKNOWN**（要設計判断） |
| 10 | Network Timeout | CONFIRMED（既定 `5.0`秒・`> 0`）。運用上の上限は**UNKNOWN** |

補足: Google Cloud側nginxの `/api/` → `127.0.0.1:8001`（deploy/nginx-tradingai.conf:19-24）は
Frontend→BackendのSame-Origin経路であり、Contaboへの接続経路ではない。Contaboへの経路は未構築。

---

## 8. Temporary Configuration Template

Live Smoke Test時に一時Shell環境変数のみで使用するConfig形式。実値は設定しない。

```bash
export RECORDER_API_ENABLED=true
export RECORDER_API_BASE_URL=<APPROVED_BASE_URL>
export RECORDER_API_TIMEOUT=<APPROVED_TIMEOUT>
export RECORDER_API_VERIFY_TLS=<APPROVED_BOOLEAN>
```

各値の承認要件:

| Env | 既定 | 承認要件 |
|---|---|---|
| `RECORDER_API_ENABLED` | `false`（Fail-closed） | `true` への切替承認が必須 |
| `RECORDER_API_BASE_URL` | なし（enabled時必須） | 承認済みBase URL（Host / Port / Scheme確定）が必須 |
| `RECORDER_API_TIMEOUT` | `5.0`秒 | `> 0` の正値。既定5.0のままが推奨 |
| `RECORDER_API_VERIFY_TLS` | `true` | 原則 `true` のまま。`false` は恒久設定不可・一時的のみ |

※ 値はプレースホルダー。実値はRepository・`.env`・systemdへ永続保存しない。

---

## 9. Live Smoke Test Scope

本Taskでは実施しない。承認後に実行可能な範囲を定義する。

- 対象Endpoint（Read-onlyのみ）: `GET /health` `/status` `/storage` `/archives?page=1&page_size=1`。
- 禁止: POST/PUT/PATCH/DELETE・download・verify・mark-for-deletion等のControl操作。
- 期待結果:
  - 正常系: HTTP 200 + 検証済みEnvelope/DTO。
  - graceful-200: HTTP 200 + `ok:true` + unavailable状態（エラー扱いしない。503非依存）。
  - エラー系: Safe Error Codeへ正規化されること（Raw詳細非公開）。
- 実施条件: 本文書§12の承認ChecklistがすべてYESであること。

---

## 10. Fail-Closed Rollback Procedure

次工程で一時設定を使用した場合の復帰手順（Preflight §12に基づき確定）。

1. 一時環境変数のみを使用する。
2. `.env`・systemdへ永続保存しない。
3. Test終了後にShell Sessionを終了する（環境変数を破棄）。
4. `RECORDER_API_ENABLED` が未設定または `false` へ戻ったことを確認する
   （未設定時はProxy無効 = `market_recorder_proxy_disabled` 503）。
5. `RECORDER_API_BASE_URL` の実値が環境から削除されていることを確認する。
6. Backend Runtimeを恒久変更しない（Config・systemd・nginx・Firewall変更なし）。
7. CredentialやURLをLog・Report・Documentへ残さない。
8. Fail-Closed状態（Proxy無効・通信なし）を再確認する。

---

## 11. Unresolved Items

- Contabo Host / IP / Port / Scheme（HTTPSかHTTPか）
- TLS Certificate発行元・CN / SAN・有効期限・CA Bundle要件
- Read API認証の要否・方式（Authorization Header / API Key / mTLS / Source IP制限のみ）
- Control API認証とRead API認証の境界
- Contabo側の実Base Path・API Version・Reverse Proxy有無・Listen Address
- Google CloudからContaboへの到達経路（VPC / NAT / Firewall / Reverse Proxy / Tunnel）
- Contabo Firewallの許可元IP（`35.194.104.74` は候補・未承認）
- `RECORDER_API_TIMEOUT` の運用上の最大値
- Loopback / Private IP指定の運用方針（現Contractはenv専用のため限定的だが明示制限なし）

---

## 12. Explicit User Approval Checklist

Live Smoke Test実施前に対応が必要な承認項目。**本Taskではすべて未承認**。

| # | 承認項目 | 承認者 | 状態 |
|---|---|---|---|
| 1 | Contabo Recorder Read APIの接続先（Host / IP / Port / Scheme）確定 | ユーザー | 未承認 |
| 2 | TLS要件の確定（Certificate種別・`verify_tls` 方針） | ユーザー | 未承認 |
| 3 | Google Cloud egress（Backend `35.194.104.74`）のContabo Firewall許可 | ユーザー | 未承認 |
| 4 | Read API認証境界の確定（認証なし / 認証方式） | ユーザー | 未承認 |
| 5 | `RECORDER_API_BASE_URL` 実値の一時設定承認 | ユーザー | 未承認 |
| 6 | `RECORDER_API_ENABLED=true` への一時切替承認 | ユーザー | 未承認 |
| 7 | 認証必要時のCredential管理方法の承認 | ユーザー | 未承認 |
| 8 | 実環境へのRead-only接続テスト実施承認 | ユーザー | 未承認 |

---

## 13. Ready / Not Ready Decision

**NOT READY**

Live接続に必須となる接続入力（Host / Port / Scheme / TLS種別 / Firewall許可 / 認証境界）が
承認済み根拠なしで確定できず、すべてUNKNOWN / CANDIDATEのままのため。
本Taskの完了条件（UNKNOWNを正しく特定・分類・報告すること）は満たしている。

---

## 14. Next Task Handoff

1. ユーザーが本Checklist（§12）を承認し、接続先入力（Host / IP・Port・Scheme）を確定する。
2. 承認後、Live Smoke Test Taskで `RECORDER_API_BASE_URL` を一時環境変数設定し、
   `RECORDER_API_ENABLED=true` で `/health` `/status` `/storage` `/archives?page=1&page_size=1` をRead-only検証する。
3. graceful-200応答（unavailable状態）を正常系として扱う。
4. テスト後は即Fail-Closed（§10）へ戻す。
5. Timeout上限・Loopback/Private IP制限・認証境界は正式な設計判断を経てContractへ反映する。
