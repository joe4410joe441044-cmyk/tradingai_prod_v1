# TR-RECORDER-UI-1D REPORT

## Result

**PASS WITH FINDINGS**

- Contract照合（Status / Storage / Archives Page / Archive Entry）はField名・型・Nullability・Envelope・Error・Pagingすべて一致。Frontend修正はBase URLのhttp/https明示制限のみ。
- Offline Contract Fixture Test（Contabo Sample相当10件）を新規作成し15 Test PASS。
- Live Read-only Testは未実施。`recorder-contabo`はDNS解決不能（`gaierror`）、SSH alias・Contabo接続先IP/Portが本環境に存在せず、承認済み接続経路がないため。原因分類はNETWORK / CONFIGURATION。
- 危険な環境変更なし。Contabo側Repository無変更。commit・push・stage・branch変更なし。

## Target Environment

- Repository: `/home/joe4410joe/tradingai_prod_v1`
- Host: `tradingai_prod1`（Google Cloud / asia-northeast1 / internal 10.146.0.7 / external 35.194.104.74）
- Branch: `main`
- Contabo: `recorder-contabo` / `/opt/market-recorder` — NOT touched（対象外）

## Git Start State

- Branch: `main`
- HEAD: `d57de0439576c1134a67ce6055f65fc4a1c084e0`
- origin/main: `d57de0439576c1134a67ce6055f65fc4a1c084e0`
- Divergence: 0 ahead / 0 behind
- 既存dirty / untracked（作業開始前から存在）: `backend/ai_advisor/runner_process_detection.py`, `backend/utils/log_buffer.py`, `frontend/dist/index.html`, `frontend/src/App.jsx`, `frontend/src/components/AppNavigation.jsx`, `frontend/src/main.jsx`, docs削除多数, `tests/*` 2件, docs配下untracked多数, market-recorder全体untracked

## Git End State

- Branch: `main`（不変）
- Commit: No / Push: No / Staged: No / Deploy: No
- Out-of-scope files modified: No（新規の対象外変更なし。`frontend/dist/index.html`は作業開始前からdirtyであり、Buildにより再生成されたBuild artifact）

## Contract照合結果

正本 `docs/recorder_api/openapi/market-recorder-api-v0.1.0.yaml` は本Repository・本セッションから参照不可（Contabo側所管、host解決不能）。Task入力内のContract（Field一覧）を正式入力として照合した。

### Status（14 Field）— 一致
`status / connection_state / pid / uptime_seconds / subscribed_streams / messages_received / bytes_received / reconnect_count / sequence_anomaly_count / active_files / last_message_at / last_error / process_started_at / observed_at`

`normalizeStatusDomain` が全Fieldを参照。Number（非負・有限・整数）、ISO Timestamp、String / null、`active_files` Array。status enumは `RUNNING/running/RECORDING/recording → RUNNING`, `STOPPED/stopped → STOPPED`, unknown → `UNAVAILABLE`。

### Storage（10 Field）— 一致
`filesystem / total_bytes / used_bytes / free_bytes / usage_percent / archive_bytes / active_bytes / manifest_bytes / quarantine_count / observed_at`

`normalizeStorageDomain` が全Fieldを参照。Bytes非負・有限、`usage_percent`は0以上Number、`quarantine_count`は非負整数。

### Archives Page（5 Field）— 一致
`entries / page / page_size / total_count / total_pages`
`normalizeArchivesDomain` が全Fieldを参照。`entries`必須Array、Paging不正値は安全にフォールバック。

### Archive Entry（13 Field）— 一致
`id / stream / symbol / period / start_time / end_time / record_count / compressed_bytes / uncompressed_bytes / verification_status / manifest_status / downloadable / deletion_eligible`
`normalizeArchiveEntryDomain` が全Fieldを参照。Path文字列拒否、null entry除外、fallback id生成、`verification_status` unknownは `completed` へ安全フォールバック。

