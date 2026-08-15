# RT-UI-1A REPORT — Runtime & Diagnostics UI集約

## 判定

PASS WITH FINDINGS

- 全 Success Criteria を満たした（Runtime集約・折りたたみ・通常画面維持・Build/Test PASS）。
- ただし2点の Findings あり：(1) 並列作業起因の既存テスト2件が既に失敗、(2) `npm run build` が追跡済みビルド成果物 `frontend/dist/index.html` を再生成。

## Target Environment

- SSH: `tradingai_prod1`
- Repository Root: `/home/joe4410joe/tradingai_prod_v1`
- Workspace（作業・テスト・buildの基準）: `/home/joe4410joe/tradingai_prod_v1/frontend`
- Git確認は Repository Root を明示して実行した。

## Git開始状態

`git -C /home/joe4410joe/tradingai_prod_v1 status --short` で、Frontendに並列作業の既存差分を確認。

- 並列作業の既存差分（対象外・保持対象）:
  - `frontend/src/App.jsx` (M) — MarketRecorderPage ルーティング追加
  - `frontend/src/components/AppNavigation.jsx` (M) — MARKET RECORDER ナビ追加
  - `frontend/src/main.jsx` (M) — market-recorder.css import 追加
  - `frontend/dist/index.html` (M) — 並列作業のビルド成果物
  - untracked: `frontend/src/features/market-recorder/`, `frontend/src/pages/MarketRecorderPage.jsx`, `frontend/src/styles/market-recorder.css`

## 既存差分の扱い

- restore / delete / stage / 書き換え / 今回の変更への混入は行っていない。
- 上記並列差分のソースファイル（App.jsx / AppNavigation.jsx / main.jsx / MarketRecorderPage 等）は一切編集していない。
- `frontend/dist/index.html` は本タスクの必須Validation `npm run build` が再生成した（後述のFindings参照）。

## Runtime情報の洗い出し結果（コード根拠）

監査対象（実在ファイル）:

| Component / 表示 | ファイル |
| --- | --- |
| 画面上部 Runtime Status | `src/components/header.jsx` / `src/components/StatusStrip.jsx` |
| Execution Monitoring（monitoring grid） | `src/pages/Dashboard.jsx`（インライン、`right-governance-column` 配下） |
| Runtime Health（Pipeline / Stages） | `src/components/runtime/RuntimeHealthPanel.jsx` / `PipelineStageList.jsx` / `RuntimeLoopList.jsx` |
| Execution Runtime | `src/components/ExecutionPanel.jsx` |
| System Summary / Account / Connections | `src/components/runtime/AccountRuntimeOverview.jsx` |
| Stage Inspector | `src/components/runtime/StageInspectorPanel.jsx` |
| Execution Timeline | `src/components/runtime/ExecutionTimelinePanel.jsx`（`monitor/LogsPanel.jsx` を内包） |
| Operation / Trade Settings | `src/components/BotControl.jsx` / `TradeSettings.jsx` / `RiskPanel.jsx` |
| ステータス色・カードCSS | `src/styles/dashboard.css` |

- 既存 state/props: `telemetryState`（governance/runtime/market）、`usePolling` による `fetchBotStatus`、`useDashboardMarketContext`（tradeSettings）、Dashboard local state（executionEnabled / selectedStageId / manualBotStatusSnapshot）。
- 既存の折りたたみ実装は Dashboard に無し（新規に `RuntimeDiagnosticsDisclosure` を追加）。

## 通常画面へ残した情報（「何を残したか」）

- Header StatusStrip（上部要約）: BOT / BROWSER WS / RUNTIME ENGINE / LATENCY / EXEC / PIPELINE / STAGES / SESSION / VERSION。要約表示としてそのまま維持（候補 RUNTIME/EXECUTION/PIPELINE/WS を含む）。
- Operation: BotControl — Loop ON/OFF, Loop State, Auto Trade ON/OFF, Emergency Stop, Emergency Lock, 通常に戻す, ユーザー操作ボタン一式。
- Trade Settings: TradeSettings + RiskPanel（Exchange / Symbol / Risk / Leverage / Timeframe / Position Size / TP / SL / Trailing / Max Drawdown）。
- Account / Trading Information: `AccountRuntimeOverview`（summary variant）— Paper Balance / Equity / Available / Position / PnL / Source、Real Balance / Equity / Available / Position、PAPER MODE コンテキスト。
- Last Order: `execution-activity`（LAST ORDER / LAST EXECUTION CHECK + 時刻）を中央カラム下部に維持。
- レイアウト: 3カラム → 2カラム（left + center）。右カラムは Runtime専用だったため廃止。

