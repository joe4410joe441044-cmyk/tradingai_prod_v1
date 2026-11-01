"""Adapt BC-2 collector batches into store items.

The collectors are called only by the explicit ``ingest_collection`` path.
A failed or partial batch is stored without marking absent records missing.
Report text and source comments stay data. They are not executed.
"""

from __future__ import annotations

from .knowledge_store import KnowledgeStore, StoreItem, SyncResult
from .models import CollectionBatch, KnowledgeRecord
from .security import secret_bytes, secret_filename


_KEEP = frozenset({"METADATA_ONLY", "TEXT_INCLUDED", "UNSUPPORTED_ENCODING"})
_TRUTH = frozenset(
    {
        "SOURCE_TRUTH",
        "PROJECT_TRUTH",
        "HISTORICAL_CONTEXT",
        "AGENT_REPORTED",
        "GIT_VERIFIED",
        "UNKNOWN",
    }
)


def _content(record: KnowledgeRecord) -> str | None:
    if record.text:
        return record.text
    fields = record.fields or {}
    parts = []
    for key in sorted(fields):
        value = fields[key]
        if not value or value == "UNKNOWN":
            continue
        parts.append(f"{key}: {value}")
    if record.provenance.relative_path:
        parts.append(record.provenance.relative_path)
    text = "\n".join(parts).strip()
    return text or None


def adapt_record(record: KnowledgeRecord) -> StoreItem | None:
    if record.collection_status not in _KEEP:
        return None
    provenance = record.provenance
    leaf = (provenance.relative_path or provenance.source_identifier).rsplit("/", 1)[-1]
    if secret_filename(leaf):
        return None
    content = _content(record)
    if content is None or secret_bytes(content.encode("utf-8")):
        return None
    title = provenance.relative_path or provenance.source_identifier
    if secret_bytes(title.encode("utf-8")):
        return None
    truth = provenance.truth_kind if provenance.truth_kind in _TRUTH else "UNKNOWN"
    fields = record.fields or {}
    workstream = fields.get("WORKSTREAM")
    if workstream in {None, "", "UNKNOWN"}:
        workstream = None
    return StoreItem(
        source_type=provenance.source_type,
        source_identifier=provenance.source_identifier,
        record_type=provenance.record_type,
        title=title[:300],
        content=content,
        content_hash=provenance.content_hash,
        collected_at=provenance.collected_at,
        verification_state=provenance.verification_state or "UNVERIFIED",
        truth_kind=truth,
        relative_path=provenance.relative_path,
        commit_sha=provenance.commit_sha,
        branch=provenance.branch,
        worktree=provenance.worktree,
        reported_at=provenance.reported_at,
        observed_at=provenance.observed_at,
        source_timestamp=provenance.source_timestamp,
        workstream=workstream,
        metadata={"collection_status": record.collection_status},
    )


def ingest_collection(
    store: KnowledgeStore,
    batch: CollectionBatch,
    *,
    indexed_at: str,
    scan_scope: str,
) -> SyncResult:
    """Persist one explicit collector result.

    ``batch.error`` and ``batch.stopped_reason`` mean the scan is partial.
    Partial scans never mark records missing.
    """

    items = []
    rejected = 0
    for record in batch.records:
        item = adapt_record(record)
        if item is None:
            rejected += 1
            continue
        items.append(item)
    complete = batch.error is None and batch.stopped_reason is None
    result = store.sync(items, indexed_at=indexed_at, scan_scope=scan_scope, complete=complete)
    if rejected and result.error is None:
        return SyncResult(
            inserted=result.inserted,
            skipped=result.skipped,
            superseded=result.superseded,
            missing=result.missing,
            rejected=result.rejected + rejected,
            error=result.error,
            rejected_codes=result.rejected_codes + ("COLLECTOR_EXCLUDED",) * rejected,
        )
    return result
