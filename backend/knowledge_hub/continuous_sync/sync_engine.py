"""Explicit incremental sync of development history into the BC-3 store.

There is no daemon, timer, cron entry, or scheduler registration here. Every
scan is an explicit call. ``complete`` is never asserted, so a partial scan
cannot mark previously known records missing. Missing sources are recorded as
explicit observations instead.
"""

from __future__ import annotations

from pathlib import Path
import hashlib
import time

from ..config import CollectorConfig
from ..git_collector import default_git_runner
from ..knowledge_store import KnowledgeStore, StoreError, logical_key, version_id
from .git_change_detector import scan_repository
from .models import (
    SCAN_MISSING,
    SCAN_PARTIAL,
    SCAN_REJECTED,
    SOURCE_KIND_REPOSITORY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_PARTIAL,
    ExistingState,
    SourceScan,
    SourceSpec,
    SyncLimits,
    SyncReport,
)
from .normalizer import commit_item, item_size, report_item, worktree_item
from .report_scanner import scan_reports
from .sync_checkpoint import CheckpointStore, read_existing_state


def build_collector_config(limits: SyncLimits) -> CollectorConfig:
    return CollectorConfig(
        max_commits=max(limits.max_commit_scan_depth, 1),
        max_worktrees=max(limits.max_worktrees, 1),
        max_status_lines=50,
        max_report_files=max(limits.max_report_files, 1),
        max_file_bytes=max(limits.max_report_file_bytes, 1),
        timeout_seconds=limits.max_scan_seconds,
        git_timeout_seconds=limits.max_git_command_seconds,
        include_text=True,
    )


def scan_sources(
    sources,
    *,
    limits: SyncLimits,
    config: CollectorConfig,
    checkpoints: dict[tuple[str, str], dict] | None = None,
    known_commits: frozenset[str] = frozenset(),
    clock=None,
    runner=default_git_runner,
) -> tuple[SourceScan, ...]:
    results: list[SourceScan] = []
    repository_count = 0
    started = time.monotonic()
    for source in sources:
        if source.kind == SOURCE_KIND_REPOSITORY:
            if repository_count >= limits.max_repositories:
                results.append(
                    SourceScan(
                        source_id=source.source_id,
                        kind=source.kind,
                        status=SCAN_REJECTED,
                        error="SOURCE_LIMIT_REACHED",
                    )
                )
                continue
            repository_count += 1
            if limits.max_scan_seconds > 0 and time.monotonic() - started > limits.max_scan_seconds:
                results.append(
                    SourceScan(
                        source_id=source.source_id,
                        kind=source.kind,
                        status=SCAN_REJECTED,
                        error="SCAN_TIMEOUT",
                    )
                )
                continue
            checkpoint = (checkpoints or {}).get((source.kind, source.source_id))
            results.append(
                scan_repository(
                    source,
                    limits=limits,
                    config=config,
                    checkpoint=checkpoint,
                    known_commits=known_commits,
                    clock=clock,
                    runner=runner,
                )
            )
        elif source.kind == "REPORT_DIR":
            results.append(scan_reports(source, limits=limits, config=config, clock=clock))
        else:
            results.append(
                SourceScan(
                    source_id=source.source_id,
                    kind=str(source.kind),
                    status=SCAN_REJECTED,
                    error="SOURCE_KIND_REJECTED",
                )
            )
    return tuple(results)


def items_for_scan(scan: SourceScan, *, limits: SyncLimits) -> tuple:
    items = []
    for commit in scan.new_commits:
        item = commit_item(commit)
        if item is not None:
            items.append(item)
    for observation in scan.worktrees:
        item = worktree_item(observation)
        if item is not None:
            items.append(item)
    for candidate in scan.reports:
        item = report_item(candidate, max_content_bytes=limits.max_report_content_bytes)
        if item is not None:
            items.append(item)
    return tuple(items)