### Common Response Envelope — 一致
`{ok: true, data: ..., error: ...}` を要求。`ok !== true` → `RECORDER_SERVER`（retryable: false, source: server）。`data`欠落 → `RECORDER_PARSE`。`error`はSafe Error Contract（code / message / retryable / source）のみ公開。

### Error Response — 一致
Error surfaceはRaw Stack / Traceback / 内部Pathを公開しない（Fixture Testで検証）。

### Query Parameter / Paging / Sort / Filter — 一致
`page`（1+）, `page_size`（1–200）, `stream`, `symbol`, `from`, `to`, `verification_status`（recording/completed/failed/verified）, `downloadable`（boolean）, `sort`（start_time/end_time/record_count/compressed_bytes/verification_status）, `order`（asc/desc）。不正値は送信しない。

### 不一致・要確認（Finding）
- **`health` DTO / `getHealth()` がFrontendに不在**。Contaboは `GET /api/recorder/health` を提供するが、Task Step 1のDTO一覧にHealthは含まれておらず、`recorderClient` に `getHealth()` は存在しない。Live Test時に `/health` を含める場合は最小の `getHealth()` + Health DTO追加が必要。
- **`verification_status=verified` のクエリ許容とDTO enumの非対称**。QueryBuilderは `verified` を許容するが、`ARCHIVE_DTO_STATUS` は `recording/completed/failed` のみ。Backendが `verified` を返した場合 `completed` へ安全フォールバック。Enum値はBackend Contract推測禁止のため変更せず、正式Contract確認を推奨。

## Offline Fixture Test

新規追加：`frontend/src/features/market-recorder/services/recorderContractFixtures.js`（10件固定Fixture・deep-frozen）と `recorderContractFixtures.test.js`（15 Test）。

Fixture: `health.success / status.running / status.unavailable / storage.success / archives.empty / archives.page1 / error.invalid_query / error.runtime_unavailable / error.storage_unavailable / error.archive_inventory_unavailable`

検証項目:
- DTO Validator通過（envelope + 個別Validator）
- Domain Model変換（normalize）
- View Model変換（adapter）
- Raw path非表示（`active_files` basename抽出、`currentFile`/`file` に `/` を含まない）
- Invalid sample安全拒否（error系4件は `RECORDER_SERVER` でthrow、`source: server`、Raw stack/traceback/path非公開）
- Input非変更（deep-frozen + snapshot一致）
- Deterministic（2回実行で同結果）

## Base URL Contract（Step 3）

- Env var: `VITE_RECORDER_API_BASE_URL`
- 未設定時 fail-closed: `RECORDER_NETWORK` / `configuration_error`（retryable: false, source: client）
- Credential埋め込み禁止: `url.username` / `url.password` → null
- Query / Fragment禁止: `url.search` / `url.hash` → null
- Trailing slash正規化: 末尾 `/` 除去
- **`http` / `https` の扱いを今回明示化**: protocolが `http:` / `https:` 以外（`ftp:` 等）→ null（fail-closed）。これに伴いClient Testを6件追加。
- Production実値は保存しない（`.env.production` に未設定のまま、実値は一時Shell環境変数のみ許可）
- Log / PageへURLを出さない
- Path prefix（`/proxy` 等）は保持され、fetch URLに反映（テストで検証）

## Connectivity Investigation（Step 4）

実施内容（読み取り専用・短timeout・指定候補のみ）:
- `recorder-contabo` のDNS解決: **失敗**（`getent` 失敗, `socket.gethostbyname` は `gaierror`）
- `~/.ssh/config` 存在せず。SSH alias `recorder-contabo` は本環境に未設定
- Repository / docs / known_hosts にContaboのIP・Port・Host名の記載なし
- 本host（Google Cloud）にMarket Recorderプロセス無し（`ps` 確認）、Recorder APIのListen無し
- 本hostのListen: 22 / 80（nginx） / 8001（uvicorn backend.main） / 4174（vite preview）等。Recorder APIに該当するものなし
- Port Scan / 無制限Retry / 指定外探索: **実施せず**

結論: 本環境からContaboへ到達する承認済み接続経路が存在しない。Recorder APIの候補Host / IP / Portが明示されていないため、接続試行自体が不可能。

