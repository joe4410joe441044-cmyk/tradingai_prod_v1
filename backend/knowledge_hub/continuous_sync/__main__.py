"""Explicit CLI entry point. It never registers a daemon or timer."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from ..knowledge_store import KnowledgeStore, StoreError
from .models import SOURCE_KIND_REPORT_DIR, SOURCE_KIND_REPOSITORY, SyncLimits, SourceSpec
from .sync_engine import ContinuousSyncEngine


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Explicit TradingAI development-history sync")
    parser.add_argument("--store", required=True, help="SQLite knowledge store path")
    parser.add_argument("--repo", action="append", default=[], help="Allowlisted Git repository")
    parser.add_argument("--report-dir", action="append", default=[], help="Allowlisted report directory")
    parser.add_argument("--allow-repo-root", action="append", default=[], help="Repository allowlist root")
    parser.add_argument("--allow-worktree-root", action="append", default=[], help="Worktree allowlist root")
    parser.add_argument("--allow-report-root", action="append", default=[], help="Report allowlist root")
    parser.add_argument("--max-commits", type=int, default=50)
    parser.add_argument("--apply", action="store_true", help="Write records and checkpoints")
    parser.add_argument("--create-store", action="store_true", help="Create the store when absent")
    parser.add_argument("--indexed-at", default=None)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    sources = [SourceSpec(path=Path(item), kind=SOURCE_KIND_REPOSITORY) for item in args.repo]
    sources.extend(
        SourceSpec(
            path=Path(item),
            kind=SOURCE_KIND_REPORT_DIR,
            agent="CURSOR" if "cursor" in item.lower() else None,
        )
        for item in args.report_dir
    )
    limits = SyncLimits(
        max_commit_scan_depth=max(args.max_commits, 1),
        allowed_repository_roots=tuple(Path(item) for item in args.allow_repo_root),
        allowed_worktree_roots=tuple(Path(item) for item in args.allow_worktree_root),
        allowed_report_roots=(
            tuple(Path(item) for item in args.allow_report_root)
            if args.allow_report_root
            else SyncLimits().allowed_report_roots
        ),
    )
    engine = ContinuousSyncEngine(limits=limits)
    if not args.apply:
        preview = engine.preview(sources, store_path=args.store)
        print(json.dumps(preview.to_dict(), indent=2, sort_keys=True))
        return 0
    indexed_at = args.indexed_at or datetime.now(timezone.utc).isoformat()
    target = Path(args.store)
    try:
        if target.exists():
            store = KnowledgeStore.open(target)
        elif args.create_store:
            store = KnowledgeStore.create(target)
        else:
            print(json.dumps({"status": "ERROR", "error": "STORE_NOT_FOUND"}))
            return 2
    except StoreError as exc:
        print(json.dumps({"status": "ERROR", "error": exc.code}))
        return 2
    try:
        report = engine.sync(
            sources,
            store,
            store_path=target,
            indexed_at=indexed_at,
        )
    finally:
        store.close()
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.status in {"OK", "PARTIAL"} else 1


if __name__ == "__main__":
    sys.exit(main())
