"""Explicit, hash-pinned TradingAI static knowledge for AI Advisor prompts.

Thin compatibility facade over the shared canonical loader
:mod:`backend.knowledge_core.canonical_loader`.  The public contract
(``production_knowledge_manifest``, ``load_authoritative_specifications``,
``select_highest_authority``, ``AuthoritativeKnowledgeEntry``,
``KnowledgeAuthorityLevel``) is preserved exactly; the six-document allowlist
and the fail-closed SHA-256 / path-security behaviour are unchanged.

The Knowledge Core is INFORMATION AUTHORITY only.  This module exposes no
runtime action and no mutation capability.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal, Tuple

from pydantic import Field, field_validator

from backend.ai_advisor.context_builder import SpecificationSourceInput
from backend.ai_advisor.conversation_models import AdvisorContractModel
from backend.knowledge_core.canonical_loader import (
    AUTHORITY_PRIORITY,
    CanonicalKnowledgeAuthority,
    CanonicalKnowledgeEntry,
    CanonicalKnowledgeLoadError,
    CanonicalKnowledgeLoader,
    CanonicalKnowledgeManifest,
    default_repository_root,
    production_canonical_knowledge_manifest,
)


# Backward-compatible alias: the canonical authority enum is the same value
# space, so existing ``KnowledgeAuthorityLevel.<MEMBER>`` references still work.
KnowledgeAuthorityLevel = CanonicalKnowledgeAuthority


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
        from backend.knowledge_core.canonical_loader import _validate_relative_path

        return _validate_relative_path(value)


class KnowledgeManifestError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__("authoritative knowledge is unavailable")


def production_knowledge_manifest() -> Tuple[AuthoritativeKnowledgeEntry, ...]:
    """Return the sole production allowlist; repository discovery is prohibited."""

    return tuple(
        _canonical_to_advisory(entry)
        for entry in production_canonical_knowledge_manifest().entries
    )


def _canonical_to_advisory(entry: CanonicalKnowledgeEntry) -> AuthoritativeKnowledgeEntry:
    return AuthoritativeKnowledgeEntry(
        sourceId=entry.document_id,
        knowledgeKey=entry.knowledge_key,
        authority=KnowledgeAuthorityLevel(entry.authority.value),
        title=entry.title,
        relativePath=entry.relative_path,
        version=entry.version,
        topics=entry.topics,
        excerpt=entry.excerpt,
        expectedHash=entry.expected_sha256,
    )


def _advisory_to_canonical(entry: AuthoritativeKnowledgeEntry) -> CanonicalKnowledgeEntry:
    return CanonicalKnowledgeEntry(
        document_id=entry.sourceId,
        knowledge_key=entry.knowledgeKey,
        authority=CanonicalKnowledgeAuthority(entry.authority.value),
        title=entry.title,
        relative_path=entry.relativePath,
        version=entry.version,
        topics=entry.topics,
        excerpt=entry.excerpt,
        expected_sha256=entry.expectedHash,
    )


def _document_to_source_input(
    document,
    *,
    loaded_at: datetime,
) -> SpecificationSourceInput:
    entry = document.entry
    return SpecificationSourceInput(
        sourceId=entry.document_id,
        sourceVersion=entry.version,
        title=entry.title,
        documentPath=entry.relative_path,
        loadedAt=loaded_at,
        contentHash=document.actual_sha256,
        authorityLevel=entry.authority.value,
        topics=entry.topics,
        excerpt=entry.excerpt,
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


def load_authoritative_specifications(
    *,
    repository_root: Path | None = None,
    loaded_at: datetime | None = None,
    entries: Tuple[AuthoritativeKnowledgeEntry, ...] | None = None,
    strict: bool = False,
) -> Tuple[SpecificationSourceInput, ...]:
    """Load only explicit manifest entries; invalid sources fail closed by omission."""

    root = repository_root or default_repository_root()
    timestamp = (loaded_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    selected = select_highest_authority(
        production_knowledge_manifest() if entries is None else entries
    )
    canonical_entries = tuple(_advisory_to_canonical(entry) for entry in selected)
    manifest = CanonicalKnowledgeManifest(
        name="advisor-authoritative-knowledge",
        entries=canonical_entries,
    )
    loader = CanonicalKnowledgeLoader(repository_root=root)
    try:
        result = loader.load(manifest, strict=strict)
    except CanonicalKnowledgeLoadError as exc:
        # Preserve the original strict-mode error contract (KnowledgeManifestError).
        if strict:
            raise KnowledgeManifestError(exc.code) from None
        raise
    return tuple(
        _document_to_source_input(document, loaded_at=timestamp)
        for document in result.verified_documents
    )