## Runtimeへ移動した情報

`RuntimeDiagnosticsDisclosure`（Dashboard最下部・初期折りたたみ）へ集約:

- Execution Monitoring / System Summary: RUNTIME HEALTH / BOT STATE / TRADING RUNTIME / PIPELINE / EXECUTION AUTHORITY / TRADING ACTION / DECISION / EXECUTION ENGINE / BROWSER WS / EXCHANGE WS / ACTION REASON / BLOCKING REASON / LATENCY（monitoring grid を丸ごと移動）
- Runtime Health: `RuntimeHealthPanel`（PipelineStageList + RuntimeLoopList）
- Execution Runtime: `ExecutionPanel`（STATUS / PHASE / WS / LATENCY）
- Connections + Execution Diagnostics: `AccountRuntimeOverview`（diagnostics variant）— Trading Mode & Execution カード（Selected Mode / Execution Mode / Allow Live / Trade Mode / Dry Run / Real Orders / Real Order Allowed / Reason）＋ Connection & Auth カード（Exchange / Exchange Connection / API Key / Permission / Account Type / Exchange Auth / accountSource / balanceSource / positionSource / Last Sync / Auth Reason / Balance Reason / Position Reason）
- Stage Inspector: `StageInspectorPanel`（Current Stage / Status / Backend File / Function / Duration / Input / Output / Exception / Reason / Related Files）
- Execution Timeline: `ExecutionTimelinePanel`（Time / Source / State / Reason / 空状態）
- 新規Mock追加なし（実在項目のみ移動）。

## 変更ファイル

- 新規: `frontend/src/components/runtime/RuntimeDiagnosticsDisclosure.jsx`
- 新規: `frontend/src/components/runtime/RuntimeDiagnosticsDisclosure.test.js`
- 変更: `frontend/src/components/runtime/AccountRuntimeOverview.jsx`（`variant="summary" | "diagnostics"` を追加）
- 変更: `frontend/src/pages/Dashboard.jsx`（Runtime表示を最下部のDisclosureへ移動、右カラム廃止）
- 変更: `frontend/src/styles/dashboard.css`（2カラム化・スクロールコンテナ化・Disclosure CSS・既存セレクタ拡張）
- 変更: `frontend/e2e/runtime-health.spec.js`（Disclosure展開後に監視値を検証するようテスト更新）

## Component構成

```
Dashboard
├─ Header (StatusStrip)          … 上部要約（維持）
├─ .dashboard (スクロールコンテナ)
│  ├─ .dashboard-layout (2カラム grid, height:100%)
│  │  ├─ left-column   … BotControl / TradeSettings / RiskPanel
│  │  └─ center-column … AccountRuntimeOverview(summary) + Last Order
│  └─ RuntimeDiagnosticsDisclosure（最下部・折りたたみ）
│     ├─ button (▶/▼ RUNTIME & DIAGNOSTICS)
│     └─ .runtime-diagnostics-panel（展開時のみ表示）
│        ├─ execution-monitoring-card（System Summary）
│        ├─ RuntimeHealthPanel
│        ├─ ExecutionPanel
│        ├─ AccountRuntimeOverview(diagnostics)
│        ├─ StageInspectorPanel
│        └─ ExecutionTimelinePanel
```

## State管理

- 開閉状態は `RuntimeDiagnosticsDisclosure` 内の local `useState(false)` のみ。Dashboardの他stateは複製せず再利用。
- Backend送信 / localStorage / URL query / Global state の追加なし。

## Accessibility対応

