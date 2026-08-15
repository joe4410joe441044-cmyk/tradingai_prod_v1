"""Explicit, hash-pinned TradingAI static knowledge for AI Advisor prompts."""

import hashlib
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal, Tuple

from pydantic import Field, field_validator

from backend.ai_advisor.context_builder import SpecificationSourceInput
from backend.ai_advisor.conversation_models import AdvisorContractModel


class KnowledgeAuthorityLevel(str, Enum):
    CONSTITUTION = "CONSTITUTION"
    ADR = "ADR"
    MASTER_SPEC = "MASTER_SPEC"
    FEATURE_SPEC = "FEATURE_SPEC"


AUTHORITY_PRIORITY = {
    KnowledgeAuthorityLevel.CONSTITUTION: 4,
    KnowledgeAuthorityLevel.ADR: 3,
    KnowledgeAuthorityLevel.MASTER_SPEC: 2,
    KnowledgeAuthorityLevel.FEATURE_SPEC: 1,
}


class AuthoritativeKnowledgeEntry(AdvisorContractModel):
    sourceId: Annotated[str, Field(min_length=1, max_length=128)]
    knowledgeKey: Annotated[str, Field(min_length=1, max_length=128)]
    authority: KnowledgeAuthorityLevel
    title: Annotated[str, Field(min_length=1, max_length=256)]
    relativePath: Annotated[str, Field(min_length=1, max_length=256)]
    version: Annotated[str, Field(min_length=1, max_length=64)]
    topics: Annotated[
        Tuple[str, ...],
        Field(min_length=1, max_length=12, strict=False),
    ]
    excerpt: Annotated[str, Field(min_length=1, max_length=8_000)]
    expectedHash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    approved: Literal[True] = True

    @field_validator("relativePath")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = Path(value)
        if (
            path.is_absolute()
            or ".." in path.parts
            or value != path.as_posix()
            or not value.startswith("docs/")
        ):
            raise ValueError("knowledge path must be canonical under docs")
        return value


class KnowledgeManifestError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__("authoritative knowledge is unavailable")


