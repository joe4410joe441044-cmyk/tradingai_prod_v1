# TradingAI Initialization

Version : 1.2
Status  : Active

---

ChatGPTはローカルリポジトリを参照できません。

OpenCode・Codex等、
リポジトリアクセス可能な実行環境では、
Constitution Reviewを実施してください。

ChatGPTでは、
Constitutionの内容がチャット内または
プロジェクト機能等で利用可能な場合は、
それを最優先として扱います。


# Purpose

この文書は、TradingAIプロジェクト専用チャットを開始する際の標準初期化プロンプトである。

TradingAIでは、本プロンプトをチャット冒頭で使用し、設計思想・レビュー方針・作業指示書・設計ガバナンスの一貫性を維持する。

---

# Initialization Prompt

【TradingAI Initialization】

このチャットはTradingAIプロジェクト専用です。

TradingAIでは、

`docs/00_CONSTITUTION/`

フォルダ全体をTradingAIプロジェクトの最高位設計文書群（Authoritative Design Documents）として扱います。

設計・レビュー・仕様提案・作業指示書を作成する際は、まず `docs/00_CONSTITUTION/` 全体を設計判断の前提として扱ってください。

アクセス可能な実行環境（OpenCode・Codex等）では、Task開始前にConstitutionフォルダ全体を一読し、その内容を理解したうえでTaskを開始してください。

Task開始前には、以下のPre-Task Constitution Reviewを実施してください。

### Pre-Task Constitution Review

Step 1

`docs/00_CONSTITUTION/`

フォルダ全体を確認してください。

Step 2

Constitutionフォルダ全体について5〜10行で要約してください。

最低限、以下を含めてください。

- TradingAIの目的
- Document Hierarchy
- Runtimeの位置付け（記載がある場合）
- Replay / Analyticsの位置付け（記載がある場合）
- 今回のTaskで特に重要だと思う設計思想

Step 3

Constitutionを踏まえ、今回のTaskをどのような設計思想で進めるかを3〜5行で説明してください。

Step 4

その後、Taskを開始してください。

---

設計判断はREADMEで定義されたDocument Hierarchyに従ってください。

優先順位は以下の通りです。

1. Constitution
2. ADR (Architecture Decision Records)
3. Master Specification
4. Feature Specification
5. Task Instruction
6. Implementation
7. Runtime Result

Taskに直接関係しない内容も設計思想として保持し、Taskに関連する内容を優先して設計・レビュー・作業指示書へ反映してください。

Constitution・ADR・仕様書・現在のTask内容の間に矛盾や設計差異が見つかった場合は、独自判断で進めず、必ず設計差異として報告してください。

TradingAIの作業指示書を作成する場合は、

`docs/00_CONSTITUTION/04_ChatGPT_Standard_Task_Template.md`

を基準として作成してください。

OpenCodeへ作業を依頼する場合は、

`docs/opencode/TradingAI_Platform_OpenCode_Parallel_Development_Standard_v2.0.md`

の運用ルールを前提として作業指示書を作成してください。

なお、ChatGPTはローカルリポジトリを自動的に参照することはできません。

`docs/00_CONSTITUTION/` の内容がチャット内で共有されている場合、またはプロジェクト機能等により参照可能な場合は、その内容を設計判断の最優先として扱ってください。

参照できない場合は、その旨を最初に報告し、そのチャット内で共有されている情報を基に作業を進めてください。

本チャットではTradingAI Constitutionを最優先思想として扱い、一貫した設計・レビュー・作業指示書を作成してください。

Constitution・Glossary・ADR・Principles・README・Template等の更新が必要と判断した場合は、変更提案として報告してください。

本InitializationはTradingAIの標準運用ルールとして扱い、Task開始時の共通前提としてください。

---

# Notes

本ファイルはTradingAI専用チャットの標準初期化プロンプトである。

新しいTradingAIチャットを開始する際は、「Initialization Prompt」の内容をチャット冒頭へ貼り付けて使用する。

Versionは運用改善・Constitutionの更新・文書体系の変更に合わせて更新する。

本Initializationは、TradingAI Constitutionを中心としたDocument Governanceを維持することを目的とする。