def _deduplicate(items: tuple) -> tuple:
    seen: set[str] = set()
    unique = []
    for item in items:
        key = logical_key(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return tuple(unique)


def _digest(item) -> str:
    return item.content_hash or hashlib.sha256(item.content.encode("utf-8")).hexdigest()


def _classify(items: tuple, existing: ExistingState) -> tuple[int, int, int, int]:
    new_count = updated_count = unchanged_count = 0
    growth = 0
    for item in items:
        record_id = version_id(item, _digest(item))
        if record_id in existing.record_ids:
            unchanged_count += 1
        elif logical_key(item) in existing.by_logical:
            updated_count += 1
            growth += item_size(item)
        else:
            new_count += 1
            growth += item_size(item)
    return new_count, updated_count, unchanged_count, growth


def _checkpoint_row(scan: SourceScan, previous: dict | None) -> dict:
    previous = previous or {}
    row = {
        "source_kind": scan.kind,
        "source_id": scan.source_id,
        "last_scan_at": previous.get("last_scan_at") or "",
        "branch": scan.branch or previous.get("branch"),
        "last_seen_commit": scan.head or previous.get("last_seen_commit"),
        "report_path": previous.get("report_path") or scan.source_id,
        "report_content_hash": previous.get("report_content_hash"),
        "last_imported_version": previous.get("last_imported_version"),
        "source_agent": previous.get("source_agent"),
    }
    if scan.kind != SOURCE_KIND_REPOSITORY:
        row["last_seen_commit"] = previous.get("last_seen_commit")
        agents = {candidate.source_agent for candidate in scan.reports}
        if agents:
            row["source_agent"] = sorted(agents)[0]
    return row


class ContinuousSyncEngine:
    def __init__(
        self,
        *,
        limits: SyncLimits | None = None,
        config: CollectorConfig | None = None,
        clock=None,
        runner=default_git_runner,
    ) -> None:
        self._limits = limits or SyncLimits()
        self._config = config or build_collector_config(self._limits)
        self._clock = clock
        self._runner = runner

    @property
    def limits(self) -> SyncLimits:
        return self._limits

    def preview(self, sources, *, store_path: str | Path):
        from .sync_preview import preview_sync

        return preview_sync(
            sources,
            store_path=store_path,
            limits=self._limits,
            config=self._config,
            clock=self._clock,
            runner=self._runner,
        )

    def sync(
        self,
        sources,
        store: KnowledgeStore,
        *,
        store_path: str | Path,
        indexed_at: str,
        scan_scope: str = "continuous-sync",
    ) -> SyncReport:
        if not indexed_at:
            return _error_report("TIMESTAMP_REQUIRED")
        if store_path is None or str(store_path) == "":
            return _error_report("STORE_PATH_REQUIRED")
        sources = tuple(sources)
        if not sources:
            return _error_report("SOURCE_REQUIRED")
        checkpoint_store = CheckpointStore.open(store_path)
        try:
            loaded = checkpoint_store.load_all()
            known = checkpoint_store.known_commits()
            scans = scan_sources(
                sources,
                limits=self._limits,
                config=self._config,
                checkpoints=loaded,
                known_commits=known,
                clock=self._clock,
                runner=self._runner,
            )
            existing = read_existing_state(store_path) or ExistingState(frozenset(), {})
            groups: list[tuple[SourceScan, tuple]] = []
            seen_keys: set[str] = set()
            for scan in scans:
                unique = []
                for item in _deduplicate(items_for_scan(scan, limits=self._limits)):
                    key = logical_key(item)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    unique.append(item)
                groups.append((scan, tuple(unique)))
            all_items = [item for _, items in groups for item in items]
            _, _, _, growth = _classify(tuple(all_items), existing)
            if growth > self._limits.max_database_growth_bytes:
                return _error_report("GROWTH_LIMIT_REACHED")

            inserted = skipped = superseded = missing = rejected = 0
            rejected_codes: list[str] = []
            errors: list[str] = []
            checkpoints: list[dict] = []
            ok_sources = 0
            for scan, items in groups:
                rejected += scan.rejected_count
                if scan.error is not None and scan.status in {SCAN_MISSING, SCAN_REJECTED}:
                    errors.append(f"{scan.source_id}:{scan.error}")
                if scan.status == SCAN_PARTIAL and scan.stopped_reason:
                    errors.append(f"{scan.source_id}:{scan.stopped_reason}")
                source_failed = False
                if scan.status == SCAN_REJECTED and not items:
                    source_failed = True
                for chunk in _chunks(items, self._limits.max_batch_size):
                    result = store.sync(
                        chunk,
                        indexed_at=indexed_at,
                        scan_scope=f"{scan_scope}:{scan.source_id}",
                        complete=False,
                    )
                    inserted += result.inserted
                    skipped += result.skipped
                    superseded += result.superseded
                    missing += result.missing
                    rejected += result.rejected
                    rejected_codes.extend(result.rejected_codes)
                    if result.error is not None:
                        source_failed = True
                        errors.append(f"{scan.source_id}:{result.error}")
                        break
                if not source_failed:
                    ok_sources += 1
                    row = _checkpoint_row(scan, loaded.get((scan.kind, scan.source_id)))
                    row["last_scan_at"] = indexed_at
                    row["last_imported_version"] = indexed_at
                    checkpoints.append(row)

            checkpoint_error = None
            try:
                checkpoint_store.save_many(tuple(checkpoints))
            except StoreError as exc:
                checkpoint_error = exc.code
                errors.append(f"CHECKPOINT:{exc.code}")
        finally:
            checkpoint_store.close()

        missing_sources = sum(1 for scan in scans if scan.status == SCAN_MISSING)
        rejected_sources = sum(1 for scan in scans if scan.status == SCAN_REJECTED)
        privacy = sum(scan.privacy_review_count for scan in scans)
        branch_changes = sum(1 for scan in scans if scan.branch_changed)
        history_rewrites = sum(1 for scan in scans if scan.history_rewrite_observed)
        commit_count = sum(len(scan.new_commits) for scan in scans)
        report_count = sum(len(scan.reports) for scan in scans)
        worktree_count = sum(len(scan.worktrees) for scan in scans)
        status = STATUS_OK
        if errors or missing_sources or rejected_sources or rejected:
            status = STATUS_PARTIAL
        if not ok_sources and errors and inserted == 0 and skipped == 0:
            status = STATUS_ERROR
        return SyncReport(
            status=status,
            source_count=len(scans),
            repository_count=sum(1 for scan in scans if scan.kind == SOURCE_KIND_REPOSITORY),
            worktree_count=worktree_count,
            commit_count=commit_count,
            report_count=report_count,
            inserted=inserted,
            skipped=skipped,
            superseded=superseded,
            missing=missing,
            rejected=rejected,
            missing_source_count=missing_sources,
            rejected_source_count=rejected_sources,
            privacy_review_count=privacy,
            branch_changes=branch_changes,
            history_rewrites=history_rewrites,
            checkpoints_updated=len(checkpoints) if checkpoint_error is None else 0,
            estimated_database_growth_bytes=growth,
            errors=tuple(errors),
            rejected_codes=tuple(rejected_codes),
        )


def _chunks(items: tuple, size: int) -> tuple[tuple, ...]:
    if not items:
        return ()
    bounded = max(size, 1)
    return tuple(items[index : index + bounded] for index in range(0, len(items), bounded))


def _error_report(error: str) -> SyncReport:
    return SyncReport(
        status=STATUS_ERROR,
        source_count=0,
        repository_count=0,
        worktree_count=0,
        commit_count=0,
        report_count=0,
        inserted=0,
        skipped=0,
        superseded=0,
        missing=0,
        rejected=0,
        missing_source_count=0,
        rejected_source_count=0,
        privacy_review_count=0,
        branch_changes=0,
        history_rewrites=0,
        checkpoints_updated=0,
        estimated_database_growth_bytes=0,
        errors=(error,),
    )