def production_knowledge_manifest() -> Tuple[AuthoritativeKnowledgeEntry, ...]:
    """Return the sole production allowlist; repository discovery is prohibited."""

    return (
        AuthoritativeKnowledgeEntry(
            sourceId="tradingai-constitution-v0.1",
            knowledgeKey="platform-architecture",
            authority=KnowledgeAuthorityLevel.CONSTITUTION,
            title="TradingAI Constitution",
            relativePath="docs/00_CONSTITUTION/00_TradingAI_Constitution.md",
            version="0.1",
            topics=("PLATFORM", "RUNTIME", "VALIDATION"),
            expectedHash="sha256:f2cfb2e19251d49480ad094bf622f8d6bc20c942837e6d1ef193e355cd28a67f",
            excerpt=(
                "TradingAIは、市場認識と意思決定を、人間では困難な速度・情報量・一貫性で行うことを使命とする。"
                "Runtimeは単なる高速注文プログラムではなく、市場認識と意思決定を担うDecision Engineである。"
                "RuntimeはReplay、Paper Trade、Small Live、Analyticsによって継続的に検証される。"
            ),
        ),
        AuthoritativeKnowledgeEntry(
            sourceId="ai-advisor-master-v1.0",
            knowledgeKey="component-ai-advisor",
            authority=KnowledgeAuthorityLevel.MASTER_SPEC,
            title="TradingAI AI Advisor Master Specification",
            relativePath="docs/ai_advisor/01_AI_Advisor_Master_Specification.md",
            version="1.0",
            topics=("AI_ADVISOR", "PLATFORM", "RELATIONSHIPS"),
            expectedHash="sha256:24354b593badd8bdda2d41c7f98dec8da85afc0e563a5ecab4fbe260953b50e0",
            excerpt=(
                "AI AdvisorはTradingAIの研究・分析パートナーであり、取引エンジンの代替ではない。"
                "Recorderデータ、承認済み仕様、Runtimeログ、過去結果を利用して、市場分析、Recorder分析、"
                "パターン発見、戦略・性能・リスクのレビュー、取引説明、研究と文書化を支援する。"
                "リアルタイムの市場データ処理、Strategy、Money Management、Governance、Executionは"
                "決定論的なPython側の責任であり、AI Advisorは取引を執行せずGovernanceを上書きしない。"
            ),
        ),
        AuthoritativeKnowledgeEntry(
            sourceId="market-intelligence-component-v1.0",
            knowledgeKey="component-market-intelligence",
            authority=KnowledgeAuthorityLevel.FEATURE_SPEC,
            title="Market Intelligence Component Specification",
            relativePath="docs/market_intelligence/02_MARKET_INTELLIGENCE_COMPONENT_SPEC.md",
            version="1.0",
            topics=("MARKET_INTELLIGENCE", "REPLAY", "DECISION_TRACE"),
            expectedHash="sha256:e6a73899974b34347e43b45dbb920b01d1b14738bc256d567bd468e0f392f4aa",
            excerpt=(
                "Market Intelligenceは、選択したポジションを中心に過去の市場状態と意思決定をレビューする画面である。"
                "Market ReplayはOrder Book、Recent Trades、イベント、タイムラインを再現し、Decision Railwayは"
                "Python RuntimeからStrategy、Governance、Executionまでの記録済み経路と結果を説明する。"
                "Data QualityはCOMPLETE、PARTIAL、STALE、UNSYNCED、MISSING、MALFORMED、UNSUPPORTEDを区別する。"
                "欠損理由を明示し、記録のない理由や最終判断をUIが推測してはならない。取引操作は持たない。"
            ),
        ),
        AuthoritativeKnowledgeEntry(
            sourceId="money-management-master-v1.0",
            knowledgeKey="component-money-management",
            authority=KnowledgeAuthorityLevel.MASTER_SPEC,
            title="Money Management Master Specification",
            relativePath="docs/money_management/01_Money_Management_Master_Specification.md",
            version="1.0",
            topics=("MONEY_MANAGEMENT", "RISK", "RELATIONSHIPS"),
            expectedHash="sha256:5374c287173bee4ffd643eee7bb80aa05010930d84f4f5a9722ddae963c7b377",
            excerpt=(
                "Money Managementは資本配分とリスクを決定し、資本保全を前提にMicro Edgeを継続的に積み重ねる。"
                "Trading Decisionが示した方向と要求サイズに対し、サイズを承認、縮小、またはブロックするが、"
                "方向を変更したりHOLDから売買判断を作ったりしない。Governanceが最終安全権限を持つ。"
                "文書化されたRisk StateはNORMAL、CAUTION、DEFENSIVE、LOCKED、RECOVERY_25、RECOVERY_50であり、"
                "結果はAPPROVED、SIZE_REDUCED、RISK_BLOCKED、INVALID_INPUT、INSUFFICIENT_DATAを含む。"
                "これらは定義であり、現在値を示すものではない。"
            ),
        ),
        AuthoritativeKnowledgeEntry(
            sourceId="market-recorder-master-v1.0",
            knowledgeKey="component-market-recorder",
            authority=KnowledgeAuthorityLevel.MASTER_SPEC,
            title="Market Recorder Master Specification",
            relativePath="docs/market_recorder/01_Market_Recorder_Master_Specification.md",
            version="1.0",
            topics=("MARKET_RECORDER", "DATA", "REPLAY"),
            expectedHash="sha256:664be2d3eeb1726c0975ec3a9fe28cf4bdd82674c32f7dc8b41abd7938dc180e",
            excerpt=(
                "Market Recorderはマーケットデータを完全、決定論的、再生可能、復旧可能、保存効率良く、"
                "長期保管可能な形で収集・保存する。正式な流れはWebSocket、正規化、Active Writer、"
                "時間ローテーション、Zstandardアーカイブ、Manifest生成、SnapshotまたはRecovery、Data Accessである。"
                "稼働中の一時ファイルだけで障害と判断せず、確定アーカイブとManifestも確認する。"
            ),
        ),
        AuthoritativeKnowledgeEntry(
            sourceId="supervisor-master-v1.1",
            knowledgeKey="component-supervisor",
            authority=KnowledgeAuthorityLevel.MASTER_SPEC,
            title="Supervisor Master Specification",
            relativePath="docs/SUPERVISOR/01_SUPERVISOR_Master_Specification.md",
            version="1.1",
            topics=("SUPERVISOR", "OVERSIGHT", "RELATIONSHIPS"),
            expectedHash="sha256:bc19a991fe73c6a5b3a9a03bae56fea515470c69e6ef91d35d29755305f6fbc0",
            excerpt=(
                "SupervisorはTradingAIの運用監督層で、初期構成はMaster SupervisorとMM Supervisorである。"
                "Masterは全体の運用状態と姿勢を説明し、MM Supervisorは権威あるMoney Management状態を評価する。"
                "初期モードはSHADOWで、両者は監督・説明を行うが、決定論的Python権限を置き換えず、"
                "注文やRuntime設定を変更しない。AI Advisorは研究、設計、改善提案、事後レビュー、"
                "Supervisor判断のセカンドオピニオンを担う別レイヤーであり、運用権限を持たない。"
            ),
        ),
    )


