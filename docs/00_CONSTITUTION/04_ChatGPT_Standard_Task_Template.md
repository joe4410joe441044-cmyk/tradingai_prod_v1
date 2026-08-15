# ChatGPT Standard Task Template

Version: 0.1\
Status: Foundation Draft


本TaskはTradingAI Initialization完了後に実行されることを前提とする。
Constitution Reviewは完了済みとして扱う。

------------------------------------------------------------------------

# Purpose

このテンプレートは、TradingAIプロジェクトにおいてChatGPTがOpenCode向けの作業指示書を作成する際の標準フォーマットである。

------------------------------------------------------------------------

# Standard Task Header

本Taskは **TradingAI Constitution** を最優先とする。

## 作業開始前に必ず参照すること

1.  `docs/00_CONSTITUTION/README.md`
2.  `docs/00_CONSTITUTION/00_TradingAI_Constitution.md`
3.  Taskに関連するADR（Design Decision Record）
4.  Taskに関連するGlossary
5.  `docs/opencode/TradingAI_Platform_OpenCode_Parallel_Development_Standard_v2.0.md`

------------------------------------------------------------------------

# Task Information

## Task ID

（例）MI-1A-001

## Task Title

作業名

## Background

背景

## Objective

目的

## Scope

作業範囲

## Out of Scope

対象外

## Constraints

-   commit禁止
-   push禁止
-   deploy禁止
-   branch変更禁止（指示がある場合を除く）
-   対象外ファイルを変更しない

## Success Criteria

成功条件を具体的に記載する。

------------------------------------------------------------------------

# Final Report

OpenCodeは最終成果物を **Markdown（.md）** として提出すること。

最終報告には最低限以下を含める。

-   PASS / FAIL 判定
-   Git Status
-   変更ファイル一覧
-   実装概要
-   テスト結果
-   残課題（あれば）

------------------------------------------------------------------------

# Review

本TaskはOpenCodeの実装完了では終了しない。

必ずChatGPTレビュー・品質判定を経て完了とする。
