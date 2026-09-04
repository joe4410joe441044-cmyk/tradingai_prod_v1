"""Shared, READ-ONLY canonical knowledge loading and verification.

This is the single canonical loading boundary for TradingAI.  It loads a
deterministic, explicitly allowlisted set of hash-pinned specification
documents from a repository-relative approved path and verifies each with
SHA-256.  It is INFORMATION AUTHORITY only:

  * Execution / configuration / governance / MM / emergency / PAPER-LIVE /
    BOT / Loop / Auto Trade authority = NONE
  * No write / save / update / delete / execute / submit / cancel / start /
    stop / unlock / approve capability
  * No network call, no provider, no API key, no LLM dependency
  * No generic filesystem reader: only explicitly registered manifest entries
    under ``docs/`` may be read

Verification is fail-closed.  A changed canonical specification becomes an
explicit ``HASH_MISMATCH`` state (drift) rather than being auto-repaired.
Repeated loading of an unchanged set is deterministic.

Dependency direction (never reversed): ``ai_advisor`` and ``supervisor`` may
import this module; it never imports from either.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import ClassVar, Optional, Tuple

from ._base import stable_json
from .authority import KnowledgeAuthority, SourceCategory, TruthLevel
from .provenance import ProvenanceRecord

MAX_CANONICAL_DOCUMENT_BYTES = 262_144
_HASH_PREFIX = "sha256:"
_HASH_HEX_LEN = 64
_HEX_CHARS = "0123456789abcdef"
_PRODUCTION_DOCUMENTS = "docs/"


def sha256_digest(content: bytes) -> str:
    """Return the ``sha256:<hex>`` digest of raw bytes."""
    return _HASH_PREFIX + hashlib.sha256(content).hexdigest()


def default_repository_root() -> Path:
    """Return the repository root containing the ``backend`` and ``docs`` trees."""
    return Path(__file__).resolve().parents[2]


def _validate_relative_path(value: str) -> str:
    path = Path(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or value != path.as_posix()
        or not value.startswith(_PRODUCTION_DOCUMENTS)
    ):
        raise ValueError("canonical knowledge path must be under docs")
    return value


def _validate_sha256(value: str) -> str:
    if not isinstance(value, str) or not value.startswith(_HASH_PREFIX):
        raise ValueError("expected hash must be sha256:<hex>")
    digest = value[len(_HASH_PREFIX):]
    if len(digest) != _HASH_HEX_LEN or any(ch not in _HEX_CHARS for ch in digest):
        raise ValueError("expected hash must be a lowercase sha256 digest")
    return value


class VerificationState(str, Enum):
    """Outcome of verifying one canonical specification document.

    ``VERIFIED``    the file exists, resolves inside the approved root, is a
                    regular file within the size bound, and its SHA-256 matches.
    ``MISSING``     the approved source is not present / not an eligible file.
    ``HASH_MISMATCH`` the present file does not match its pinned hash (drift).
    ``REJECTED_PATH`` the approved path escapes the security boundary.
    """

    VERIFIED = "VERIFIED"
    MISSING = "MISSING"
    HASH_MISMATCH = "HASH_MISMATCH"
    REJECTED_PATH = "REJECTED_PATH"


class CanonicalKnowledgeAuthority(str, Enum):
    """Authority tier of a canonical specification (descriptive metadata)."""

    CONSTITUTION = "CONSTITUTION"
    ADR = "ADR"
    MASTER_SPEC = "MASTER_SPEC"
    FEATURE_SPEC = "FEATURE_SPEC"


AUTHORITY_PRIORITY = {
    CanonicalKnowledgeAuthority.CONSTITUTION: 4,
    CanonicalKnowledgeAuthority.ADR: 3,
    CanonicalKnowledgeAuthority.MASTER_SPEC: 2,
    CanonicalKnowledgeAuthority.FEATURE_SPEC: 1,
}


class CanonicalKnowledgeLoadError(ValueError):
    """Fail-closed error raised while loading an approved canonical set."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__("canonical knowledge is unavailable")


