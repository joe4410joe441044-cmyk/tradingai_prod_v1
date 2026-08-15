# TradingAI Platform OpenCode Parallel Development Standard v1.0

## 目的

本仕様は、TradingAI
PlatformにおいてOpenCodeを利用した並列開発を安全かつ効率的に行うための標準運用ルールを定義する。

## Rule 1

1セッション＝1担当領域。担当変更はセッション終了後のみ。

## Rule 2

開始時に担当範囲・変更可能範囲・変更禁止範囲を宣言する。

## Rule 3

Git操作・Commit・Branch変更・全体検索置換・担当外編集は禁止。

## Rule 4

編集対象ファイルを固定する。

## Rule 5

settings.py、config.py、requirements.txt、package.json等の共通ファイルは専任担当のみ編集。

## Rule 6

終了時に `git status --short` を確認する。

## Rule 7

1セッション＝1テーマで進める。

## Rule 8

統合担当のみが最終確認を行う。

## Rule 9

OpenCodeへ担当を明示する。

例:

    あなたはDashboard専任です。
    担当外は禁止です。

## Rule 10

全体リファクタリング、全体rename、formatter全体実行は禁止。

## Rule 11

終了時は変更ファイル一覧・変更概要・影響範囲を出力する。

## Rule 12

ChatGPTレビューを必須とする。

## Rule 13

OpenCodeには他セッションの存在を伝えず、自担当だけを依頼する。

## 推奨運用

-   VS Code拡張版OpenCodeを基本利用
-   同一ファイルの同時編集は禁止
-   担当領域を固定
-   作業終了時はGit状態確認
-   ChatGPTレビュー実施

## Version

-   Document: TradingAI Platform OpenCode Parallel Development Standard
-   Version: 1.0
-   Status: Draft