## Live Read-only Test（Step 5）

**NOT PERFORMED**

理由: 正式な接続先が不明かつ到達不能（`recorder-contabo` DNS解決不能、接続先IP/Port未指定）。Live Testは「安全な接続先が明示され、追加環境変更なしで到達可能な場合のみ」というTask条件を満たさないため、無理に実施しない。

許可Endpoint（実施条件を満たした場合の対象）: `GET /api/recorder/health`, `/status`, `/storage`, `/archives?page=1&page_size=1`
禁止Endpoint: POST/DELETE系・download・verify・mark-for-deletion は一律対象外。

## Browser Integration Feasibility（Step 6）

| 案 | Security | Deploy複雑度 | Auth | CORS | TLS | Auditability | Failure Isolation | 推奨度 |
|---|---|---|---|---|---|---|---|---|
| A. Browser → Contabo直接 | 低（Public expose必須、認証・認可管理が分散） | 中（Contabo側でPublic公開・TLS・CORS設定が必要） | Contabo側で要実装 | Contabo側で要設定 | Contabo側で要証明書 | 低（統制記録が分離） | 低 | 非推奨 |
| B. TradingAI Backend Proxy経由 | 高（外側は既存nginx/backendに集約、内側のみContaboへ） | 低（既存nginx `/api/` proxyパターン流用） | Backend側で一元管理可 | 不要（同Origin） | 既存TLS/nginxを利用 | 高（単一経路で監査可） | 高 | **推奨** |
| C. Private Tunnel / Network | 高（Public exposure無し） | 高（VPN/Tunnel・VPC peering相当の構築・運用） | Tunnel層で要検討 | 不要 | Tunnel内で要検討 | 中 | 高 | 中（長期的選択肢） |

本TaskではProxy・Tunnelは実装しない。推奨は**案B（TradingAI Backend Proxy）**。既にnginxが `/api/` → `127.0.0.1:8001` をproxyしており、backendにrecorder read-only proxy経路を追加する方式が最も統制された接続となる。

## UI Verification（Step 7）

`MarketRecorderPage.jsx` を静的確認。既存Designは無変更。
- Status表示（badge + Recording Time + Current File）: Success系Fixture（status.running/unavailable）でVM確認済
- Storage表示（Total/Used/Free/Recorder Size）: storage.successでVM確認済
- Archive一覧（Date/File/Size/Status/Action）: archives.page1でVM確認済
- Loading / Unavailable / Error / Empty: Pageが各DataStateに対応するPlaceholderをレンダリング
- Control Button（START/STOP）: disabled
- Download / Delete Button: disabled
- 動的Paging UI: 本Taskの必須範囲外（従来通り固定 `page=1, page_size=200`）

Reactランタイムレンダリングの自動テストは `node --test` 基盤では未実施（jsdom / @testing-library 未導入）。これは既存Findingと同一。

## Failure Classification（Step 8）

**NETWORK**（`recorder-contabo` DNS解決不能 — 到達不能）+ **CONFIGURATION**（SSH alias・接続先IP/Port・接続経路が本環境に未設定）。

同一の失敗を根拠なく繰り返すことはしない（本Taskでは接続試行1回で判定し、Live Testは条件不成立のため不実施）。

## Tests

```bash
cd frontend && node --test src/features/market-recorder/
```
- **PASS** — 270/270（基準249 + Fixture 15 + Base URL Client 6）
  - recorderContractFixtures.test.js: 15/15（新規）
  - recorderClient.test.js: 29/29（23→29）
  - 他既存: recorderDataState 15, recorderError 13, recorderFormatters 36, recorderAdapters 30, useRecorderStatus 23, useRecorderStorage 18, useRecorderArchives 19, recorderApiDtos 48, recorderQueryBuilder 24

```bash
cd frontend && npm run build
```
- **PASS** — vite build成功（4.75s）。chunk size警告は従来と同一（既存の非ブロッキング警告）

