"""Allowlisted explicit report scanning.

Cursor and VS Code private chat databases are never opened. Only files in a
caller-allowlisted report directory are parsed, and the existing BC-2 report
collector does the parsing and secret filtering.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ..config import CollectorConfig
from ..provenance import stamp
from ..report_collector import collect_reports
from ..security import directory_inside
from .models import (
    AGENT_CURSOR,
    AGENT_EXPLICIT,
    AGENT_VSCODE,
    REPORT_PRIVACY_STATUSES,
    SCAN_OK,
    SCAN_REJECTED,
    SOURCE_KIND_REPORT_DIR,
    ReportCandidate,
    SourceScan,
    SyncLimits,
)


def _agent_for(source, relative_path: str) -> str:
    declared = (source.agent or "").upper()
    if declared in {AGENT_CURSOR, AGENT_VSCODE}:
        return declared
    lowered = relative_path.lower()
    if "cursor" in lowered:
        return AGENT_CURSOR
    if "vscode" in lowered or "vs_code" in lowered or "vs-code" in lowered:
        return AGENT_VSCODE
    return AGENT_EXPLICIT


def validate_report_directory(path: Path, limits: SyncLimits) -> str | None:
    requested = Path(path)
    if requested.is_symlink():
        return "SYMLINK_REJECTED"
    if not requested.exists() or not requested.is_dir():
        return "SOURCE_NOT_FOUND"
    if not limits.allowed_report_roots:
        return "REPORT_ROOT_REQUIRED"
    if not any(directory_inside(requested, root) for root in limits.allowed_report_roots):
        return "REPORT_ROOT_NOT_ALLOWLISTED"
    return None


def scan_reports(
    source,
    *,
    limits: SyncLimits,
    config: CollectorConfig,
    clock=None,
) -> SourceScan:
    observed_at = stamp(clock or (lambda: datetime.now(timezone.utc)))
    directory = Path(source.path)
    code = validate_report_directory(directory, limits)
    if code is not None:
        return SourceScan(
            source_id=source.source_id,
            kind=SOURCE_KIND_REPORT_DIR,
            status=SCAN_REJECTED,
            error=code,
        )
    batch = collect_reports(
        (directory,),
        allowed_roots=limits.allowed_report_roots,
        config=config,
        clock=clock,
    )
    if batch.error is not None and not batch.records:
        return SourceScan(
            source_id=source.source_id,
            kind=SOURCE_KIND_REPORT_DIR,
            status=SCAN_REJECTED,
            error=batch.error,
        )
    candidates: list[ReportCandidate] = []
    privacy = 0
    rejected = 0
    for record in batch.records:
        provenance = record.provenance
        relative = provenance.relative_path or provenance.source_identifier
        agent = _agent_for(source, relative)
        fields = dict(record.fields or {})
        candidate = ReportCandidate(
            path=directory / relative,
            relative_path=relative,
            source_agent=agent,
            status=record.collection_status,
            fields=fields,
            content_hash=provenance.content_hash,
            size_bytes=record.size_bytes,
            text=record.text,
            observed_at=observed_at,
        )
        candidates.append(candidate)
        if record.collection_status in REPORT_PRIVACY_STATUSES:
            privacy += 1
        if record.collection_status not in {"METADATA_ONLY", "TEXT_INCLUDED", "UNSUPPORTED_ENCODING"}:
            rejected += 1
    status = SCAN_OK if batch.error is None else "PARTIAL"
    return SourceScan(
        source_id=source.source_id,
        kind=SOURCE_KIND_REPORT_DIR,
        status=status,
        error=batch.error,
        reports=tuple(candidates),
        privacy_review_count=privacy,
        rejected_count=rejected,
        stopped_reason=batch.stopped_reason,
    )