- `<button>` 使用、`aria-expanded`、`aria-controls`（panel id と一致）。
- Keyboard操作可能（button標準）、`:focus-visible` でフォーカス表示。
- 折りたたみ状態は ▶/▼ に依存せず、テキストラベル「COLLAPSED / EXPANDED」＋ aria-expanded で判別可能。
- Screen Reader向けには button のテキスト「RUNTIME & DIAGNOSTICS」がアクセシブルネームとなり、`aria-hidden="true"` で装飾要素を除外。
- 展開時 `hidden` 属性で内容を accessibility tree から除外。

## Backend変更なし確認

- Backend全ファイルの変更なし（git status で backend 差分は並列作業のみで、本タスクでは編集していない）。

## API request追加なし確認

- 新規 fetch / axios / WebSocket / polling / API client の追加なし。既存 `usePolling(fetchBotStatus)` と WebSocket Runtime のみ再利用。

## Test結果

| 対象 | 結果 |
| --- | --- |
| `node --test src/components/runtime/RuntimeDiagnosticsDisclosure.test.js` | PASS (4/4) |
| `node --test`（runtimeHealth / runtimeDisplay / DashboardMarketContext） | PASS (14/14) |
| `npm test`（full） | 643/645 PASS / 2 FAIL（下記Findings・並列作業起因） |
| `npx playwright test`（e2e 8件） | PASS (8/8) |
| `npm run build` | PASS（chunk size 警告のみ） |
| `npx eslint`（変更ファイル） | PASS |
| `git diff --check` | PASS |

## Build結果

- `cd /home/joe4410joe/tradingai_prod_v1/frontend && npm run build` → PASS（695 modules, 1.4s）

## git diff --check

- `git -C /home/joe4410joe/tradingai_prod_v1 diff --check` → PASS

## Git終了状態

`git -C /home/joe4410joe/tradingai_prod_v1 status --short`（本タスク関与分のみ抜粋）:

- M: `frontend/src/pages/Dashboard.jsx`, `frontend/src/components/runtime/AccountRuntimeOverview.jsx`, `frontend/src/styles/dashboard.css`, `frontend/e2e/runtime-health.spec.js`
- ??（新規）: `frontend/src/components/runtime/RuntimeDiagnosticsDisclosure.jsx`, `frontend/src/components/runtime/RuntimeDiagnosticsDisclosure.test.js`
- 並列作業差分（App.jsx / AppNavigation.jsx / main.jsx / dist/index.html / market-recorder 群）は保持されたまま。
- commit / push / deploy / branch変更 / stage なし。

## Findings

1. **並列作業起因の既存テスト失敗（本タスク非起因）**: `src/App.test.js` と `src/components/AppNavigation.test.js` が失敗。並列作業が `App.jsx` に `MarketRecorderPage` import を追加したが `App.test.js` の stub 対象に無く、また `AppNavigation.test.js` がナビ項目数4を期待する一方で並列作業が5個目（MARKET RECORDER）を追加したため。本タスクの変更では App.jsx / AppNavigation.jsx に触れていない。
2. **`frontend/dist/index.html`（追跡済みビルド成果物）の再生成**: 必須Validation `npm run build` が bundle hash 参照を更新。並列作業のソース差分は全て保持されており、成果物は現行ソースの累積ビルドを反映。並列セッション終了時に最終ビルドで統一することを推奨。
3. **e2eテスト更新（宣言スコープ外だが必須）**: `frontend/e2e/runtime-health.spec.js` を、Disclosureを展開してから監視値を検証する形に最小更新。これは「初期状態は折りたたみ」という本タスクの仕様の直接の帰結。
4. **Realカードの接続系メトリクス移動**: 通常画面のRealカードから Exchange Auth / Last Sync / accountSource / balanceSource / positionSource を除外し、Runtime内の Connection & Auth カードへ統合（重複表示回避）。通常画面のRealカードは Balance / Equity / Available / Position のみ表示。

## 次工程

- RT-UI-1B（Backend・API・WebSocket・Runtime contract の接続整理／統合）を並列作業が落ち着いた後に実施。
- 並列作業完了後の再ビルドで `frontend/dist/index.html` を統一。
- 並列作業の MarketRecorder 差分収束後に `App.test.js` / `AppNavigation.test.js` を更新。
