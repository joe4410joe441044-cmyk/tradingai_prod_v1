"""Static, versioned, local-only knowledge allowlist."""

import hashlib
import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal, Optional, Tuple

from pydantic import Field, field_validator

from backend.ai_advisor.context_builder import sanitize_text
from backend.ai_advisor.conversation_models import AdvisorContractModel

MAX_APPROVED_SOURCE_BYTES = 262_144
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")


class ApprovedKnowledgeSourceType(str, Enum):
    NORMATIVE_SPECIFICATION = "NORMATIVE_SPECIFICATION"
    APPROVED_PROJECT_DOCUMENT = "APPROVED_PROJECT_DOCUMENT"


class ApprovedKnowledgeAuthority(str, Enum):
    NORMATIVE = "NORMATIVE"
    APPROVED_REFERENCE = "APPROVED_REFERENCE"


class ApprovedKnowledgeFreshness(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ApprovedKnowledgeSource(AdvisorContractModel):
    sourceId: Annotated[str, Field(min_length=1, max_length=128)]
    sourceType: ApprovedKnowledgeSourceType
    displayTitle: Annotated[str, Field(min_length=1, max_length=256)]
    documentId: Annotated[str, Field(min_length=1, max_length=128)]
    version: Annotated[str, Field(min_length=1, max_length=64)]
    authority: ApprovedKnowledgeAuthority
    contentHash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    approvedRootId: Annotated[str, Field(min_length=1, max_length=64)]
    relativePath: Annotated[str, Field(min_length=1, max_length=256)]
    freshnessKind: Literal[ApprovedKnowledgeFreshness.NOT_APPLICABLE]
    sourceTime: Optional[datetime] = None
    loadedAt: datetime
    externalTransmissionAllowed: Literal[False] = False
    committedAtHead: Literal[True] = True

    @field_validator("relativePath")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or value != path.as_posix():
            raise ValueError("source path must be canonical and relative")
        return value


class ApprovedKnowledgePolicy(AdvisorContractModel):
    retrievalEnabled: bool = False
    externalContextTransmissionAllowed: Literal[False] = False
    maximumFileBytes: int = Field(
        default=MAX_APPROVED_SOURCE_BYTES,
        ge=1,
        le=MAX_APPROVED_SOURCE_BYTES,
    )


class ApprovedKnowledgeExcerpt(AdvisorContractModel):
    source: ApprovedKnowledgeSource
    excerpt: Annotated[str, Field(min_length=1, max_length=8_000)]
    instructionBoundary: Literal["UNTRUSTED_SOURCE_DATA_ONLY"] = (
        "UNTRUSTED_SOURCE_DATA_ONLY"
    )


class KnowledgeSourceError(ValueError):
    def __init__(self, code: str):
        super().__init__("approved source is unavailable")
        self.code = code


class ApprovedKnowledgeRegistry:
    """Immutable manifest registry; no repository search or network access."""

    def __init__(
        self,
        *,
        approved_roots: dict[str, Path],
        sources: Tuple[ApprovedKnowledgeSource, ...],
        policy: ApprovedKnowledgePolicy = ApprovedKnowledgePolicy(),
    ):
        self._roots = dict(approved_roots)
        self._sources = {source.sourceId: source for source in sources}
        if len(self._sources) != len(sources):
            raise ValueError("source IDs must be unique")
        identities = {}
        for source in sources:
            key = (source.documentId, source.version)
            previous = identities.get(key)
            if previous is not None and previous != source.contentHash:
                raise KnowledgeSourceError("SOURCE_CONFLICT")
            identities[key] = source.contentHash
        self._policy = policy

    @property
    def policy(self) -> ApprovedKnowledgePolicy:
        return self._policy

    def load(self, source_id: str) -> ApprovedKnowledgeExcerpt:
        if self._policy.retrievalEnabled is not True:
            raise KnowledgeSourceError("KNOWLEDGE_RETRIEVAL_DISABLED")
        source = self._sources.get(source_id)
        if source is None:
            raise KnowledgeSourceError("UNKNOWN_SOURCE")
        root = self._roots.get(source.approvedRootId)
        if root is None:
            raise KnowledgeSourceError("UNAPPROVED_ROOT")
        root = root.resolve(strict=True)
        candidate = root / source.relativePath
        if candidate.is_symlink():
            raise KnowledgeSourceError("SYMLINK_REJECTED")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (FileNotFoundError, ValueError):
            raise KnowledgeSourceError("SOURCE_NOT_AVAILABLE") from None
        stat = resolved.stat()
        if not resolved.is_file() or stat.st_size > self._policy.maximumFileBytes:
            raise KnowledgeSourceError("SOURCE_NOT_ELIGIBLE")
        content = resolved.read_bytes()
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if digest != source.contentHash or not _HASH.fullmatch(digest):
            raise KnowledgeSourceError("HASH_OR_COMMIT_MISMATCH")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise KnowledgeSourceError("SOURCE_ENCODING_INVALID") from None
        cleaned = sanitize_text(text)
        if cleaned.sensitiveRemoved or cleaned.pathRemoved:
            raise KnowledgeSourceError("SENSITIVE_DATA_BLOCKED")
        if cleaned.injectionRemoved:
            raise KnowledgeSourceError("PROMPT_INJECTION_SUSPECTED")
        excerpt = cleaned.value[:8_000].strip()
        if not excerpt:
            raise KnowledgeSourceError("SOURCE_EMPTY")
        return ApprovedKnowledgeExcerpt(source=source, excerpt=excerpt)
