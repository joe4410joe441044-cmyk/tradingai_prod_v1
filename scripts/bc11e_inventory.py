#!/usr/bin/env python3
"""BC-11E metadata-only inventory of saved Cursor Agent work reports.

The inventory records only file-system metadata: filename, absolute path,
extension, size, and modification time. Report bodies are never opened, read,
decoded, hashed, or imported. Only the report roots that the existing BC
collector already approves are traversed; every other location is at most
existence-checked and is never scanned.

A ``BC*.md`` filename is a *filename match candidate only*. It is never proof
that Cursor created the file, so every entry stays ``approved=false`` and
requires operator review. The manifest produced here is an unapproved candidate
list and must not be handed to a real import.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.knowledge_hub.config import DEFAULT_REPORT_ROOTS  # noqa: E402
from backend.knowledge_hub.security import directory_inside, secret_filename  # noqa: E402

INVENTORY_SCHEMA_VERSION = "tradingai-bc11e-cursor-report-inventory/v1"
MANIFEST_SCHEMA_VERSION = "tradingai-bc11e-cursor-report-manifest-candidate/v1"

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".md", ".txt"})

CLASS_FILENAME_MATCH = "FILENAME_MATCH_CANDIDATE"
CLASS_REVIEW_REQUIRED = "REVIEW_REQUIRED"
CLASS_EXCLUDED = "EXCLUDED"

COVERAGE_COMPLETE = "COMPLETE_WITHIN_APPROVED_ROOTS"
COVERAGE_ADDITIONAL = "ADDITIONAL_SOURCE_ROOTS_REQUIRED"

CANDIDATE_FILENAME = re.compile(r"^BC.*\.(?:md|txt)$", re.IGNORECASE)

DENY_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "dist",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".env",
    }
)

DEFAULT_ADDITIONAL_CANDIDATE_ROOTS: tuple[str, ...] = (
    "docs/reports",
    "docs/opencode/reports",
)

DEFAULT_OUTPUT_DIR = Path("/tmp/work_bc_audit")
INVENTORY_JSON_NAME = "BC11E_CURSOR_REPORT_INVENTORY.json"
INVENTORY_MD_NAME = "BC11E_CURSOR_REPORT_INVENTORY.md"
MANIFEST_NAME = "BC11E_CURSOR_REPORT_MANIFEST_CANDIDATE.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_id(root: Path, relative: str) -> str:
    material = f"{root.as_posix()}\x00{relative}".encode("utf-8")
    return "crsrc_" + hashlib.sha256(material).hexdigest()[:24]


def _mtime_iso(stat_result: os.stat_result) -> str:
    return datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc).isoformat()


def _root_is_approved(root: Path, allowed_roots: tuple[Path, ...]) -> bool:
    if root.is_symlink():
        return False
    return any(directory_inside(root, allowed) for allowed in allowed_roots)


def _iter_paths(root: Path):
    """Yield paths beneath ``root`` without following or yielding symlinks."""

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        kept_dirs = []
        for name in sorted(dirnames):
            child = current / name
            if child.is_symlink():
                continue
            if name.startswith(".") or name in DENY_DIRECTORY_NAMES:
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs
        for name in sorted(filenames):
            yield current / name


def _empty_entry(path: Path, root: Path, relative: str) -> dict:
    return {
        "source_id": _source_id(root, relative),
        "absolute_path": str(path),
        "filename": path.name,
        "extension": path.suffix.lower(),
        "size_bytes": None,
        "mtime": None,
        "source_root": str(root),
        "relative_path": relative,
        "candidate_reason": "",
        "classification": CLASS_EXCLUDED,
        "approved": False,
        "origin_confirmed": False,
        "requires_review": False,
        "exclusion_reason": None,
    }


def _describe(path: Path, root: Path) -> dict:
    """Classify one path using metadata only. Never opens the file."""

    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.name
    entry = _empty_entry(path, root, relative)

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

    entry["size_bytes"] = stat_result.st_size
    entry["mtime"] = _mtime_iso(stat_result)

    if not path.is_file():
        entry["candidate_reason"] = "NOT_A_FILE"
        entry["exclusion_reason"] = "NOT_A_FILE"
        return entry

    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        entry["candidate_reason"] = "UNSUPPORTED_EXTENSION"
        entry["exclusion_reason"] = "UNSUPPORTED_EXTENSION"
        return entry

    if CANDIDATE_FILENAME.match(path.name):
        entry["classification"] = CLASS_FILENAME_MATCH
        entry["candidate_reason"] = "FILENAME_MATCH_BC_PREFIX"
    else:
        entry["classification"] = CLASS_REVIEW_REQUIRED
        entry["candidate_reason"] = "SUPPORTED_EXTENSION_ORIGIN_UNCONFIRMED"

    # Filename match alone never confirms the Cursor origin, so the entry is
    # always review-required and always unapproved at the inventory stage.
    entry["requires_review"] = True
    entry["approved"] = False
    entry["origin_confirmed"] = False
    return entry


def _additional_root_status(
    worktree_root: Path,
    candidates: tuple[str, ...],
) -> list[dict]:
    """Existence-check additional roots only. Never list or scan their files."""

    status: list[dict] = []
    for candidate in candidates:
        path = (worktree_root / candidate) if not os.path.isabs(candidate) else Path(candidate)
        exists = path.exists() and not path.is_symlink()
        is_dir = bool(exists and path.is_dir())
        status.append(
            {
                "root": str(path),
                "declared": candidate,
                "exists": exists,
                "is_directory": is_dir,
                "scanned": False,
                "check": "EXISTENCE_ONLY",
            }
        )
    return status


def run_inventory(
    *,
    scan_roots: tuple[str | Path, ...] | None = None,
    allowed_roots: tuple[str | Path, ...] | None = None,
    additional_candidate_roots: tuple[str, ...] | None = None,
    worktree_root: str | Path | None = None,
    generated_at: str | None = None,
) -> dict:
    """Build the metadata-only inventory payload. Does not write anything."""

    allowed = tuple(Path(item) for item in (allowed_roots if allowed_roots is not None else DEFAULT_REPORT_ROOTS))
    requested_scan = tuple(
        Path(item) for item in (scan_roots if scan_roots is not None else DEFAULT_REPORT_ROOTS)
    )
    root_base = Path(worktree_root) if worktree_root is not None else ROOT
    candidate_roots = (
        additional_candidate_roots
        if additional_candidate_roots is not None
        else DEFAULT_ADDITIONAL_CANDIDATE_ROOTS
    )

    accepted_roots: list[Path] = []
    rejected_roots: list[dict] = []
    for root in requested_scan:
        if root.is_symlink() or not root.is_dir():
            rejected_roots.append({"root": str(root), "reason": "ROOT_NOT_FOUND_OR_SYMLINK"})
            continue
        if not _root_is_approved(root, allowed):
            rejected_roots.append({"root": str(root), "reason": "ROOT_NOT_ALLOWLISTED"})
            continue
        accepted_roots.append(root)

    entries: list[dict] = []
    for root in accepted_roots:
        for path in _iter_paths(root):
            entries.append(_describe(path, root))

    entries.sort(key=lambda item: (item["source_root"], item["relative_path"]))

    filename_match = [e for e in entries if e["classification"] == CLASS_FILENAME_MATCH]
    review_required = [e for e in entries if e["classification"] == CLASS_REVIEW_REQUIRED]
    excluded = [e for e in entries if e["classification"] == CLASS_EXCLUDED]
    candidates = filename_match + review_required

    additional_status = _additional_root_status(root_base, candidate_roots)

    approved_not_scanned = [
        str(root)
        for root in allowed
        if root.is_dir()
        and not root.is_symlink()
        and all(root.resolve(strict=False) != scanned.resolve(strict=False) for scanned in accepted_roots)
    ]

    additional_source_roots: list[str] = []
    for item in additional_status:
        if item["exists"]:
            additional_source_roots.append(item["root"])
    additional_source_roots.extend(approved_not_scanned)

    coverage_status = COVERAGE_ADDITIONAL if additional_source_roots else COVERAGE_COMPLETE

    counts = {
        "CANDIDATE_COUNT": len(candidates),
        "FILENAME_MATCH_COUNT": len(filename_match),
        "REVIEW_REQUIRED_COUNT": len(review_required),
        "EXCLUDED_COUNT": len(excluded),
        "TOTAL_DISCOVERED_COUNT": len(entries),
    }

    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "generated_at": generated_at or _now_iso(),
        "mode": "METADATA_ONLY",
        "content_read": False,
        "real_import_executed": False,
        "approved_roots": [str(item) for item in allowed],
        "scanned_roots": [str(item) for item in accepted_roots],
        "rejected_roots": rejected_roots,
        "additional_candidate_roots": additional_status,
        "additional_source_roots": additional_source_roots,
        "coverage_status": coverage_status,
        "counts": counts,
        "safety": {
            "approved_true_count": sum(1 for e in entries if e["approved"]),
            "origin_confirmed_count": sum(1 for e in entries if e["origin_confirmed"]),
            "body_hash_computed": False,
            "body_text_stored": False,
        },
        "entries": entries,
        "candidates": candidates,
        "candidate_source_ids": [e["source_id"] for e in candidates],
    }


def build_manifest_candidate(payload: dict) -> dict:
    """Wrap the candidate list as an explicitly unapproved manifest."""

    candidates = payload["candidates"]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": payload["generated_at"],
        "inventory_schema_version": payload["schema_version"],
        "manifest_kind": "MANIFEST_CANDIDATE",
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "operator_review_required": True,
        "note": (
            "Unapproved candidate inventory. Filename matches do not confirm a "
            "Cursor Agent origin. Do not pass this manifest to a real import."
        ),
        "counts": dict(payload["counts"]),
        "coverage_status": payload["coverage_status"],
        "candidates": [
            {
                "source_id": entry["source_id"],
                "absolute_path": entry["absolute_path"],
                "filename": entry["filename"],
                "extension": entry["extension"],
                "size_bytes": entry["size_bytes"],
                "mtime": entry["mtime"],
                "source_root": entry["source_root"],
                "classification": entry["classification"],
                "candidate_reason": entry["candidate_reason"],
                "approved": False,
                "origin_confirmed": False,
                "requires_review": True,
            }
            for entry in candidates
        ],
    }


def _render_markdown(payload: dict) -> str:
    counts = payload["counts"]
    lines: list[str] = []
    lines.append("# BC-11E Cursor Report Inventory (Metadata Only)")
    lines.append("")
    lines.append(f"- schema_version: `{payload['schema_version']}`")
    lines.append(f"- generated_at: `{payload['generated_at']}`")
    lines.append(f"- mode: `{payload['mode']}`")
    lines.append(f"- content_read: `{payload['content_read']}`")
    lines.append(f"- coverage_status: `{payload['coverage_status']}`")
    lines.append("")
    lines.append("## Counts")
    lines.append("")
    for key in (
        "CANDIDATE_COUNT",
        "FILENAME_MATCH_COUNT",
        "REVIEW_REQUIRED_COUNT",
        "EXCLUDED_COUNT",
        "TOTAL_DISCOVERED_COUNT",
    ):
        lines.append(f"- {key}: {counts[key]}")
    lines.append("")
    lines.append("## Roots")
    lines.append("")
    lines.append(f"- approved_roots: {payload['approved_roots']}")
    lines.append(f"- scanned_roots: {payload['scanned_roots']}")
    lines.append(f"- rejected_roots: {payload['rejected_roots']}")
    lines.append("")
    lines.append("### Additional candidate roots (existence check only, not scanned)")
    lines.append("")
    for item in payload["additional_candidate_roots"]:
        lines.append(
            f"- `{item['root']}` exists={item['exists']} is_directory={item['is_directory']} scanned={item['scanned']}"
        )
    if not payload["additional_candidate_roots"]:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Candidates")
    lines.append("")
    lines.append("| classification | filename | size_bytes | mtime | source_root | reason |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for entry in payload["candidates"]:
        lines.append(
            "| {classification} | {filename} | {size} | {mtime} | {root} | {reason} |".format(
                classification=entry["classification"],
                filename=entry["filename"],
                size=entry["size_bytes"],
                mtime=entry["mtime"],
                root=entry["source_root"],
                reason=entry["candidate_reason"],
            )
        )
    if not payload["candidates"]:
        lines.append("| (none) | - | - | - | - | - |")
    lines.append("")
    lines.append("## Excluded")
    lines.append("")
    if payload["entries"]:
        for entry in payload["entries"]:
            if entry["classification"] != CLASS_EXCLUDED:
                continue
            lines.append(
                f"- `{entry['filename']}` ({entry['exclusion_reason']}) under `{entry['source_root']}`"
            )
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Safety")
    lines.append("")
    lines.append("- Report body text was not read, decoded, hashed, or stored.")
    lines.append("- No entry is approved; no entry has a confirmed Cursor origin.")
    lines.append(f"- approved_true_count: {payload['safety']['approved_true_count']}")
    lines.append(f"- origin_confirmed_count: {payload['safety']['origin_confirmed_count']}")
    lines.append("- The manifest candidate is unapproved and must not be used for a real import.")
    lines.append("")
    return "\n".join(lines)


def write_outputs(payload: dict, output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> dict:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    inventory_json = target / INVENTORY_JSON_NAME
    inventory_md = target / INVENTORY_MD_NAME
    manifest_json = target / MANIFEST_NAME

    inventory_json.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    inventory_md.write_text(_render_markdown(payload) + "\n", encoding="utf-8")
    manifest = build_manifest_candidate(payload)
    manifest_json.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "inventory_json": str(inventory_json),
        "inventory_md": str(inventory_md),
        "manifest_candidate": str(manifest_json),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scan-root",
        action="append",
        default=[],
        help="Report root to scan. Must sit inside an approved root. Defaults to the approved roots.",
    )
    parser.add_argument(
        "--allowed-root",
        action="append",
        default=[],
        help="Approved report root boundary. Defaults to the BC collector allowlist.",
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--generated-at", default="")
    return parser


def _main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    allowed = tuple(args.allowed_root) if args.allowed_root else None
    scan = tuple(args.scan_root) if args.scan_root else None
    payload = run_inventory(
        scan_roots=scan,
        allowed_roots=allowed,
        generated_at=args.generated_at or None,
    )
    paths = write_outputs(payload, args.output_dir)
    summary = {
        "CANDIDATE_COUNT": payload["counts"]["CANDIDATE_COUNT"],
        "FILENAME_MATCH_COUNT": payload["counts"]["FILENAME_MATCH_COUNT"],
        "REVIEW_REQUIRED_COUNT": payload["counts"]["REVIEW_REQUIRED_COUNT"],
        "EXCLUDED_COUNT": payload["counts"]["EXCLUDED_COUNT"],
        "COVERAGE_STATUS": payload["coverage_status"],
        "outputs": paths,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
