"""Dry-run preview of a continuous sync.

The preview opens the store read-only. It never creates a database, a table,
a checkpoint row, or a knowledge record. Raw report text is not returned.
"""

from __future__ import annotations

from pathlib import Path
import hashlib

from ..config import CollectorConfig
from ..git_collector import default_git_runner
from ..knowledge_store import logical_key, version_id
from .models import (
    SCAN_MISSING,
    SCAN_REJECTED,
    SOURCE_KIND_REPOSITORY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_PARTIAL,
    ExistingState,
    SyncLimits,
    SyncPreview,
)
from .normalizer import item_size
from .sync_checkpoint import read_checkpoints, read_existing_state, read_known_commits
from .sync_engine import build_collector_config, items_for_scan, scan_sources


def preview_sync(
    sources,
    *,
    store_path: str | Path,
    limits: SyncLimits | None = None,
    config: CollectorConfig | None = None,
    clock=None,
    runner=default_git_runner,
) -> SyncPreview:
    settings = limits or SyncLimits()
    collector = config or build_collector_config(settings)
    sources = tuple(sources)
    if not sources:
        return _empty_preview(STATUS_ERROR, "SOURCE_REQUIRED")
    existing = read_existing_state(store_path) or ExistingState(frozenset(), {})
    checkpoints = read_checkpoints(store_path)
    known = read_known_commits(store_path)
    scans = scan_sources(
        sources,
        limits=settings,
        config=collector,
        checkpoints=checkpoints,
        known_commits=known,
        clock=clock,
        runner=runner,
    )
    seen_keys: set[str] = set()
    new_count = updated_count = unchanged_count = 0
    growth = 0
    entries: list[dict] = []
    for scan in scans:
        for item in items_for_scan(scan, limits=settings):
            key = logical_key(item)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            digest = item.content_hash
            if not digest:
                digest = hashlib.sha256(item.content.encode("utf-8")).hexdigest()
            record_id = version_id(item, digest)
            if record_id in existing.record_ids:
                unchanged_count += 1
                state = "UNCHANGED"
            elif key in existing.by_logical:
                updated_count += 1
                growth += item_size(item)
                state = "UPDATED"
            else:
                new_count += 1
                growth += item_size(item)
                state = "NEW"
            if len(entries) < settings.max_preview_entries:
                entries.append(
                    {
                        "source_id": scan.source_id,
                        "record_type": item.record_type,
                        "source_type": item.source_type,
                        "title": item.title,
                        "state": state,
                    }
                )
    missing_sources = sum(1 for scan in scans if scan.status == SCAN_MISSING)
    rejected_sources = sum(1 for scan in scans if scan.status == SCAN_REJECTED)
    privacy = sum(scan.privacy_review_count for scan in scans)
    rejected_items = sum(scan.rejected_count for scan in scans)
    status = STATUS_OK
    if missing_sources or rejected_sources or rejected_items or any(scan.error for scan in scans):
        status = STATUS_PARTIAL
    if not scans or all(scan.status == SCAN_REJECTED for scan in scans):
        status = STATUS_ERROR if rejected_sources else status
    return SyncPreview(
        status=status,
        source_count=len(scans),
        repository_count=sum(1 for scan in scans if scan.kind == SOURCE_KIND_REPOSITORY),
        worktree_count=sum(len(scan.worktrees) for scan in scans),
        commit_candidate_count=sum(len(scan.commits) for scan in scans),
        report_candidate_count=sum(len(scan.reports) for scan in scans),
        new_record_count=new_count,
        updated_record_count=updated_count,
        unchanged_record_count=unchanged_count,
        missing_source_count=missing_sources,
        rejected_source_count=rejected_sources,
        privacy_review_count=privacy,
        estimated_database_growth_bytes=growth,
        entries=tuple(entries),
    )


def _empty_preview(status: str, error: str) -> SyncPreview:
    return SyncPreview(
        status=status,
        source_count=0,
        repository_count=0,
        worktree_count=0,
        commit_candidate_count=0,
        report_candidate_count=0,
        new_record_count=0,
        updated_record_count=0,
        unchanged_record_count=0,
        missing_source_count=0,
        rejected_source_count=0,
        privacy_review_count=0,
        estimated_database_growth_bytes=0,
        entries=(),
        error=error,
    )
