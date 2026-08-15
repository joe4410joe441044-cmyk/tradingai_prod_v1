# TradingAI Market Recorder 進捗・方針仕様書

作成日: 2026-08-09

## 1. 目的

本仕様書は、Recorderプロジェクトの成果・今後の方針を固定し、今後の開発指針とする。

## 2. プロジェクトプロファイル

-   個人利用のみ
-   TradingAI専用
-   外部ユーザーなし
-   検証・学習・バックテスト用途
-   完成を最優先
-   Enterprise専用インフラは必要になるまで導入しない

## 3. 完了済み

### Recorder Runtime

-   Coordinator
-   Session管理
-   JSONL Writer
-   Manifest
-   Storage Repository
-   State Machine

### Event Pipeline

-   Validator
-   Normalizer
-   Binance Adapter

### Read API

-   Health
-   Status
-   Storage
-   Archives

### TradingAI連携

-   Backend Proxy
-   DTO
-   Hooks
-   UI
-   Live Read API

### UI

-   Operation
-   Status
-   Storage
-   Archives
-   Runtime & Diagnostics

### Security

-   HTTPS
-   Let's Encrypt
-   Nginx
-   UFW
-   TradingAI Source IP Allowlist
-   Redis Replay
-   Redis Rate Limit
-   Audit
-   Idempotency
-   Lock

### Redis

-   Replay Store
-   RateLimit Store
-   AOF

### Control Runtime

-   Start/Stop
-   Dry Run
-   Gateway
-   Auth Middleware
-   Execution
-   Error Mapping

## 4. 現在停止中の理由

Control APIの実装ではなく、Enterprise向けmTLS証明書発行待ちが停止理由。

## 5. 正式方針

Phase1ではmTLSを採用しない。

採用: - HTTPS - Nginx - UFW - TradingAI IP Allowlist - Redis Replay -
Redis Rate Limit - Audit

mTLSはPhase2。

## 6. 残作業

1.  個人利用向けControl認証へ簡素化
2.  TradingAI START/STOP有効化
3.  E2Eテスト
4.  Recorder完成

## 7. OpenCode共通前提

    Individual developer.
    Private internal system.
    Recorder is used only by TradingAI.
    No public users.
    No mandatory mTLS.
    Reuse HTTPS/UFW/Nginx/IP Allowlist/Redis/Audit.
    Prefer the simplest implementation.

## 8. 完成度

-   Runtime: 完了
-   Read API: 完了
-   TradingAI Proxy/UI: 完了
-   Redis: 完了
-   Security: 完了
-   Control Runtime: 完了
-   Production Activation: 方針変更後に実施

## 9. 最終目標

TradingAIからRecorderを安全に開始・停止し、安定して市場データを記録し、検証・学習に利用できる状態を完成とする。
