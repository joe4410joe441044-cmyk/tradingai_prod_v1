#!/usr/bin/env python3
"""BC-11E-2 metadata-only cross-worktree report inventory.

This is a *read-only metadata* scan of the report-only directories inside the
sibling TradingAI git worktrees. It records filename, absolute path, extension,
size, and modification time only. Report bodies are never opened, read, decoded,
hashed, imported, or copied.

Only these worktree-relative report roots are inspected::

    docs/reports
    docs/opencode/reports
    reports
    tmp/reports
    tmp/chatgpt_reviews

No other directory is traversed. Symlinks are never followed. The canonical
main checkout and any non-worktree location are intentionally excluded.

A filename hint (for example ``cursor`` in the name) produces a *candidate*
classification only. It never confirms an authoring agent, so every candidate
stays ``approved=false`` and ``origin_confirmed=false``.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat as stat_module
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.knowledge_hub.config import DEFAULT_REPORT_ROOTS  # noqa: E402
from backend.knowledge_hub.security import secret_filename  # noqa: E402

INVENTORY_SCHEMA_VERSION = "tradingai-bc11e2-cross-worktree-inventory/v1"
ROOTS_SCHEMA_VERSION = "tradingai-bc11e2-worktree-report-roots/v1"
DUPLICATES_SCHEMA_VERSION = "tradingai-bc11e2-duplicate-candidates/v1"

WORKTREE_ROOT = Path("/home/joe4410joe/tradingai_prod_v1.worktrees")
CANONICAL_ROOT = Path("/home/joe4410joe/tradingai_prod_v1")

REPORT_ROOTS: tuple[str, ...] = (
    "docs/reports",
    "docs/opencode/reports",
    "reports",
    "tmp/reports",
    "tmp/chatgpt_reviews",
)

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".md", ".txt"})
CANDIDATE_EXTENSIONS: frozenset[str] = frozenset({".md", ".txt", ".json"})

CLASS_CURSOR = "CURSOR_REPORT_CANDIDATE"
CLASS_OTHER_AGENT = "OTHER_AGENT_REPORT_CANDIDATE"
CLASS_CHATGPT = "CHATGPT_REVIEW_CANDIDATE"
CLASS_UNKNOWN = "UNKNOWN_REPORT_CANDIDATE"
CLASS_EXCLUDED = "EXCLUDED"

CANDIDATE_CLASSES: tuple[str, ...] = (
    CLASS_CURSOR,
    CLASS_OTHER_AGENT,
    CLASS_CHATGPT,
    CLASS_UNKNOWN,
)

COVERAGE_COMPLETE = "COMPLETE_WITHIN_SCANNED_ROOTS"
COVERAGE_ADDITIONAL = "ADDITIONAL_SOURCE_ROOTS_REQUIRED"
COVERAGE_SCAN_LIMIT = "SCAN_LIMIT_REACHED"

DUP_EXACT_PATH = "EXACT_PATH_DUPLICATE"
DUP_POSSIBLE = "POSSIBLE_DUPLICATE"
DUP_NAME_COLLISION = "NAME_COLLISION"

DENY_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "venv",
        ".venv",
        "__pycache__",
        "dist",
        "build",
        "secrets",
        "credentials",
    }
)

OTHER_AGENT_HINTS: tuple[str, ...] = (
    "codex",
    "claude",
    "gemini",
    "copilot",
    "opencode",
    "aider",
    "cline",
    "windsurf",
)

MAX_DEPTH = 3
MAX_FILES_PER_ROOT = 5_000
MAX_TOTAL_FILES = 50_000
MAX_SECONDS_PER_ROOT = 30.0
MAX_TOTAL_SECONDS = 900.0

DEFAULT_OUTPUT_DIR = Path("/tmp/work_bc_audit")
INVENTORY_JSON_NAME = "BC11E2_CROSS_WORKTREE_INVENTORY.json"
INVENTORY_MD_NAME = "BC11E2_CROSS_WORKTREE_INVENTORY.md"
ROOTS_JSON_NAME = "BC11E2_WORKTREE_REPORT_ROOTS.json"
DUPLICATES_JSON_NAME = "BC11E2_DUPLICATE_CANDIDATES.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mtime_iso(stat_result: os.stat_result) -> str:
    return datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc).isoformat()


def _source_id(worktree_path: str | Path, root_rel: str, relative: str) -> str:
    material = (
        f"{Path(worktree_path).resolve(strict=False).as_posix()}"
        f"\x00{root_rel}\x00{relative}"
    ).encode("utf-8")
    return "xwsrc_" + hashlib.sha256(material).hexdigest()[:24]


def _group_id(kind: str, material: str) -> str:
    return f"{kind}:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _git_worktree_porcelain(cwd: str | Path | None = None) -> str:
    completed = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return completed.stdout


def parse_worktree_porcelain(
    text: str,
    worktree_root: str | Path = WORKTREE_ROOT,
    canonical_root: str | Path = CANONICAL_ROOT,
) -> list[dict]:
    """Return direct-child TradingAI worktrees from ``git worktree list`` output.

    Only worktrees whose path sits directly under ``worktree_root`` are kept.
    The canonical main checkout and every non-worktree location are dropped.
    """

    root = Path(worktree_root).resolve(strict=False)
    canonical = Path(canonical_root).resolve(strict=False)
    records: list[dict] = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        path: Path | None = None
        head = ""
        branch = ""
        detached = False
        prunable = False
        for line in block.splitlines():
            if line.startswith("worktree "):
                path = Path(line[len("worktree ") :].strip())
            elif line.startswith("HEAD "):
                head = line[len("HEAD ") :].strip()
            elif line.startswith("branch "):
                branch = line[len("branch ") :].strip()
            elif line.strip() == "detached":
                detached = True
            elif line.startswith("prunable"):
                prunable = True
        if path is None:
            continue
        resolved = path.resolve(strict=False)
        if resolved == canonical:
            continue
        if resolved.parent != root:
            continue
        if branch.startswith("refs/heads/"):
            branch = branch[len("refs/heads/") :]
        records.append(
            {
                "worktree_path": str(path),
                "branch": branch,
                "head": head,
                "detached": detached,
                "prunable": prunable,
                "exists": path.is_dir() and not path.is_symlink(),
            }
        )
    records.sort(key=lambda item: item["worktree_path"])
    return records


def _scan_root(
    root: Path,
    *,
    max_depth: int,
    max_files: int,
    max_seconds: float,
    deadline: float,
) -> tuple[list[Path], bool]:
    """Collect regular-file paths under ``root`` within the bounds.

    Symlinked directories are skipped and never followed. Hidden and deny-listed
    directories are pruned. The caller is responsible for filtering files.
    """

    collected: list[Path] = []
    limit_hit = False
    started = time.monotonic()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if time.monotonic() - started > max_seconds or time.monotonic() > deadline:
            limit_hit = True
            break
        current = Path(dirpath)
        try:
            depth = len(current.relative_to(root).parts)
        except ValueError:
            depth = max_depth
        kept_dirs: list[str] = []
        if depth < max_depth:
            for name in sorted(dirnames):
                child = current / name
                if child.is_symlink():
                    continue
                if name.startswith(".") or name.lower() in DENY_DIRECTORY_NAMES:
                    continue
                kept_dirs.append(name)
        dirnames[:] = kept_dirs
        for name in sorted(filenames):
            if len(collected) >= max_files:
                limit_hit = True
                break
            collected.append(current / name)
        if limit_hit:
            break
    return collected, limit_hit


def _classify(name: str, extension: str, root_rel: str) -> tuple[str, str]:
    """Provisional, metadata-only classification. Never confirms an origin."""

    if extension == ".json":
        return CLASS_UNKNOWN, "JSON_CONTENT_NOT_READ_REVIEW_REQUIRED"

    lowered = name.lower()
    if root_rel == "tmp/chatgpt_reviews" or "chatgpt" in lowered or "gpt" in lowered:
        return CLASS_CHATGPT, "CHATGPT_ROOT_OR_FILENAME_HINT"
    if "cursor" in lowered:
        return CLASS_CURSOR, "CURSOR_FILENAME_HINT"
    if any(hint in lowered for hint in OTHER_AGENT_HINTS):
        return CLASS_OTHER_AGENT, "OTHER_AGENT_FILENAME_HINT"
    if root_rel == "docs/opencode/reports":
        return CLASS_OTHER_AGENT, "OPENCODE_ROOT_HINT"
    return CLASS_UNKNOWN, "ORIGIN_UNCONFIRMED"


def _describe(path: Path, root: Path, root_rel: str, worktree: dict) -> dict:
    """Classify one path from metadata only. Never opens the file."""

    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.name

    entry = {
        "source_id": _source_id(worktree["worktree_path"], root_rel, relative),
        "absolute_path": str(path),
        "relative_path": relative,
        "filename": path.name,
        "extension": path.suffix.lower(),
        "size_bytes": None,
        "mtime": None,
        "source_root": str(root),
        "source_root_declared": root_rel,
        "worktree_path": worktree["worktree_path"],
        "branch": worktree["branch"],
        "head": worktree["head"],
        "classification": CLASS_EXCLUDED,
        "candidate_reason": "",
        "duplicate_group": None,
        "duplicate_kind": None,
        "report_content_read": False,
        "approved": False,
        "origin_confirmed": False,
        "requires_review": False,
        "exclusion_reason": None,
    }

    if path.is_symlink():
        entry["candidate_reason"] = "SYMLINK_REJECTED"
        entry["exclusion_reason"] = "SYMLINK_REJECTED"
        return entry

    if any(part.startswith(".") for part in Path(relative).parts):
        entry["candidate_reason"] = "HIDDEN_PATH_REJECTED"
        entry["exclusion_reason"] = "HIDDEN_PATH_REJECTED"
        return entry

    if secret_filename(path.name):
        entry["candidate_reason"] = "SECRET_FILENAME_REJECTED"
        entry["exclusion_reason"] = "SECRET_FILENAME_REJECTED"
        return entry

    try:
        stat_result = path.stat()
    except OSError:
        entry["candidate_reason"] = "STAT_FAILED"
        entry["exclusion_reason"] = "STAT_FAILED"
        return entry

    if not stat_module.S_ISREG(stat_result.st_mode):
        entry["candidate_reason"] = "NOT_REGULAR_FILE"
        entry["exclusion_reason"] = "NOT_REGULAR_FILE"
        return entry

    entry["size_bytes"] = stat_result.st_size
    entry["mtime"] = _mtime_iso(stat_result)

    extension = path.suffix.lower()
    if extension not in CANDIDATE_EXTENSIONS:
        entry["candidate_reason"] = "UNSUPPORTED_EXTENSION"
        entry["exclusion_reason"] = "UNSUPPORTED_EXTENSION"
        return entry

    classification, reason = _classify(path.name, extension, root_rel)
    entry["classification"] = classification
    entry["candidate_reason"] = reason
    entry["requires_review"] = True
    return entry


def _build_duplicate_groups(entries: list[dict]) -> list[dict]:
    """Detect metadata-only duplicate candidates. No content hash is computed."""

    candidates = [e for e in entries if e["classification"] != CLASS_EXCLUDED]

    exact: dict[str, list[dict]] = {}
    for entry in candidates:
        normalized = os.path.normpath(entry["absolute_path"])
        exact.setdefault(normalized, []).append(entry)

    possible: dict[tuple[str, object], list[dict]] = {}
    for entry in candidates:
        possible.setdefault((entry["filename"], entry["size_bytes"]), []).append(entry)

    name_only: dict[str, list[dict]] = {}
    for entry in candidates:
        name_only.setdefault(entry["filename"], []).append(entry)

    groups: list[dict] = []

    for normalized, members in sorted(exact.items()):
        if len(members) < 2:
            continue
        group_id = _group_id(DUP_EXACT_PATH, normalized)
        groups.append(
            {
                "duplicate_group": group_id,
                "duplicate_kind": DUP_EXACT_PATH,
                "filename": members[0]["filename"],
                "size_bytes": members[0]["size_bytes"],
                "member_count": len(members),
                "members": [
                    {
                        "source_id": m["source_id"],
                        "absolute_path": m["absolute_path"],
                        "worktree_path": m["worktree_path"],
                        "branch": m["branch"],
                        "head": m["head"],
                    }
                    for m in members
                ],
            }
        )

    for (filename, size_bytes), members in sorted(
        possible.items(), key=lambda item: (item[0][0], str(item[0][1]))
    ):
        distinct = {os.path.normpath(m["absolute_path"]) for m in members}
        if len(members) < 2 or len(distinct) < 2:
            continue
        group_id = _group_id(DUP_POSSIBLE, f"{filename}\x00{size_bytes}")
        groups.append(
            {
                "duplicate_group": group_id,
                "duplicate_kind": DUP_POSSIBLE,
                "filename": filename,
                "size_bytes": size_bytes,
                "member_count": len(members),
                "members": [
                    {
                        "source_id": m["source_id"],
                        "absolute_path": m["absolute_path"],
                        "worktree_path": m["worktree_path"],
                        "branch": m["branch"],
                        "head": m["head"],
                    }
                    for m in members
                ],
            }
        )

    for filename, members in sorted(name_only.items()):
        distinct = {os.path.normpath(m["absolute_path"]) for m in members}
        if len(members) < 2 or len(distinct) < 2:
            continue
        group_id = _group_id(DUP_NAME_COLLISION, filename)
        groups.append(
            {
                "duplicate_group": group_id,
                "duplicate_kind": DUP_NAME_COLLISION,
                "filename": filename,
                "size_bytes": None,
                "member_count": len(members),
                "members": [
                    {
                        "source_id": m["source_id"],
                        "absolute_path": m["absolute_path"],
                        "worktree_path": m["worktree_path"],
                        "branch": m["branch"],
                        "head": m["head"],
                    }
                    for m in members
                ],
            }
        )

    priority = {DUP_EXACT_PATH: 3, DUP_POSSIBLE: 2, DUP_NAME_COLLISION: 1}
    best: dict[str, dict] = {}
    for group in groups:
        for member in group["members"]:
            sid = member["source_id"]
            current = best.get(sid)
            if current is None or priority[group["duplicate_kind"]] > priority[
                current["duplicate_kind"]
            ]:
                best[sid] = group
    for entry in candidates:
        group = best.get(entry["source_id"])
        if group is not None:
            entry["duplicate_group"] = group["duplicate_group"]
            entry["duplicate_kind"] = group["duplicate_kind"]

    return groups


def _known_excluded_locations(canonical_root: Path) -> list[dict]:
    """Record known report-bearing locations that are out of scope for this scan."""

    locations: list[dict] = []
    if canonical_root.exists() and not canonical_root.is_symlink():
        locations.append(
            {
                "path": str(canonical_root),
                "reason": "CANONICAL_MAIN_EXCLUDED_BY_TASK",
                "scanned": False,
            }
        )
    for candidate in DEFAULT_REPORT_ROOTS:
        path = Path(candidate)
        if path.exists() and not path.is_symlink():
            locations.append(
                {
                    "path": str(path),
                    "reason": "OUTSIDE_DISCOVERY_ROOT",
                    "scanned": False,
                }
            )
    return locations


def run_cross_worktree_inventory(
    *,
    worktree_root: str | Path = WORKTREE_ROOT,
    canonical_root: str | Path = CANONICAL_ROOT,
    report_roots: tuple[str, ...] = REPORT_ROOTS,
    worktrees: list[dict] | None = None,
    porcelain_text: str | None = None,
    max_depth: int = MAX_DEPTH,
    max_files_per_root: int = MAX_FILES_PER_ROOT,
    max_total_files: int = MAX_TOTAL_FILES,
    max_seconds_per_root: float = MAX_SECONDS_PER_ROOT,
    max_total_seconds: float = MAX_TOTAL_SECONDS,
    generated_at: str | None = None,
) -> dict:
    """Build the metadata-only cross-worktree inventory payload.

    Does not write anything and never reads report content.
    """

    root = Path(worktree_root)
    canonical = Path(canonical_root)

    if worktrees is None:
        if porcelain_text is None:
            porcelain_text = _git_worktree_porcelain()
        worktrees = parse_worktree_porcelain(porcelain_text, root, canonical)

    worktree_records: list[dict] = []
    root_records: list[dict] = []
    entries: list[dict] = []
    errors: list[dict] = []
    scan_limit_reached_count = 0

    total_started = time.monotonic()
    total_deadline = total_started + max_total_seconds
    total_scanned = 0

    for worktree in sorted(worktrees, key=lambda item: item["worktree_path"]):
        worktree_path = Path(worktree["worktree_path"])
        exists = worktree_path.is_dir() and not worktree_path.is_symlink()
        record = {
            "worktree_path": worktree["worktree_path"],
            "branch": worktree.get("branch", ""),
            "head": worktree.get("head", ""),
            "detached": worktree.get("detached", False),
            "prunable": worktree.get("prunable", False),
            "exists": exists,
            "report_directories_found": [],
            "roots": [],
        }

        for root_rel in report_roots:
            path = worktree_path / root_rel
            is_symlink = path.is_symlink()
            is_dir = (not is_symlink) and path.is_dir()
            root_record = {
                "worktree_path": worktree["worktree_path"],
                "branch": worktree.get("branch", ""),
                "head": worktree.get("head", ""),
                "root": root_rel,
                "absolute_path": str(path),
                "exists": is_dir,
                "is_directory": is_dir,
                "is_symlink": is_symlink,
                "scanned": False,
                "file_count": 0,
                "scan_limit_reached": False,
                "error": None,
            }

            if not is_dir:
                record["roots"].append(root_record)
                root_records.append(root_record)
                continue

            record["report_directories_found"].append(root_rel)

            remaining = max_total_files - total_scanned
            if remaining <= 0:
                root_record["scan_limit_reached"] = True
                root_record["error"] = "SCAN_LIMIT_REACHED"
                scan_limit_reached_count += 1
                record["roots"].append(root_record)
                root_records.append(root_record)
                continue

            try:
                files, limit_hit = _scan_root(
                    path,
                    max_depth=max_depth,
                    max_files=min(max_files_per_root, remaining),
                    max_seconds=max_seconds_per_root,
                    deadline=total_deadline,
                )
            except OSError as exc:  # pragma: no cover - defensive
                root_record["error"] = type(exc).__name__
                errors.append(
                    {
                        "worktree_path": worktree["worktree_path"],
                        "root": root_rel,
                        "error": type(exc).__name__,
                    }
                )
                record["roots"].append(root_record)
                root_records.append(root_record)
                continue

            root_record["scanned"] = True
            root_record["file_count"] = len(files)
            total_scanned += len(files)
            if limit_hit:
                root_record["scan_limit_reached"] = True
                scan_limit_reached_count += 1

            for file_path in files:
                entries.append(_describe(file_path, path, root_rel, worktree))

            record["roots"].append(root_record)
            root_records.append(root_record)

        worktree_records.append(record)

    entries.sort(
        key=lambda item: (
            item["worktree_path"],
            item["source_root_declared"],
            item["relative_path"],
        )
    )

    duplicate_groups = _build_duplicate_groups(entries)

    candidate_entries = [e for e in entries if e["classification"] != CLASS_EXCLUDED]
    excluded_entries = [e for e in entries if e["classification"] == CLASS_EXCLUDED]

    def _count(cls: str) -> int:
        return sum(1 for e in candidate_entries if e["classification"] == cls)

    possible_duplicate_entries = [
        e for e in candidate_entries if e["duplicate_kind"] == DUP_POSSIBLE
    ]

    out_of_scope_locations = _known_excluded_locations(canonical)
    missing_roots = [
        item
        for item in root_records
        if item["error"] == "SCAN_LIMIT_REACHED" or item["error"] is not None
    ]

    # All approved worktree roots that exist were fully traversed within the
    # count/time bounds, so coverage within the scanned roots is complete. The
    # canonical main and external /tmp audit roots are intentionally out of
    # scope for this task and are reported separately.
    if scan_limit_reached_count > 0:
        coverage_status = COVERAGE_SCAN_LIMIT
    elif missing_roots:
        coverage_status = COVERAGE_ADDITIONAL
    else:
        coverage_status = COVERAGE_COMPLETE

    counts = {
        "WORKTREE_COUNT": len(worktree_records),
        "REPORT_ROOT_COUNT": sum(
            1 for item in root_records if item["is_directory"]
        ),
        "TOTAL_CANDIDATE_COUNT": len(candidate_entries),
        "CURSOR_REPORT_CANDIDATE_COUNT": _count(CLASS_CURSOR),
        "OTHER_AGENT_REPORT_CANDIDATE_COUNT": _count(CLASS_OTHER_AGENT),
        "CHATGPT_REVIEW_CANDIDATE_COUNT": _count(CLASS_CHATGPT),
        "UNKNOWN_REPORT_CANDIDATE_COUNT": _count(CLASS_UNKNOWN),
        "EXCLUDED_COUNT": len(excluded_entries),
        "POSSIBLE_DUPLICATE_COUNT": len(possible_duplicate_entries),
        "NAME_COLLISION_COUNT": sum(
            1 for e in candidate_entries if e["duplicate_kind"] == DUP_NAME_COLLISION
        ),
        "EXACT_PATH_DUPLICATE_COUNT": sum(
            1 for e in candidate_entries if e["duplicate_kind"] == DUP_EXACT_PATH
        ),
        "POSSIBLE_DUPLICATE_GROUP_COUNT": sum(
            1 for g in duplicate_groups if g["duplicate_kind"] == DUP_POSSIBLE
        ),
        "DUPLICATE_GROUP_COUNT": len(duplicate_groups),
        "SCAN_LIMIT_REACHED_COUNT": scan_limit_reached_count,
        "TOTAL_DISCOVERED_COUNT": len(entries),
        "TOTAL_SCANNED_FILES": total_scanned,
    }

    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "generated_at": generated_at or _now_iso(),
        "mode": "READ_ONLY_CROSS_WORKTREE_METADATA_DISCOVERY",
        "content_read": False,
        "real_import_executed": False,
        "discovery_root": str(root),
        "canonical_root_excluded": str(canonical),
        "approved_report_roots": list(report_roots),
        "max_depth": max_depth,
        "limits": {
            "max_files_per_root": max_files_per_root,
            "max_total_files": max_total_files,
            "max_seconds_per_root": max_seconds_per_root,
            "max_total_seconds": max_total_seconds,
        },
        "coverage_status": coverage_status,
        "coverage_scope": "WORKTREE_APPROVED_REPORT_ROOTS_ONLY",
        "full_history_asserted": False,
        "additional_source_roots_required": coverage_status
        in {COVERAGE_SCAN_LIMIT, COVERAGE_ADDITIONAL},
        "out_of_scope_locations": out_of_scope_locations,
        "errors": errors,
        "counts": counts,
        "safety": {
            "approved_true_count": sum(1 for e in entries if e["approved"]),
            "origin_confirmed_count": sum(1 for e in entries if e["origin_confirmed"]),
            "content_read_count": sum(
                1 for e in entries if e.get("report_content_read")
            ),
            "body_hash_computed": False,
            "body_text_stored": False,
        },
        "worktrees": worktree_records,
        "report_roots": root_records,
        "duplicate_groups": duplicate_groups,
        "entries": entries,
        "candidates": candidate_entries,
        "candidate_source_ids": [e["source_id"] for e in candidate_entries],
    }


def build_roots_payload(payload: dict) -> dict:
    return {
        "schema_version": ROOTS_SCHEMA_VERSION,
        "generated_at": payload["generated_at"],
        "discovery_root": payload["discovery_root"],
        "canonical_root_excluded": payload["canonical_root_excluded"],
        "approved_report_roots": payload["approved_report_roots"],
        "mode": payload["mode"],
        "content_read": False,
        "counts": {
            "WORKTREE_COUNT": payload["counts"]["WORKTREE_COUNT"],
            "REPORT_ROOT_COUNT": payload["counts"]["REPORT_ROOT_COUNT"],
        },
        "worktrees": payload["worktrees"],
        "report_roots": payload["report_roots"],
    }


def build_duplicates_payload(payload: dict) -> dict:
    return {
        "schema_version": DUPLICATES_SCHEMA_VERSION,
        "generated_at": payload["generated_at"],
        "mode": payload["mode"],
        "content_read": False,
        "hash_computed": False,
        "note": (
            "Metadata-only duplicate candidates. Content was not read or hashed, "
            "so no entry is a confirmed full duplicate."
        ),
        "counts": {
            "DUPLICATE_GROUP_COUNT": payload["counts"]["DUPLICATE_GROUP_COUNT"],
            "POSSIBLE_DUPLICATE_GROUP_COUNT": payload["counts"][
                "POSSIBLE_DUPLICATE_GROUP_COUNT"
            ],
            "POSSIBLE_DUPLICATE_COUNT": payload["counts"]["POSSIBLE_DUPLICATE_COUNT"],
            "NAME_COLLISION_COUNT": payload["counts"]["NAME_COLLISION_COUNT"],
            "EXACT_PATH_DUPLICATE_COUNT": payload["counts"]["EXACT_PATH_DUPLICATE_COUNT"],
        },
        "duplicate_groups": payload["duplicate_groups"],
    }


def _render_markdown(payload: dict) -> str:
    counts = payload["counts"]
    lines: list[str] = []
    lines.append("# BC-11E-2 Cross-Worktree Report Inventory (Metadata Only)")
    lines.append("")
    lines.append(f"- schema_version: `{payload['schema_version']}`")
    lines.append(f"- generated_at: `{payload['generated_at']}`")
    lines.append(f"- mode: `{payload['mode']}`")
    lines.append("- content_read: `False`")
    lines.append(f"- discovery_root: `{payload['discovery_root']}`")
    lines.append(f"- canonical_root_excluded: `{payload['canonical_root_excluded']}`")
    lines.append(f"- coverage_status: `{payload['coverage_status']}`")
    lines.append(f"- coverage_scope: `{payload['coverage_scope']}`")
    lines.append(f"- full_history_asserted: `{payload['full_history_asserted']}`")
    lines.append(
        f"- additional_source_roots_required: `{payload['additional_source_roots_required']}`"
    )
    lines.append("")
    lines.append("## Counts")
    lines.append("")
    for key in (
        "WORKTREE_COUNT",
        "REPORT_ROOT_COUNT",
        "TOTAL_CANDIDATE_COUNT",
        "CURSOR_REPORT_CANDIDATE_COUNT",
        "OTHER_AGENT_REPORT_CANDIDATE_COUNT",
        "CHATGPT_REVIEW_CANDIDATE_COUNT",
        "UNKNOWN_REPORT_CANDIDATE_COUNT",
        "EXCLUDED_COUNT",
        "POSSIBLE_DUPLICATE_COUNT",
        "NAME_COLLISION_COUNT",
        "SCAN_LIMIT_REACHED_COUNT",
        "TOTAL_DISCOVERED_COUNT",
    ):
        lines.append(f"- {key}: {counts[key]}")
    lines.append("")
    lines.append("## Approved report roots (per worktree)")
    lines.append("")
    for root_rel in payload["approved_report_roots"]:
        lines.append(f"- `{root_rel}`")
    lines.append("")
    lines.append("## Candidate classification counts")
    lines.append("")
    for cls in CANDIDATE_CLASSES:
        count_key = {
            CLASS_CURSOR: "CURSOR_REPORT_CANDIDATE_COUNT",
            CLASS_OTHER_AGENT: "OTHER_AGENT_REPORT_CANDIDATE_COUNT",
            CLASS_CHATGPT: "CHATGPT_REVIEW_CANDIDATE_COUNT",
            CLASS_UNKNOWN: "UNKNOWN_REPORT_CANDIDATE_COUNT",
        }[cls]
        lines.append(f"- {cls}: {counts[count_key]}")
    lines.append("")
    lines.append("## Out-of-scope locations (not scanned)")
    lines.append("")
    for item in payload["out_of_scope_locations"]:
        lines.append(f"- `{item['path']}` ({item['reason']})")
    if not payload["out_of_scope_locations"]:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Top-level candidates by worktree")
    lines.append("")
    by_worktree: dict[str, int] = {}
    for entry in payload["candidates"]:
        by_worktree[entry["worktree_path"]] = by_worktree.get(entry["worktree_path"], 0) + 1
    for worktree_path, count in sorted(by_worktree.items()):
        lines.append(f"- `{worktree_path}`: {count}")
    if not by_worktree:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Safety")
    lines.append("")
    lines.append("- Report body text was not read, decoded, hashed, or stored.")
    lines.append("- No entry is approved; no entry has a confirmed origin.")
    lines.append(f"- approved_true_count: {payload['safety']['approved_true_count']}")
    lines.append(f"- origin_confirmed_count: {payload['safety']['origin_confirmed_count']}")
    lines.append(
        "- Duplicate candidates are metadata-only and are not confirmed full duplicates."
    )
    lines.append("- Coverage applies only to the scanned roots; full history is not asserted.")
    lines.append("")
    return "\n".join(lines)


def write_outputs(payload: dict, output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> dict:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)

    inventory_json = target / INVENTORY_JSON_NAME
    inventory_md = target / INVENTORY_MD_NAME
    roots_json = target / ROOTS_JSON_NAME
    duplicates_json = target / DUPLICATES_JSON_NAME

    inventory_json.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    inventory_md.write_text(_render_markdown(payload) + "\n", encoding="utf-8")
    roots_json.write_text(
        json.dumps(build_roots_payload(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    duplicates_json.write_text(
        json.dumps(build_duplicates_payload(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "inventory_json": str(inventory_json),
        "inventory_md": str(inventory_md),
        "worktree_report_roots": str(roots_json),
        "duplicate_candidates": str(duplicates_json),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree-root", default=str(WORKTREE_ROOT))
    parser.add_argument("--canonical-root", default=str(CANONICAL_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--max-depth", type=int, default=MAX_DEPTH)
    parser.add_argument("--max-files-per-root", type=int, default=MAX_FILES_PER_ROOT)
    parser.add_argument("--max-total-files", type=int, default=MAX_TOTAL_FILES)
    return parser


def _main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = run_cross_worktree_inventory(
        worktree_root=args.worktree_root,
        canonical_root=args.canonical_root,
        max_depth=args.max_depth,
        max_files_per_root=args.max_files_per_root,
        max_total_files=args.max_total_files,
        generated_at=args.generated_at or None,
    )
    paths = write_outputs(payload, args.output_dir)
    summary = {
        "WORKTREE_COUNT": payload["counts"]["WORKTREE_COUNT"],
        "REPORT_ROOT_COUNT": payload["counts"]["REPORT_ROOT_COUNT"],
        "TOTAL_CANDIDATE_COUNT": payload["counts"]["TOTAL_CANDIDATE_COUNT"],
        "CURSOR_REPORT_CANDIDATE_COUNT": payload["counts"]["CURSOR_REPORT_CANDIDATE_COUNT"],
        "OTHER_AGENT_REPORT_CANDIDATE_COUNT": payload["counts"][
            "OTHER_AGENT_REPORT_CANDIDATE_COUNT"
        ],
        "CHATGPT_REVIEW_CANDIDATE_COUNT": payload["counts"][
            "CHATGPT_REVIEW_CANDIDATE_COUNT"
        ],
        "UNKNOWN_REPORT_CANDIDATE_COUNT": payload["counts"]["UNKNOWN_REPORT_CANDIDATE_COUNT"],
        "EXCLUDED_COUNT": payload["counts"]["EXCLUDED_COUNT"],
        "POSSIBLE_DUPLICATE_COUNT": payload["counts"]["POSSIBLE_DUPLICATE_COUNT"],
        "SCAN_LIMIT_REACHED_COUNT": payload["counts"]["SCAN_LIMIT_REACHED_COUNT"],
        "COVERAGE_STATUS": payload["coverage_status"],
        "outputs": paths,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