```bash
cd /home/joe4410joe/tradingai_prod_v1 && git diff --check
```
- **PASS** — whitespace error無し

```bash
grep -RInE 'fetch\s*\(|axios|XMLHttpRequest|new WebSocket|EventSource' \
  frontend/src/features/market-recorder frontend/src/pages/MarketRecorderPage.jsx
```
- Production code match: `recorderClient.js:153` の `fetch(` のみ（1件）
- `method: "GET"`（recorderClient.js:154）のみ。POST/PUT/PATCH/DELETE/WebSocket/EventSource/axios はProductionに無し（Test内のStatic Assertion matchesのみ）
- Polling無し / Retry Loop無し / 単一fetch

## Build

PASS（`npm run build`）。`frontend/dist/index.html` はBuild artifactとして再生成（作業開始前からdirty）。dist/assetsは新しいhash名で生成されるが、git status上はdist/index.htmlのみ変更表示（assetsはgitignore対象）。

## Git Safety

- Commit: No / Push: No / Deploy: No
- Stage: No / Branch変更: No
- Out-of-scope Files Modified: No（新規対象外変更なし）
- 終了時 `git status --short` は開始時と同等（新規はmarket-recorder内のみ）

## Changed Files

### New
- `frontend/src/features/market-recorder/services/recorderContractFixtures.js` — Contabo Sample相当10件の固定Fixture（deep-frozen）
- `frontend/src/features/market-recorder/services/recorderContractFixtures.test.js` — 15 Test

### Modified
- `frontend/src/features/market-recorder/services/recorderClient.js` — `getBaseUrl` にprotocol `http:/https:` 明示制限を追加（fail-closed強化）
- `frontend/src/features/market-recorder/services/recorderClient.test.js` — Base URL ContractのRuntime Testを6件追加（query/fragment/credential/ftp拒否、trailing slash正規化、path prefix保持）

### Build Artifact（作業開始前からdirty）
- `frontend/dist/index.html` — Buildにより再生成

## Findings

1. **Live Read-only Test 未実施**: `recorder-contabo` が本環境でDNS解決不能（`gaierror`）。SSH alias / 接続先IP / Portが未設定。接続経路の設定（VPC/Firewall/Nginx/SSH Tunnel等）はCritical Boundaryで禁止のため、承認対象として報告する。
2. **`getHealth()` 不在**: Contaboは `GET /api/recorder/health` を提供するがFrontend Clientには無い。Task Step 1のDTO一覧外のため追加せず。Live Testで `/health` を含める場合は次Taskで最小追加が必要。
3. **`verification_status=verified` とDTO enum非対称**: QueryBuilderは `verified` filterを許容、DTO enumは `recording/completed/failed`。Backendが `verified` を返した場合は `completed` へ安全フォールバック。正式Contract確認を推奨。
4. **ReactランタイムUIテスト未導入**: `node --test` 基盤ではReact hook/componentのランタイム検証なし（jsdom / @testing-library 未導入）。UIは静的確認のみ。
5. **動的Paging UI未実装**: Archivesは固定 `page=1, page_size=200`。本Taskの必須範囲外。
6. **`VITE_RECORDER_API_BASE_URL` 未設定**: `.env.production` に実値なし（fail-closedにより安全）。実接続時は承認後の一時設定・またはProxy経路整備が必要。

## Required Approval

接続経路構築の承認（推奨: 案B TradingAI Backend Proxy）:
- Backend / Nginxに `GET /api/recorder/*` のread-only reverse proxy経路を追加する承認
- Contabo側のAllow-list（TradingAI backend IP `35.194.104.74`）設定の承認
- `.env.production` への接続値設定方法（Proxy利用時は same-origin `/api/recorder/`）の承認

Contabo側へ変更（Recorder API・systemd・Firewall・公開設定）は発生しない。

## Next Recommended Task

**TR-RECORDER-UI-1E** — TradingAI Backend Proxy（案B）による `GET /api/recorder/health|status|storage|archives` のRead-only接続経路構築と承認後のLive Read-only Test。完了後に動的Paging UI（Archives）を実装する。
