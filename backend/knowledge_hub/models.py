"""Value objects returned by the collectors.

A successful read is not a claim that the bytes are runtime truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Provenance:
    schema_version: str
    source_type: str
    source_identifier: str
    collected_at: str
    content_hash: str | None
    verification_state: str
    authority_scope: str
    record_type: str
    truth_kind: str
    relative_path: str | None = None
    commit_sha: str | None = None
    branch: str | None = None
    worktree: str | None = None
    reported_at: str | None = None
    observed_at: str | None = None
    source_timestamp: str | None = None
    superseded_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_type": self.source_type,
            "source_identifier": self.source_identifier,
            "collected_at": self.collected_at,
            "content_hash": self.content_hash,
            "verification_state": self.verification_state,
            "authority_scope": self.authority_scope,
            "record_type": self.record_type,
            "truth_kind": self.truth_kind,
            "relative_path": self.relative_path,
            "commit_sha": self.commit_sha,
            "branch": self.branch,
            "worktree": self.worktree,
            "reported_at": self.reported_at,
            "observed_at": self.observed_at,
            "source_timestamp": self.source_timestamp,
            "superseded_by": self.superseded_by,
        }


@dataclass(frozen=True)
class KnowledgeRecord:
    provenance: Provenance
    collection_status: str
    size_bytes: int | None = None
    modified_at: str | None = None
    text: str | None = None
    fields: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "provenance": self.provenance.to_dict(),
            "collection_status": self.collection_status,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
            "fields": dict(self.fields or {}),
        }
        if self.text is not None:
            body["text"] = self.text
        return body


@dataclass(frozen=True)
class CollectionBatch:
    records: tuple[KnowledgeRecord, ...]
    stopped_reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [record.to_dict() for record in self.records],
            "stopped_reason": self.stopped_reason,
            "error": self.error,
        }