@dataclass(frozen=True)
class CanonicalKnowledgeEntry:
    """A single explicitly approved canonical specification record.

    This is an allowlist entry, not a file reader.  The loader will only ever
    consider paths described here; it never discovers or searches the tree.
    """

    document_id: str
    knowledge_key: str
    authority: CanonicalKnowledgeAuthority
    title: str
    relative_path: str
    version: str
    topics: Tuple[str, ...]
    excerpt: str
    expected_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.authority, CanonicalKnowledgeAuthority):
            raise ValueError("authority must be a CanonicalKnowledgeAuthority")
        _validate_relative_path(self.relative_path)
        _validate_sha256(self.expected_sha256)
        if not self.document_id or not self.knowledge_key:
            raise ValueError("document_id and knowledge_key are required")
        if not self.topics:
            raise ValueError("topics must be non-empty")
        if not self.excerpt.strip():
            raise ValueError("excerpt must be non-empty")

    @property
    def approved_path(self) -> str:
        return self.relative_path


@dataclass(frozen=True)
class CanonicalKnowledgeManifest:
    """Deterministic allowlist manifest of canonical knowledge entries."""

    name: str
    entries: Tuple[CanonicalKnowledgeEntry, ...]

    def __post_init__(self) -> None:
        if not self.name or not self.entries:
            raise ValueError("manifest requires a name and at least one entry")
        document_ids = [entry.document_id for entry in self.entries]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("canonical document_id must be unique")

    def by_id(self, document_id: str) -> Optional[CanonicalKnowledgeEntry]:
        for entry in self.entries:
            if entry.document_id == document_id:
                return entry
        return None

    @property
    def document_ids(self) -> Tuple[str, ...]:
        return tuple(entry.document_id for entry in self.entries)

    def select_highest_authority(
        self,
    ) -> Tuple[CanonicalKnowledgeEntry, ...]:
        """Dedupe by ``knowledge_key`` keeping the highest-authority entry.

        Deterministic: ties that are not identical conflict loudly rather than
        silently keeping either.  Result is sorted by ``document_id``.
        """
        selected: dict[str, CanonicalKnowledgeEntry] = {}
        for entry in self.entries:
            existing = selected.get(entry.knowledge_key)
            if existing is None:
                selected[entry.knowledge_key] = entry
                continue
            current = AUTHORITY_PRIORITY[entry.authority]
            previous = AUTHORITY_PRIORITY[existing.authority]
            if current > previous:
                selected[entry.knowledge_key] = entry
            elif current == previous and entry != existing:
                raise CanonicalKnowledgeLoadError(
                    "SAME_AUTHORITY_CONFLICT", entry.document_id
                )
        return tuple(sorted(selected.values(), key=lambda item: item.document_id))

    def stable_json(self) -> str:
        return stable_json(self.entries)


@dataclass(frozen=True)
class CanonicalKnowledgeDocument:
    """A loaded + verified (or declared-failed) canonical document.

    ``verification_state`` records the outcome deterministically.  For
    ``VERIFIED``, ``content`` holds the approved text and ``actual_sha256`` is
    the computed digest; otherwise ``content`` is empty and ``actual_sha256``
    is ``None`` unless the file existed (``HASH_MISMATCH``).
    """

    entry: CanonicalKnowledgeEntry
    content: str
    expected_sha256: str
    actual_sha256: Optional[str]
    verification_state: VerificationState
    provenance: ProvenanceRecord

    @property
    def document_id(self) -> str:
        return self.entry.document_id

    @property
    def approved_path(self) -> str:
        return self.entry.relative_path

    @property
    def is_verified(self) -> bool:
        return self.verification_state is VerificationState.VERIFIED


@dataclass(frozen=True)
class CanonicalKnowledgeLoadResult:
    """Typed result of a canonical load, including any declared failures.

    Ordering follows the manifest entry order, which is deterministic.
    ``documents`` holds every attempt (verified and failed) so drift is
    observable; verify via :attr:`all_verified` and :attr:`verified_documents`.
    """

    manifest: CanonicalKnowledgeManifest
    repository_root: str
    documents: Tuple[CanonicalKnowledgeDocument, ...]

    @property
    def verified_documents(self) -> Tuple[CanonicalKnowledgeDocument, ...]:
        return tuple(doc for doc in self.documents if doc.is_verified)

    @property
    def failures(self) -> Tuple[CanonicalKnowledgeDocument, ...]:
        return tuple(doc for doc in self.documents if not doc.is_verified)

    @property
    def verified_document_ids(self) -> Tuple[str, ...]:
        return tuple(doc.document_id for doc in self.verified_documents)

    @property
    def all_verified(self) -> bool:
        return all(doc.is_verified for doc in self.documents)

    def stable_json(self) -> str:
        return stable_json(self)