def select_highest_authority(
    entries: Tuple[AuthoritativeKnowledgeEntry, ...],
) -> Tuple[AuthoritativeKnowledgeEntry, ...]:
    selected = {}
    for entry in entries:
        existing = selected.get(entry.knowledgeKey)
        if existing is None:
            selected[entry.knowledgeKey] = entry
            continue
        current = AUTHORITY_PRIORITY[entry.authority]
        previous = AUTHORITY_PRIORITY[existing.authority]
        if current > previous:
            selected[entry.knowledgeKey] = entry
        elif current == previous and entry != existing:
            raise KnowledgeManifestError("SAME_AUTHORITY_CONFLICT")
    return tuple(sorted(selected.values(), key=lambda item: item.sourceId))


def _load_entry(
    entry: AuthoritativeKnowledgeEntry,
    *,
    repository_root: Path,
    loaded_at: datetime,
) -> SpecificationSourceInput:
    root = repository_root.resolve(strict=True)
    candidate = root / entry.relativePath
    if candidate.is_symlink():
        raise KnowledgeManifestError("SYMLINK_REJECTED")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError):
        raise KnowledgeManifestError("SOURCE_NOT_AVAILABLE") from None
    if not resolved.is_file() or resolved.stat().st_size > 262_144:
        raise KnowledgeManifestError("SOURCE_NOT_ELIGIBLE")
    content = resolved.read_bytes()
    actual_hash = "sha256:" + hashlib.sha256(content).hexdigest()
    if actual_hash != entry.expectedHash:
        raise KnowledgeManifestError("HASH_MISMATCH")
    return SpecificationSourceInput(
        sourceId=entry.sourceId,
        sourceVersion=entry.version,
        title=entry.title,
        documentPath=entry.relativePath,
        loadedAt=loaded_at,
        contentHash=actual_hash,
        authorityLevel=entry.authority.value,
        topics=entry.topics,
        excerpt=entry.excerpt,
    )


def load_authoritative_specifications(
    *,
    repository_root: Path | None = None,
    loaded_at: datetime | None = None,
    entries: Tuple[AuthoritativeKnowledgeEntry, ...] | None = None,
    strict: bool = False,
) -> Tuple[SpecificationSourceInput, ...]:
    """Load only explicit manifest entries; invalid sources fail closed by omission."""

    root = repository_root or Path(__file__).resolve().parents[2]
    timestamp = (loaded_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    selected = select_highest_authority(
        production_knowledge_manifest() if entries is None else entries
    )
    loaded = []
    for entry in selected:
        try:
            loaded.append(
                _load_entry(entry, repository_root=root, loaded_at=timestamp)
            )
        except KnowledgeManifestError:
            if strict:
                raise
    return tuple(loaded)
