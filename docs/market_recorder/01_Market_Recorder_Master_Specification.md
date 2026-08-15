# 01_Market_Recorder_Master_Specification.md

# Market Recorder Master Specification

**Version:** 1.0\
**Status:** Authoritative Master Specification

------------------------------------------------------------------------

# 1. Purpose

本仕様書は **Market Recorder**
プロジェクト全体の最上位仕様書（マスター仕様書）である。

本書はプロジェクト全体の目的、設計思想、アーキテクチャ、および各下位仕様書の役割を定義する。
詳細な設計・契約・実装要件は下位仕様書へ委譲し、本書は長期的に維持される「憲法」として位置付ける。

------------------------------------------------------------------------

# 2. Project Goal

Market Recorder はマーケットデータを以下の原則で収集・保存する。

-   Complete
-   Deterministic
-   Replayable
-   Recoverable
-   Storage Efficient
-   Long-term Archivable

------------------------------------------------------------------------

# 3. Design Principles

-   Data Integrity First
-   Deterministic Storage
-   Immutable Archive
-   Fault Tolerance
-   Recoverability
-   Replay Safety

------------------------------------------------------------------------

# 4. System Architecture

    WebSocket
        ↓
    Normalization
        ↓
    Active Writer (.jsonl.part)
        ↓
    Hourly Rotation
        ↓
    Zstandard Compression (.jsonl.zst)
        ↓
    Manifest Generation
        ↓
    Snapshot / Recovery
        ↓
    Data Access

------------------------------------------------------------------------

# 5. Runtime Storage Lifecycle

Market Recorder の保存ライフサイクルを以下の正式仕様とする。

1.  稼働中データは `active/` 配下へ `.jsonl.part` として追記される。
2.  `.jsonl.part`
    は未圧縮の**作業中ファイル**であり、その存在は圧縮機能の未実装または障害を意味しない。
3.  ローテーション完了後、ファイルは `archive/` 配下へ `.jsonl.zst`
    として保存される。
4.  アーカイブ確定後、対応する Manifest が生成される。
5.  圧縮状態を確認する場合は、`active/` の `.jsonl.part`
    のみで判断せず、`archive/` の `.jsonl.zst` および Manifest
    を確認すること。

正式ライフサイクル:

    active/*.jsonl.part
            ↓
    rotation / finalization
            ↓
    archive/*.jsonl.zst
            ↓
    *.jsonl.zst.manifest.json

> **重要:** `.jsonl.part`
> の存在だけで「圧縮されていない」と判断してはならない。

------------------------------------------------------------------------

# 6. Specification Hierarchy

    01_Market_Recorder_Master_Specification.md
    │
    ├── 02_Market_Recorder_Storage_Contract.md
    ├── 03_Market_Recorder_Data_Access_Contract.md
    ├── 04_Market_Recorder_Snapshot_Gap_Recovery_Architecture.md
    ├── 05_Market_Recorder_Storage_Contract_v2.md
    └── 06_Market_Recorder_Storage_v2_Certification_Plan.md

------------------------------------------------------------------------

# 7. Responsibilities

-   **01**：プロジェクト全体の設計思想・原則・構成
-   **02**：Storage Contract
-   **03**：Data Access Contract
-   **04**：Snapshot / Gap Recovery Architecture
-   **05**：Storage Contract v2
-   **06**：Certification Plan

------------------------------------------------------------------------

# 8. Authority

本書を Market Recorder プロジェクトの最上位仕様書とする。
下位仕様書は本書の原則に従って策定・更新される。