class CanonicalKnowledgeLoader:
    """READ-ONLY loader that verifies an explicit canonical manifest.

    The loader only reads paths declared in the manifest.  It exposes no
    runtime action, no authority and no mutation capability.
    """

    KNOWLEDGE_AUTHORITY: ClassVar[KnowledgeAuthority] = KnowledgeAuthority.INFORMATION_ONLY

    def __init__(self, *, repository_root: Path | str):
        self._root = Path(repository_root).resolve(strict=True)

    @property
    def repository_root(self) -> str:
        return str(self._root)

    @property
    def authority(self) -> KnowledgeAuthority:
        return KnowledgeAuthority.INFORMATION_ONLY

    @property
    def grants_any_authority(self) -> bool:
        return False

    def _provenance(
        self,
        entry: CanonicalKnowledgeEntry,
        actual_sha256: Optional[str],
        state: VerificationState,
        note: str,
    ) -> ProvenanceRecord:
        return ProvenanceRecord(
            truth_level=TruthLevel.CANONICAL_SPECIFICATION,
            source_category=SourceCategory.SPECIFICATION,
            source_reference=entry.relative_path,
            source_path=entry.relative_path,
            version=entry.version,
            content_hash=actual_sha256,
            verified=state is VerificationState.VERIFIED,
            notes=note,
        )

    def _failure(
        self,
        entry: CanonicalKnowledgeEntry,
        state: VerificationState,
        note: str,
        actual_sha256: Optional[str] = None,
    ) -> CanonicalKnowledgeDocument:
        return CanonicalKnowledgeDocument(
            entry=entry,
            content="",
            expected_sha256=entry.expected_sha256,
            actual_sha256=actual_sha256,
            verification_state=state,
            provenance=self._provenance(entry, actual_sha256, state, note),
        )

    def _load_entry(self, entry: CanonicalKnowledgeEntry) -> CanonicalKnowledgeDocument:
        root = self._root
        candidate = root / entry.relative_path
        if candidate.is_symlink():
            return self._failure(
                entry, VerificationState.REJECTED_PATH,
                "declined: symbolic links are not allowed",
            )
        if not candidate.exists():
            return self._failure(
                entry, VerificationState.MISSING,
                "declined: approved source is not present",
            )
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except ValueError:
            return self._failure(
                entry, VerificationState.REJECTED_PATH,
                "declined: path escapes the approved root",
            )
        except (FileNotFoundError, OSError):
            return self._failure(
                entry, VerificationState.MISSING,
                "declined: approved source is unavailable",
            )
        if not resolved.is_file() or resolved.stat().st_size > MAX_CANONICAL_DOCUMENT_BYTES:
            return self._failure(
                entry, VerificationState.MISSING,
                "declined: approved source is not an eligible regular file",
            )
        content_bytes = resolved.read_bytes()
        actual_sha256 = sha256_digest(content_bytes)
        if actual_sha256 != entry.expected_sha256:
            return self._failure(
                entry, VerificationState.HASH_MISMATCH,
                "declined: canonical hash mismatch (drift)",
                actual_sha256,
            )
        try:
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return self._failure(
                entry, VerificationState.MISSING,
                "declined: approved source encoding is not UTF-8",
                actual_sha256,
            )
        return CanonicalKnowledgeDocument(
            entry=entry,
            content=content,
            expected_sha256=entry.expected_sha256,
            actual_sha256=actual_sha256,
            verification_state=VerificationState.VERIFIED,
            provenance=self._provenance(
                entry, actual_sha256, VerificationState.VERIFIED,
                "verification=VERIFIED",
            ),
        )

    def load(
        self,
        manifest: CanonicalKnowledgeManifest,
        *,
        strict: bool = False,
    ) -> CanonicalKnowledgeLoadResult:
        """Load and verify every manifest entry in deterministic order.

        ``strict=False`` (default) records each failure and returns it in the
        result, fail-closed by omission from :attr:`verified_documents`.
        ``strict=True`` raises :class:`CanonicalKnowledgeLoadError` on the
        first non-verified document.
        """
        if not isinstance(manifest, CanonicalKnowledgeManifest):
            raise TypeError("typed CanonicalKnowledgeManifest required")
        documents = tuple(self._load_entry(entry) for entry in manifest.entries)
        if strict:
            for doc in documents:
                if not doc.is_verified:
                    raise CanonicalKnowledgeLoadError(
                        doc.verification_state.value, doc.document_id
                    )
        return CanonicalKnowledgeLoadResult(
            manifest=manifest,
            repository_root=self.repository_root,
            documents=documents,
        )

    def load_production_manifest(self, *, strict: bool = False) -> CanonicalKnowledgeLoadResult:
        return self.load(production_canonical_knowledge_manifest(), strict=strict)

    def stable_json(self) -> str:
        return stable_json({
            "authority": self.authority.value,
            "repository_root": self.repository_root,
            "manifest": production_canonical_knowledge_manifest(),
        })


