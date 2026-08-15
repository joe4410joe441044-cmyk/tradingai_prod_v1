# TradingAI Platform OpenCode Parallel Development Standard v2.0

**Status:** Official\
**Version:** 2.0

## 1. Purpose

本仕様は、TradingAI
PlatformにおいてOpenCodeを利用した並列開発を、安全・高品質・高効率で運用するための標準ルールを定義する。

## 2. Development Architecture

### ChatGPT

-   設計
-   アーキテクチャ
-   タスク分割
-   優先順位決定
-   コードレビュー
-   次工程設計

### OpenCode

-   実装
-   調査
-   テスト
-   実装結果報告

## 3. Parallel Session Rules

-   1セッション＝1担当領域
-   同一ファイルの同時編集禁止
-   担当変更はセッション終了後のみ
-   共通ファイルは専任担当のみ編集

## 4. Task Management

すべての作業はTask ID単位で管理する。

例 - RP-A4 - RP-A5 - ADV-2A - MM-5A

## 5. Prompt Standard

指示書には必ず以下を含める。

-   背景
-   目的
-   対象
-   実装または調査内容
-   禁止事項
-   成功条件
-   報告形式

## 6. Report Standard

OpenCodeは途中経過・思考過程・詳細ログを出力しない。

最終報告のみをMarkdown形式で出力する。

``` text
# 判定

# 実装概要

# Findings

# テスト結果

# Git状態

# 次工程への引継ぎ事項
```

## 7. Git Rules

禁止事項

-   Commit
-   Push
-   Branch変更
-   全体Rename
-   全体Formatter
-   担当外編集

終了時は `git status --short` を確認する。

## 8. Review Workflow

ChatGPT ↓ Task作成 ↓ OpenCode ↓ 最終報告 ↓ ChatGPTレビュー ↓ 次Task

## 9. Multi Session Operation

例

Session1 - AI Advisor

Session2 - Replay

または

Session1 - Market Intelligence

Session2 - Money Management

## 10. Integration Rules

統合担当のみが最終統合を行う。

## 11. Future Expansion

2セッション以上の並列開発へ対応する。

## 12. Operating Principles

-   ChatGPTは設計・レビュー担当
-   OpenCodeは実装担当
-   Task IDで管理
-   最終報告のみレビュー対象
-   ChatGPTレビュー必須

## Version

Document: TradingAI Platform OpenCode Parallel Development Standard

Version: 2.0

Status: Official