def _production_entries() -> Tuple[CanonicalKnowledgeEntry, ...]:
    return (
        CanonicalKnowledgeEntry(
            document_id="tradingai-constitution-v0.1",
            knowledge_key="platform-architecture",
            authority=CanonicalKnowledgeAuthority.CONSTITUTION,
            title="TradingAI Constitution",
            relative_path="docs/00_CONSTITUTION/00_TradingAI_Constitution.md",
            version="0.1",
            topics=("PLATFORM", "RUNTIME", "VALIDATION"),
            expected_sha256=(
                "sha256:f2cfb2e19251d49480ad094bf622f8d6bc20c942837e6d1ef193e355cd28a67f"
            ),
            excerpt=(
                "TradingAIは、市場認識と意思決定を、人間では困難な速度・情報量・一貫性で行うことを使命とする。"
                "Runtimeは単なる高速注文プログラムではなく、市場認識と意思決定を担うDecision Engineである。"
                "RuntimeはReplay、Paper Trade、Small Live、Analyticsによって継続的に検証される。"
            ),
        ),
        CanonicalKnowledgeEntry(
            document_id="ai-advisor-master-v1.0",
            knowledge_key="component-ai-advisor",
            authority=CanonicalKnowledgeAuthority.MASTER_SPEC,
            title="TradingAI AI Advisor Master Specification",
            relative_path="docs/ai_advisor/01_AI_Advisor_Master_Specification.md",
            version="1.0",
            topics=("AI_ADVISOR", "PLATFORM", "RELATIONSHIPS"),
            expected_sha256=(
                "sha256:24354b593badd8bdda2d41c7f98dec8da85afc0e563a5ecab4fbe260953b50e0"
            ),
            excerpt=(
                "AI AdvisorはTradingAIの研究・分析パートナーであり、取引エンジンの代替ではない。"
                "Recorderデータ、承認済み仕様、Runtimeログ、過去結果を利用して、市場分析、Recorder分析、"
                "パターン発見、戦略・性能・リスクのレビュー、取引説明、研究と文書化を支援する。"
                "リアルタイムの市場データ処理、Strategy、Money Management、Governance、Executionは"
                "決定論的なPython側の責任であり、AI Advisorは取引を執行せずGovernanceを上書きしない。"
            ),
        ),
        CanonicalKnowledgeEntry(
            document_id="market-intelligence-component-v1.0",
            knowledge_key="component-market-intelligence",
            authority=CanonicalKnowledgeAuthority.FEATURE_SPEC,
            title="Market Intelligence Component Specification",
            relative_path="docs/market_intelligence/02_MARKET_INTELLIGENCE_COMPONENT_SPEC.md",
            version="1.0",
            topics=("MARKET_INTELLIGENCE", "REPLAY", "DECISION_TRACE"),
            expected_sha256=(
                "sha256:e6a73899974b34347e43b45dbb920b01d1b14738bc256d567bd468e0f392f4aa"
            ),
            excerpt=(
                "Market Intelligenceは、選択したポジションを中心に過去の市場状態と意思決定をレビューする画面である。"
                "Market ReplayはOrder Book、Recent Trades、イベント、タイムラインを再現し、Decision Railwayは"
                "Python RuntimeからStrategy、Governance、Executionまでの記録済み経路と結果を説明する。"
                "Data QualityはCOMPLETE、PARTIAL、STALE、UNSYNCED、MISSING、MALFORMED、UNSUPPORTEDを区別する。"
                "欠損理由を明示し、記録のない理由や最終判断をUIが推測してはならない。取引操作は持たない。"
            ),
        ),
        CanonicalKnowledgeEntry(
            document_id="money-management-master-v1.0",
            knowledge_key="component-money-management",
            authority=CanonicalKnowledgeAuthority.MASTER_SPEC,
            title="Money Management Master Specification",
            relative_path="docs/money_management/01_Money_Management_Master_Specification.md",
            version="1.0",
            topics=("MONEY_MANAGEMENT", "RISK", "RELATIONSHIPS"),
            expected_sha256=(
                "sha256:5374c287173bee4ffd643eee7bb80aa05010930d84f4f5a9722ddae963c7b377"
            ),
            excerpt=(
                "Money Managementは資本配分とリスクを決定し、資本保全を前提にMicro Edgeを継続的に積み重ねる。"
                "Trading Decisionが示した方向と要求サイズに対し、サイズを承認、縮小、またはブロックするが、"
                "方向を変更したりHOLDから売買判断を作ったりしない。Governanceが最終安全権限を持つ。"
                "文書化されたRisk StateはNORMAL、CAUTION、DEFENSIVE、LOCKED、RECOVERY_25、RECOVERY_50であり、"
                "結果はAPPROVED、SIZE_REDUCED、RISK_BLOCKED、INVALID_INPUT、INSUFFICIENT_DATAを含む。"
                "これらは定義であり、現在値を示すものではない。"
            ),
        ),
        CanonicalKnowledgeEntry(
            document_id="market-recorder-master-v1.0",
            knowledge_key="component-market-recorder",
            authority=CanonicalKnowledgeAuthority.MASTER_SPEC,
            title="Market Recorder Master Specification",
            relative_path="docs/market_recorder/01_Market_Recorder_Master_Specification.md",
            version="1.0",
            topics=("MARKET_RECORDER", "DATA", "REPLAY"),
            expected_sha256=(
                "sha256:664be2d3eeb1726c0975ec3a9fe28cf4bdd82674c32f7dc8b41abd7938dc180e"
            ),
            excerpt=(
                "Market Recorderはマーケットデータを完全、決定論的、再生可能、復旧可能、保存効率良く、"
                "長期保管可能な形で収集・保存する。正式な流れはWebSocket、正規化、Active Writer、"
                "時間ローテーション、Zstandardアーカイブ、Manifest生成、SnapshotまたはRecovery、Data Accessである。"
                "稼働中の一時ファイルだけで障害と判断せず、確定アーカイブとManifestも確認する。"
            ),
        ),
        CanonicalKnowledgeEntry(
            document_id="supervisor-master-v1.1",
            knowledge_key="component-supervisor",
            authority=CanonicalKnowledgeAuthority.MASTER_SPEC,
            title="Supervisor Master Specification",
            relative_path="docs/SUPERVISOR/01_SUPERVISOR_Master_Specification.md",
            version="1.1",
            topics=("SUPERVISOR", "OVERSIGHT", "RELATIONSHIPS"),
            expected_sha256=(
                "sha256:bc19a991fe73c6a5b3a9a03bae56fea515470c69e6ef91d35d29755305f6fbc0"
            ),
            excerpt=(
                "SupervisorはTradingAIの運用監督層で、初期構成はMaster SupervisorとMM Supervisorである。"
                "Masterは全体の運用状態と姿勢を説明し、MM Supervisorは権威あるMoney Management状態を評価する。"
                "初期モードはSHADOWで、両者は監督・説明を行うが、決定論的Python権限を置き換えず、"
                "注文やRuntime設定を変更しない。AI Advisorは研究、設計、改善提案、事後レビュー、"
                "Supervisor判断のセカンドオピニオンを担う別レイヤーであり、運用権限を持たない。"
            ),
        ),
    )


def production_canonical_knowledge_manifest() -> CanonicalKnowledgeManifest:
    """Return the sole production canonical allowlist; discovery is prohibited.

    Exactly the six hash-pinned documents validated by D-0/D-2.  Order is the
    deterministic allowlist order; do not add or remove entries silently.
    """
    return CanonicalKnowledgeManifest(
        name="tradingai-production-canonical-specifications",
        entries=_production_entries(),
    )


def load_canonical_knowledge(
    manifest: CanonicalKnowledgeManifest,
    *,
    repository_root: Path | str,
    strict: bool = False,
) -> CanonicalKnowledgeLoadResult:
    """Load and verify a canonical manifest against ``repository_root``."""
    return CanonicalKnowledgeLoader(repository_root=repository_root).load(
        manifest, strict=strict
    )
