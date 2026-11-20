#!/usr/bin/env python3
"""BC-11E-3 metadata-only consolidation of historical agent report candidates.

This module merges the BC-11E-1 Cursor report inventory and the BC-11E-2
cross-worktree inventory into one unified candidate schema. It performs only
metadata work:

* reads the two already-produced inventory JSON files,
* normalises their candidate records,
* existence-checks each recorded source with ``os.stat`` only,
* groups metadata-only duplicate candidates,
* selects a review-only representative per duplicate group,
* writes unapproved review artefacts.

Report bodies are never opened, read, decoded, hashed, or imported. No real
import is invoked. Nothing is written outside the requested output directory.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.knowledge_hub.security import secret_filename  # noqa: E402

UNIFIED_SCHEMA_VERSION = "tradingai-bc11e3-unified-inventory/v1"
DUPLICATE_SCHEMA_VERSION = "tradingai-bc11e3-duplicate-review/v1"
QUEUE_SCHEMA_VERSION = "tradingai-bc11e3-review-queues/v1"
MANIFEST_SCHEMA_VERSION = "tradingai-bc11e3-import-manifest-candidate/v1"

DEFAULT_OUTPUT_DIR = Path("/tmp/work_bc_audit")
DEFAULT_BC11E1_PATH = DEFAULT_OUTPUT_DIR / "BC11E_CURSOR_REPORT_INVENTORY.json"
DEFAULT_BC11E2_PATH = DEFAULT_OUTPUT_DIR / "BC11E2_CROSS_WORKTREE_INVENTORY.json"

UNIFIED_JSON_NAME = "BC11E3_UNIFIED_INVENTORY.json"
DUPLICATE_JSON_NAME = "BC11E3_DUPLICATE_REVIEW.json"
QUEUES_JSON_NAME = "BC11E3_REVIEW_QUEUES.json"
MANIFEST_JSON_NAME = "BC11E3_IMPORT_MANIFEST_CANDIDATE.json"
SUMMARY_MD_NAME = "BC11E3_CANDIDATE_SUMMARY.md"

ORIGIN_BC11E1 = "BC11E1"
ORIGIN_BC11E2 = "BC11E2"

CLASS_CURSOR = "CURSOR_CANDIDATE"
CLASS_OTHER_AGENT = "OTHER_AGENT_CANDIDATE"
CLASS_CHATGPT = "CHATGPT_CANDIDATE"
CLASS_UNKNOWN = "UNKNOWN_CANDIDATE"
CLASS_OUT_OF_SCOPE = "OUT_OF_SCOPE_CANDIDATE"
CLASS_EXCLUDED = "EXCLUDED"

PROVENANCE_CONFIRMED_CURSOR = "CONFIRMED_CURSOR"
PROVENANCE_CONFIRMED_OTHER_AGENT = "CONFIRMED_OTHER_AGENT"
PROVENANCE_CONFIRMED_CHATGPT = "CONFIRMED_CHATGPT"
PROVENANCE_UNKNOWN = "UNKNOWN"

DUP_EXACT_PATH = "EXACT_PATH_DUPLICATE"
DUP_POSSIBLE = "POSSIBLE_DUPLICATE"
DUP_NAME_COLLISION = "NAME_COLLISION"
DUP_UNIQUE = "UNIQUE_METADATA"

SELECTION_REPRESENTATIVE = "REPRESENTATIVE_REVIEW_ONLY"
SELECTION_HOLD = "HOLD_UNVERIFIED_NOT_DEDUPLICATED"
SELECTION_UNIQUE = "UNIQUE_REVIEW_ONLY"

APPROVAL_UNAPPROVED = "UNAPPROVED"

SOURCE_PRESENT = "SOURCE_PRESENT"
SOURCE_MISSING = "SOURCE_MISSING"
SOURCE_CHANGED = "SOURCE_CHANGED_SINCE_INVENTORY"

COVERAGE_COMPLETE = "COMPLETE_WITHIN_SCANNED_ROOTS"
COVERAGE_ADDITIONAL = "ADDITIONAL_SOURCE_ROOTS_REQUIRED"

INPUTS_VALID = "INPUTS_VALID"
INPUT_COUNT_MISMATCH = "INPUT_COUNT_MISMATCH"
MISSING_INPUT = "MISSING_INPUT"
INVALID_INPUT = "INVALID_INPUT"

EXPECTED_BC11E1 = {
    "CANDIDATE_COUNT": 111,
    "FILENAME_MATCH_COUNT": 31,
    "REVIEW_REQUIRED_COUNT": 80,
    "EXCLUDED_COUNT": 26,
}

EXPECTED_BC11E2 = {
    "WORKTREE_COUNT": 242,
    "REPORT_ROOT_COUNT": 538,
    "TOTAL_CANDIDATE_COUNT": 6535,
    "CURSOR_REPORT_CANDIDATE_COUNT": 0,
    "OTHER_AGENT_REPORT_CANDIDATE_COUNT": 242,
    "CHATGPT_REVIEW_CANDIDATE_COUNT": 353,
    "UNKNOWN_REPORT_CANDIDATE_COUNT": 5940,
    "EXCLUDED_COUNT": 11,
    "POSSIBLE_DUPLICATE_COUNT": 6174,
    "SCAN_LIMIT_REACHED_COUNT": 0,
}

REQUIRED_CANDIDATE_FIELDS = (
    "source_id",
    "absolute_path",
    "filename",
    "extension",
    "size_bytes",
    "mtime",
    "source_root",
    "classification",
    "candidate_reason",
)

_E1_CLASSIFICATION_MAP = {
    "FILENAME_MATCH_CANDIDATE": CLASS_CURSOR,
    "REVIEW_REQUIRED": CLASS_UNKNOWN,
    "EXCLUDED": CLASS_EXCLUDED,
}

_E2_CLASSIFICATION_MAP = {
    "CURSOR_REPORT_CANDIDATE": CLASS_CURSOR,
    "OTHER_AGENT_REPORT_CANDIDATE": CLASS_OTHER_AGENT,
    "CHATGPT_REVIEW_CANDIDATE": CLASS_CHATGPT,
    "UNKNOWN_REPORT_CANDIDATE": CLASS_UNKNOWN,
    "EXCLUDED": CLASS_EXCLUDED,
}

_TASK_OUT_OF_SCOPE = "OUT_OF_SCOPE_CANDIDATE"


class InputError(Exception):
    """A required input is missing or structurally invalid."""

    def __init__(self, code: str, path: str, detail: str) -> None:
        super().__init__(f"{code}: {path}: {detail}")
        self.code = code
        self.path = path
        self.detail = detail


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mtime_iso(stat_result: os.stat_result) -> str:
    return datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc).isoformat()


def _group_id(kind: str, material: str) -> str:
    return f"{kind}:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _norm(path: str) -> str:
    return os.path.normpath(path)


def load_input(path: str | Path) -> dict:
    """Load one inventory JSON. Raises InputError on missing/invalid input."""

    target = Path(path)
    if not target.exists():
        raise InputError(MISSING_INPUT, str(target), "file does not exist")
    if not target.is_file():
        raise InputError(INVALID_INPUT, str(target), "not a regular file")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(INVALID_INPUT, str(target), type(exc).__name__) from None
    validate_input(payload, origin=str(target))
    return payload


def validate_input(payload: object, *, origin: str) -> None:
    """Reject an inventory payload that is not a usable candidate inventory."""

    if not isinstance(payload, dict):
        raise InputError(INVALID_INPUT, origin, "top-level JSON is not an object")
    candidates = payload.get("candidates")
    counts = payload.get("counts")
    if not isinstance(candidates, list):
        raise InputError(INVALID_INPUT, origin, "candidates is not a list")
    if not isinstance(counts, dict):
        raise InputError(INVALID_INPUT, origin, "counts is not an object")
    if not isinstance(payload.get("entries", []), list):
        raise InputError(INVALID_INPUT, origin, "entries is not a list")
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise InputError(INVALID_INPUT, origin, f"candidate {index} is not an object")
        missing = [key for key in REQUIRED_CANDIDATE_FIELDS if key not in candidate]
        if missing:
            raise InputError(
                INVALID_INPUT,
                origin,
                f"candidate {index} missing fields: {','.join(missing)}",
            )


def reconcile_inputs(
    bc11e1: dict,
    bc11e2: dict,
    *,
    expected_bc11e1: dict | None = None,
    expected_bc11e2: dict | None = None,
) -> dict:
    """Compare actual inventory counts with the recorded baseline counts."""

    expected1 = EXPECTED_BC11E1 if expected_bc11e1 is None else expected_bc11e1
    expected2 = EXPECTED_BC11E2 if expected_bc11e2 is None else expected_bc11e2

    def _compare(name: str, payload: dict, expected: dict) -> dict:
        actual_counts = payload.get("counts", {})
        comparisons = []
        for key, expected_value in expected.items():
            actual_value = actual_counts.get(key)
            comparisons.append(
                {
                    "key": key,
                    "expected": expected_value,
                    "actual": actual_value,
                    "match": actual_value == expected_value,
                }
            )
        return {"name": name, "comparisons": comparisons}

    bc11e1_result = _compare(ORIGIN_BC11E1, bc11e1, expected1)
    bc11e2_result = _compare(ORIGIN_BC11E2, bc11e2, expected2)

    mismatches: list[dict] = []
    for block in (bc11e1_result, bc11e2_result):
        for item in block["comparisons"]:
            if not item["match"]:
                mismatches.append({"inventory_origin": block["name"], **item})

    candidate_lengths = {
        ORIGIN_BC11E1: len(bc11e1.get("candidates", [])),
        ORIGIN_BC11E2: len(bc11e2.get("candidates", [])),
    }
    declared_lengths = {
        ORIGIN_BC11E1: bc11e1.get("counts", {}).get("CANDIDATE_COUNT"),
        ORIGIN_BC11E2: bc11e2.get("counts", {}).get("TOTAL_CANDIDATE_COUNT"),
    }
    for origin in (ORIGIN_BC11E1, ORIGIN_BC11E2):
        if candidate_lengths[origin] != declared_lengths[origin]:
            mismatches.append(
                {
                    "inventory_origin": origin,
                    "key": "CANDIDATE_LIST_LENGTH",
                    "expected": declared_lengths[origin],
                    "actual": candidate_lengths[origin],
                    "match": False,
                }
            )

    status = INPUTS_VALID if not mismatches else INPUT_COUNT_MISMATCH
    return {
        "status": status,
        "inputs_valid": not mismatches,
        "mismatches": mismatches,
        "candidate_list_lengths": candidate_lengths,
        "bc11e1": bc11e1_result,
        "bc11e2": bc11e2_result,
    }


def _classification_basis(
    origin: str, source_classification: str, candidate_reason: str
) -> list[str]:
    basis = [
        f"inventory_origin:{origin}",
        f"source_classification:{source_classification}",
    ]
    if candidate_reason:
        basis.append(f"candidate_reason:{candidate_reason}")
    return basis


def _provenance_status(origin_confirmed: bool, classification: str) -> str:
    if not origin_confirmed:
        return PROVENANCE_UNKNOWN
    if classification == CLASS_CURSOR:
        return PROVENANCE_CONFIRMED_CURSOR
    if classification == CLASS_OTHER_AGENT:
        return PROVENANCE_CONFIRMED_OTHER_AGENT
    if classification == CLASS_CHATGPT:
        return PROVENANCE_CONFIRMED_CHATGPT
    return PROVENANCE_UNKNOWN


def _normalise_bc11e1(candidate: dict) -> dict:
    source_classification = str(candidate.get("classification", ""))
    classification = _E1_CLASSIFICATION_MAP.get(source_classification, CLASS_UNKNOWN)
    origin_confirmed = bool(candidate.get("origin_confirmed", False))
    return {
        "source_id": candidate["source_id"],
        "absolute_path": candidate["absolute_path"],
        "filename": candidate["filename"],
        "extension": candidate["extension"],
        "size_bytes": candidate["size_bytes"],
        "mtime": candidate["mtime"],
        "source_root": candidate["source_root"],
        "worktree_path": str(candidate.get("worktree_path") or ""),
        "branch": str(candidate.get("branch") or ""),
        "head": str(candidate.get("head") or ""),
        "inventory_origin": ORIGIN_BC11E1,
        "source_classification": source_classification,
        "classification": classification,
        "candidate_reason": str(candidate.get("candidate_reason", "")),
        "classification_basis": _classification_basis(
            ORIGIN_BC11E1,
            source_classification,
            str(candidate.get("candidate_reason", "")),
        ),
        "provenance_status": _provenance_status(origin_confirmed, classification),
        "origin_confirmed": origin_confirmed,
        "requires_review": True,
        "duplicate_group": None,
        "duplicate_kind": None,
        "selection_status": SELECTION_UNIQUE,
        "approval_status": APPROVAL_UNAPPROVED,
        "approved": False,
        "source_status": None,
        "source_size_bytes": None,
        "source_mtime": None,
    }


def _normalise_bc11e2(candidate: dict) -> dict:
    source_classification = str(candidate.get("classification", ""))
    classification = _E2_CLASSIFICATION_MAP.get(source_classification, CLASS_UNKNOWN)
    origin_confirmed = bool(candidate.get("origin_confirmed", False))
    return {
        "source_id": candidate["source_id"],
        "absolute_path": candidate["absolute_path"],
        "filename": candidate["filename"],
        "extension": candidate["extension"],
        "size_bytes": candidate["size_bytes"],
        "mtime": candidate["mtime"],
        "source_root": candidate["source_root"],
        "worktree_path": str(candidate.get("worktree_path") or ""),
        "branch": str(candidate.get("branch") or ""),
        "head": str(candidate.get("head") or ""),
        "inventory_origin": ORIGIN_BC11E2,
        "source_classification": source_classification,
        "classification": classification,
        "candidate_reason": str(candidate.get("candidate_reason", "")),
        "classification_basis": _classification_basis(
            ORIGIN_BC11E2,
            source_classification,
            str(candidate.get("candidate_reason", "")),
        ),
        "provenance_status": _provenance_status(origin_confirmed, classification),
        "origin_confirmed": origin_confirmed,
        "requires_review": True,
        "duplicate_group": None,
        "duplicate_kind": None,
        "selection_status": SELECTION_UNIQUE,
        "approval_status": APPROVAL_UNAPPROVED,
        "approved": False,
        "source_status": None,
        "source_size_bytes": None,
        "source_mtime": None,
    }


def _check_source(entry: dict, stat_func) -> None:
    """Existence/stat check only. Never opens or reads the source file."""

    try:
        stat_result = stat_func(entry["absolute_path"])
    except OSError:
        entry["source_status"] = SOURCE_MISSING
        return
    entry["source_size_bytes"] = stat_result.st_size
    entry["source_mtime"] = _mtime_iso(stat_result)
    if (
        entry["size_bytes"] is not None
        and stat_result.st_size != entry["size_bytes"]
    ) or (
        entry["mtime"] is not None
        and entry["source_mtime"] != entry["mtime"]
    ):
        entry["source_status"] = SOURCE_CHANGED
    else:
        entry["source_status"] = SOURCE_PRESENT


def _build_duplicate_groups(candidates: list[dict]) -> list[dict]:
    """Build metadata-only duplicate groups. No source content is hashed."""

    exact: dict[str, list[dict]] = {}
    possible: dict[tuple[str, object], list[dict]] = {}
    name_only: dict[str, list[dict]] = {}

    for entry in candidates:
        exact.setdefault(_norm(entry["absolute_path"]), []).append(entry)
        possible.setdefault((entry["filename"], entry["size_bytes"]), []).append(entry)
        name_only.setdefault(entry["filename"], []).append(entry)

    groups: list[dict] = []

    for normalized, members in sorted(exact.items()):
        if len(members) < 2:
            continue
        groups.append(
            _group_record(
                DUP_EXACT_PATH,
                _group_id(DUP_EXACT_PATH, normalized),
                members[0]["filename"],
                members[0]["size_bytes"],
                members,
            )
        )

    for (filename, size_bytes), members in sorted(
        possible.items(), key=lambda item: (item[0][0], str(item[0][1]))
    ):
        distinct = {_norm(m["absolute_path"]) for m in members}
        if len(members) < 2 or len(distinct) < 2:
            continue
        groups.append(
            _group_record(
                DUP_POSSIBLE,
                _group_id(DUP_POSSIBLE, f"{filename}\x00{size_bytes}"),
                filename,
                size_bytes,
                members,
            )
        )

    for filename, members in sorted(name_only.items()):
        distinct = {_norm(m["absolute_path"]) for m in members}
        if len(members) < 2 or len(distinct) < 2:
            continue
        groups.append(
            _group_record(
                DUP_NAME_COLLISION,
                _group_id(DUP_NAME_COLLISION, filename),
                filename,
                None,
                members,
            )
        )

    priority = {DUP_EXACT_PATH: 3, DUP_POSSIBLE: 2, DUP_NAME_COLLISION: 1}
    best: dict[str, dict] = {}
    for group in groups:
        for member in group["members"]:
            source_id = member["source_id"]
            current = best.get(source_id)
            if current is None or priority[group["duplicate_kind"]] > priority[
                current["duplicate_kind"]
            ]:
                best[source_id] = group

    for entry in candidates:
        group = best.get(entry["source_id"])
        if group is not None:
            entry["duplicate_group"] = group["duplicate_group"]
            entry["duplicate_kind"] = group["duplicate_kind"]

    groups.sort(key=lambda item: item["duplicate_group"])
    return groups


def _group_record(
    kind: str,
    group_id: str,
    filename: str,
    size_bytes: object,
    members: list[dict],
) -> dict:
    return {
        "duplicate_group": group_id,
        "duplicate_kind": kind,
        "filename": filename,
        "size_bytes": size_bytes,
        "member_count": len(members),
        "members": sorted(members, key=lambda m: (m["absolute_path"], m["source_id"])),
    }


def _is_bc_root(source_root: str) -> bool:
    return _norm(source_root) == "/tmp/work_bc_audit"


def _representative_key(entry: dict) -> tuple:
    return (
        0 if _is_bc_root(entry["source_root"]) else 1,
        0 if entry["source_status"] != SOURCE_MISSING else 1,
        0 if entry["worktree_path"] else 1,
        entry["absolute_path"],
        entry["source_id"],
    )


def _select_representatives(
    candidates: list[dict], groups: list[dict]
) -> list[dict]:
    """Pick one review representative per group; keep every member."""

    by_id = {entry["source_id"]: entry for entry in candidates}
    review_groups: list[dict] = []
    for group in groups:
        ordered = sorted(group["members"], key=_representative_key)
        representative = ordered[0]
        representative_id = representative["source_id"]
        for member in group["members"]:
            entry = by_id[member["source_id"]]
            if entry["source_id"] == representative_id:
                entry["selection_status"] = SELECTION_REPRESENTATIVE
            else:
                entry["selection_status"] = SELECTION_HOLD
        review_groups.append(
            {
                "duplicate_group": group["duplicate_group"],
                "duplicate_kind": group["duplicate_kind"],
                "filename": group["filename"],
                "size_bytes": group["size_bytes"],
                "member_count": group["member_count"],
                "representative_source_id": representative_id,
                "representative_path": representative["absolute_path"],
                "members": [
                    {
                        "source_id": member["source_id"],
                        "absolute_path": member["absolute_path"],
                        "source_root": member["source_root"],
                        "worktree_path": member["worktree_path"],
                        "inventory_origin": member["inventory_origin"],
                        "classification": member["classification"],
                        "provenance_status": member["provenance_status"],
                        "source_status": member["source_status"],
                        "selection_status": member["selection_status"],
                        "size_bytes": member["size_bytes"],
                        "mtime": member["mtime"],
                    }
                    for member in ordered
                ],
                "deduplication_confirmed": False,
                "note": (
                    "Same name/size is metadata evidence only. Content was not "
                    "read or hashed. Every member is retained as a hold candidate."
                ),
            }
        )
    return review_groups


def _queue_item(entry: dict) -> dict:
    return {
        "source_id": entry["source_id"],
        "absolute_path": entry["absolute_path"],
        "filename": entry["filename"],
        "classification": entry["classification"],
        "provenance_status": entry["provenance_status"],
        "source_status": entry["source_status"],
        "duplicate_group": entry["duplicate_group"],
        "inventory_origin": entry["inventory_origin"],
    }


def _examples(entries: list[dict], limit: int = 5) -> list[dict]:
    ordered = sorted(entries, key=lambda item: (item["absolute_path"], item["source_id"]))
    return [_queue_item(entry) for entry in ordered[:limit]]


def _excluded_secret_entries(bc11e1: dict, bc11e2: dict) -> list[dict]:
    items: list[dict] = []
    for origin, payload in ((ORIGIN_BC11E1, bc11e1), (ORIGIN_BC11E2, bc11e2)):
        for entry in payload.get("entries", []):
            if not isinstance(entry, dict):
                continue
            if entry.get("exclusion_reason") != "SECRET_FILENAME_REJECTED":
                continue
            items.append(
                {
                    "source_id": entry.get("source_id"),
                    "absolute_path": entry.get("absolute_path"),
                    "filename": entry.get("filename"),
                    "inventory_origin": origin,
                    "exclusion_reason": entry.get("exclusion_reason"),
                }
            )
    return sorted(items, key=lambda item: (str(item["absolute_path"]), str(item["source_id"])))


def _build_queue(
    *,
    queue_id: str,
    name: str,
    entries: list[dict],
    reason_for_review: str,
    recommended_next_check: str,
) -> dict:
    return {
        "queue_id": queue_id,
        "name": name,
        "count": len(entries),
        "reason_for_review": reason_for_review,
        "recommended_next_check": recommended_next_check,
        "representative_examples": _examples(entries),
        "source_ids": [entry["source_id"] for entry in entries],
    }


def build_review_queues(
    candidates: list[dict],
    bc11e1: dict,
    bc11e2: dict,
) -> dict:
    secret_entries = _excluded_secret_entries(bc11e1, bc11e2)
    known_out_of_scope = list(bc11e2.get("out_of_scope_locations", []))
    queues = [
        _build_queue(
            queue_id="A",
            name="CURSOR_CANDIDATES",
            entries=[e for e in candidates if e["classification"] == CLASS_CURSOR],
            reason_for_review=(
                "Filename or inventory origin suggests Cursor, but metadata alone "
                "does not confirm the authoring agent."
            ),
            recommended_next_check=(
                "Confirm Cursor provenance from an approved source record before "
                "any import approval."
            ),
        ),
        _build_queue(
            queue_id="B",
            name="OTHER_AGENT_CANDIDATES",
            entries=[e for e in candidates if e["classification"] == CLASS_OTHER_AGENT],
            reason_for_review=(
                "Directory or filename hints another agent, but provenance is not "
                "confirmed and the content owner must be decided."
            ),
            recommended_next_check=(
                "Review root/filename evidence and decide whether these reports "
                "are in scope before approval."
            ),
        ),
        _build_queue(
            queue_id="C",
            name="CHATGPT_CANDIDATES",
            entries=[e for e in candidates if e["classification"] == CLASS_CHATGPT],
            reason_for_review=(
                "ChatGPT review hint only; no authoring provenance is confirmed."
            ),
            recommended_next_check=(
                "Confirm the ChatGPT review origin and whether review artefacts "
                "should be imported as knowledge."
            ),
        ),
        _build_queue(
            queue_id="D",
            name="UNKNOWN_ORIGIN_CANDIDATES",
            entries=[e for e in candidates if e["classification"] == CLASS_UNKNOWN],
            reason_for_review=(
                "Origin is UNKNOWN from metadata. These candidates must not be "
                "dropped solely because the agent is unknown."
            ),
            recommended_next_check=(
                "Inspect report headers only after explicit approval, or obtain "
                "operator provenance confirmation."
            ),
        ),
        _build_queue(
            queue_id="E",
            name="POSSIBLE_DUPLICATES",
            entries=[
                e for e in candidates if e["duplicate_kind"] == DUP_POSSIBLE
            ],
            reason_for_review=(
                "Same filename and size does not prove identical content. No "
                "content hash was computed."
            ),
            recommended_next_check=(
                "Keep all members on hold; compare content only under an approved "
                "content-review step."
            ),
        ),
    ]

    out_of_scope_entries = [
        e for e in candidates if e["classification"] == CLASS_OUT_OF_SCOPE
    ]
    queues.append(
        {
            **_build_queue(
                queue_id="F",
                name="OUT_OF_SCOPE",
                entries=out_of_scope_entries,
                reason_for_review=(
                    "Locations outside the approved report roots are not import "
                    "candidates for this task."
                ),
                recommended_next_check=(
                    "Decide separately whether any out-of-scope root should be "
                    "added to a later inventory."
                ),
            ),
            "known_out_of_scope_locations": known_out_of_scope,
        }
    )

    queues.append(
        _build_queue(
            queue_id="G",
            name="MISSING_SOURCE_FILES",
            entries=[e for e in candidates if e["source_status"] == SOURCE_MISSING],
            reason_for_review=(
                "The inventory recorded a path whose source no longer exists."
            ),
            recommended_next_check=(
                "Recover the source or remove the candidate from any future "
                "import manifest after operator confirmation."
            ),
        )
    )

    queues.append(
        {
            **_build_queue(
                queue_id="H",
                name="SECRET_FILENAME_EXCLUSIONS",
                entries=[],
                reason_for_review=(
                    "Secret-looking filenames were excluded during the source "
                    "inventories and must never be imported."
                ),
                recommended_next_check=(
                    "No action if the count stays zero. If it grows, confirm the "
                    "exclusion before any import."
                ),
            ),
            "excluded_entries": secret_entries,
            "count": len(secret_entries),
        }
    )

    return {
        "schema_version": QUEUE_SCHEMA_VERSION,
        "mode": "METADATA_ONLY_REVIEW_QUEUES",
        "content_read": False,
        "hash_computed": False,
        "real_import_executed": False,
        "queues": queues,
        "counts": {queue["name"]: queue["count"] for queue in queues},
    }


def _coverage(bc11e1: dict, bc11e2: dict) -> dict:
    scanned_roots: list[str] = []
    for root in bc11e1.get("scanned_roots", []):
        scanned_roots.append(_norm(str(root)))
    for record in bc11e2.get("report_roots", []):
        if isinstance(record, dict) and record.get("scanned"):
            scanned_roots.append(_norm(str(record.get("absolute_path", ""))))
    scanned_roots = sorted(set(scanned_roots))

    scan_limits = int(bc11e2.get("counts", {}).get("SCAN_LIMIT_REACHED_COUNT", 0) or 0)
    errors = bc11e2.get("errors", [])
    within = (
        COVERAGE_COMPLETE
        if scan_limits == 0 and not errors
        else COVERAGE_ADDITIONAL
    )

    known_not_scanned = [
        item
        for item in bc11e2.get("out_of_scope_locations", [])
        if isinstance(item, dict)
    ]
    additional = sorted(
        {
            _norm(str(item.get("path", "")))
            for item in known_not_scanned
            if _norm(str(item.get("path", ""))) not in scanned_roots
            and str(item.get("path", ""))
        }
    )

    return {
        "coverage_status": COVERAGE_ADDITIONAL if additional else within,
        "coverage_within_scanned_roots": within,
        "scanned_roots": scanned_roots,
        "additional_source_roots": additional,
        "known_not_scanned_locations": known_not_scanned,
        "full_history_asserted": False,
    }


def consolidate_inventory(
    bc11e1: dict,
    bc11e2: dict,
    *,
    generated_at: str | None = None,
    expected_bc11e1: dict | None = None,
    expected_bc11e2: dict | None = None,
    reconciliation: dict | None = None,
    stat_func=None,
) -> dict:
    """Build all unified payloads without writing anything."""

    validate_input(bc11e1, origin=ORIGIN_BC11E1)
    validate_input(bc11e2, origin=ORIGIN_BC11E2)

    if reconciliation is None:
        reconciliation = reconcile_inputs(
            bc11e1,
            bc11e2,
            expected_bc11e1=expected_bc11e1,
            expected_bc11e2=expected_bc11e2,
        )

    stat_func = stat_func or os.stat
    candidates = [
        _normalise_bc11e1(item) for item in bc11e1.get("candidates", [])
    ] + [_normalise_bc11e2(item) for item in bc11e2.get("candidates", [])]

    for entry in candidates:
        _check_source(entry, stat_func)

    groups = _build_duplicate_groups(candidates)
    review_groups = _select_representatives(candidates, groups)

    candidates.sort(key=lambda item: (item["absolute_path"], item["source_id"]))

    counts = {
        "BC11E1_CANDIDATE_COUNT": len(bc11e1.get("candidates", [])),
        "BC11E2_CANDIDATE_COUNT": len(bc11e2.get("candidates", [])),
        "UNIFIED_CANDIDATE_COUNT": len(candidates),
        "EXACT_PATH_DUPLICATE_COUNT": sum(
            1 for entry in candidates if entry["duplicate_kind"] == DUP_EXACT_PATH
        ),
        "POSSIBLE_DUPLICATE_COUNT": sum(
            1 for entry in candidates if entry["duplicate_kind"] == DUP_POSSIBLE
        ),
        "NAME_COLLISION_COUNT": sum(
            1 for entry in candidates if entry["duplicate_kind"] == DUP_NAME_COLLISION
        ),
        "UNIQUE_METADATA_COUNT": sum(
            1 for entry in candidates if entry["duplicate_group"] is None
        ),
        "DUPLICATE_GROUP_COUNT": len(review_groups),
        "CURSOR_CANDIDATE_COUNT": sum(
            1 for entry in candidates if entry["classification"] == CLASS_CURSOR
        ),
        "OTHER_AGENT_CANDIDATE_COUNT": sum(
            1 for entry in candidates if entry["classification"] == CLASS_OTHER_AGENT
        ),
        "CHATGPT_CANDIDATE_COUNT": sum(
            1 for entry in candidates if entry["classification"] == CLASS_CHATGPT
        ),
        "UNKNOWN_CANDIDATE_COUNT": sum(
            1 for entry in candidates if entry["classification"] == CLASS_UNKNOWN
        ),
        "OUT_OF_SCOPE_CANDIDATE_COUNT": sum(
            1 for entry in candidates if entry["classification"] == CLASS_OUT_OF_SCOPE
        ),
        "SOURCE_PRESENT_COUNT": sum(
            1 for entry in candidates if entry["source_status"] == SOURCE_PRESENT
        ),
        "SOURCE_MISSING_COUNT": sum(
            1 for entry in candidates if entry["source_status"] == SOURCE_MISSING
        ),
        "SOURCE_CHANGED_COUNT": sum(
            1 for entry in candidates if entry["source_status"] == SOURCE_CHANGED
        ),
        "PROVENANCE_CONFIRMED_CURSOR_COUNT": sum(
            1
            for entry in candidates
            if entry["provenance_status"] == PROVENANCE_CONFIRMED_CURSOR
        ),
        "PROVENANCE_CONFIRMED_OTHER_AGENT_COUNT": sum(
            1
            for entry in candidates
            if entry["provenance_status"] == PROVENANCE_CONFIRMED_OTHER_AGENT
        ),
        "PROVENANCE_CONFIRMED_CHATGPT_COUNT": sum(
            1
            for entry in candidates
            if entry["provenance_status"] == PROVENANCE_CONFIRMED_CHATGPT
        ),
        "PROVENANCE_UNKNOWN_COUNT": sum(
            1 for entry in candidates if entry["provenance_status"] == PROVENANCE_UNKNOWN
        ),
        "REPRESENTATIVE_COUNT": sum(
            1 for entry in candidates if entry["selection_status"] == SELECTION_REPRESENTATIVE
        ),
        "HOLD_UNVERIFIED_COUNT": sum(
            1 for entry in candidates if entry["selection_status"] == SELECTION_HOLD
        ),
        "UNIQUE_REVIEW_ONLY_COUNT": sum(
            1 for entry in candidates if entry["selection_status"] == SELECTION_UNIQUE
        ),
        "MANIFEST_CANDIDATE_COUNT": len(candidates),
        "APPROVED_TRUE_COUNT": sum(1 for entry in candidates if entry["approved"]),
    }

    coverage = _coverage(bc11e1, bc11e2)
    timestamp = generated_at or _now_iso()

    unified = {
        "schema_version": UNIFIED_SCHEMA_VERSION,
        "generated_at": timestamp,
        "mode": "OFFLINE_METADATA_CONSOLIDATION_ONLY",
        "content_read": False,
        "hash_computed": False,
        "real_import_executed": False,
        "full_history_asserted": False,
        "inputs": {
            "bc11e1_schema_version": bc11e1.get("schema_version"),
            "bc11e2_schema_version": bc11e2.get("schema_version"),
            "reconciliation": reconciliation,
        },
        **coverage,
        "counts": counts,
        "safety": {
            "approved_true_count": counts["APPROVED_TRUE_COUNT"],
            "origin_confirmed_count": sum(
                1 for entry in candidates if entry["origin_confirmed"]
            ),
            "body_hash_computed": False,
            "body_text_stored": False,
            "content_read_count": 0,
        },
        "candidates": candidates,
    }

    duplicate_review = {
        "schema_version": DUPLICATE_SCHEMA_VERSION,
        "generated_at": timestamp,
        "mode": "METADATA_ONLY_DUPLICATE_REVIEW",
        "content_read": False,
        "hash_computed": False,
        "note": (
            "Metadata-only duplicate candidates. No content was read or hashed, "
            "so no group is a confirmed full duplicate. Representatives are for "
            "review display only and are not import selections."
        ),
        "counts": {
            "DUPLICATE_GROUP_COUNT": counts["DUPLICATE_GROUP_COUNT"],
            "EXACT_PATH_DUPLICATE_COUNT": counts["EXACT_PATH_DUPLICATE_COUNT"],
            "POSSIBLE_DUPLICATE_COUNT": counts["POSSIBLE_DUPLICATE_COUNT"],
            "NAME_COLLISION_COUNT": counts["NAME_COLLISION_COUNT"],
            "UNIQUE_METADATA_COUNT": counts["UNIQUE_METADATA_COUNT"],
            "POSSIBLE_DUPLICATE_GROUP_COUNT": sum(
                1 for group in review_groups if group["duplicate_kind"] == DUP_POSSIBLE
            ),
            "NAME_COLLISION_GROUP_COUNT": sum(
                1
                for group in review_groups
                if group["duplicate_kind"] == DUP_NAME_COLLISION
            ),
            "EXACT_PATH_DUPLICATE_GROUP_COUNT": sum(
                1
                for group in review_groups
                if group["duplicate_kind"] == DUP_EXACT_PATH
            ),
        },
        "representative_policy": [
            "prefer candidates inside the BC-only /tmp/work_bc_audit root",
            "prefer candidates whose source still exists",
            "prefer candidates belonging to a git worktree",
            "prefer a stable absolute path",
            "break ties deterministically by source_id",
        ],
        "groups": review_groups,
    }

    queues = build_review_queues(candidates, bc11e1, bc11e2)
    queues["generated_at"] = timestamp

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": timestamp,
        "manifest_kind": "MANIFEST_CANDIDATE",
        "mode": "OFFLINE_METADATA_CONSOLIDATION_ONLY",
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "operator_review_required": True,
        "note": (
            "Unapproved review manifest. No entry may be used for a real import "
            "until an operator confirms provenance and duplicate handling."
        ),
        "counts": {
            "MANIFEST_CANDIDATE_COUNT": len(candidates),
            "APPROVED_TRUE_COUNT": counts["APPROVED_TRUE_COUNT"],
            "ALL_APPROVED_FALSE": counts["APPROVED_TRUE_COUNT"] == 0,
        },
        "entries": [
            {
                "sourceId": entry["source_id"],
                "path": entry["absolute_path"],
                "sourceType": entry["classification"],
                "provenanceStatus": entry["provenance_status"],
                "duplicateGroup": entry["duplicate_group"],
                "selectionStatus": entry["selection_status"],
                "approved": False,
                "sourceStatus": entry["source_status"],
            }
            for entry in candidates
        ],
    }

    return {
        "unified_inventory": unified,
        "duplicate_review": duplicate_review,
        "review_queues": queues,
        "import_manifest_candidate": manifest,
        "counts": counts,
        "coverage": coverage,
        "reconciliation": reconciliation,
    }


def _render_summary(result: dict) -> str:
    unified = result["unified_inventory"]
    counts = unified["counts"]
    queues = result["review_queues"]
    lines = [
        "# BC-11E-3 Candidate Consolidation Summary",
        "",
        f"- schema_version: `{unified['schema_version']}`",
        f"- generated_at: `{unified['generated_at']}`",
        f"- mode: `{unified['mode']}`",
        f"- content_read: `{unified['content_read']}`",
        f"- hash_computed: `{unified['hash_computed']}`",
        f"- real_import_executed: `{unified['real_import_executed']}`",
        f"- inputs_status: `{result['reconciliation']['status']}`",
        f"- coverage_status: `{unified['coverage_status']}`",
        f"- coverage_within_scanned_roots: `{unified['coverage_within_scanned_roots']}`",
        "- full_history_asserted: `NO`",
        "",
        "## Candidate counts",
        "",
        f"- BC11E1_CANDIDATE_COUNT: {counts['BC11E1_CANDIDATE_COUNT']}",
        f"- BC11E2_CANDIDATE_COUNT: {counts['BC11E2_CANDIDATE_COUNT']}",
        f"- UNIFIED_CANDIDATE_COUNT: {counts['UNIFIED_CANDIDATE_COUNT']}",
        f"- CURSOR_CANDIDATE_COUNT: {counts['CURSOR_CANDIDATE_COUNT']}",
        f"- OTHER_AGENT_CANDIDATE_COUNT: {counts['OTHER_AGENT_CANDIDATE_COUNT']}",
        f"- CHATGPT_CANDIDATE_COUNT: {counts['CHATGPT_CANDIDATE_COUNT']}",
        f"- UNKNOWN_CANDIDATE_COUNT: {counts['UNKNOWN_CANDIDATE_COUNT']}",
        f"- OUT_OF_SCOPE_CANDIDATE_COUNT: {counts['OUT_OF_SCOPE_CANDIDATE_COUNT']}",
        f"- SOURCE_MISSING_COUNT: {counts['SOURCE_MISSING_COUNT']}",
        f"- SOURCE_CHANGED_COUNT: {counts['SOURCE_CHANGED_COUNT']}",
        "",
        "## Duplicate counts",
        "",
        f"- DUPLICATE_GROUP_COUNT: {counts['DUPLICATE_GROUP_COUNT']}",
        f"- EXACT_PATH_DUPLICATE_COUNT: {counts['EXACT_PATH_DUPLICATE_COUNT']}",
        f"- POSSIBLE_DUPLICATE_COUNT: {counts['POSSIBLE_DUPLICATE_COUNT']}",
        f"- NAME_COLLISION_COUNT: {counts['NAME_COLLISION_COUNT']}",
        f"- UNIQUE_METADATA_COUNT: {counts['UNIQUE_METADATA_COUNT']}",
        f"- REPRESENTATIVE_COUNT: {counts['REPRESENTATIVE_COUNT']}",
        f"- HOLD_UNVERIFIED_COUNT: {counts['HOLD_UNVERIFIED_COUNT']}",
        "- deduplication of unverified candidates: `NONE`",
        "",
        "## Review queue counts",
        "",
        "| queue | count |",
        "| --- | --- |",
    ]
    for name, value in queues["counts"].items():
        lines.append(f"| {name} | {value} |")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report bodies were not read, decoded, hashed, or stored.",
            "- No manifest entry is approved; the manifest is not import-ready.",
            "- No real import, production write, or git push was performed by this script.",
            "",
            "## Known additional source roots",
            "",
        ]
    )
    additional = unified.get("additional_source_roots", [])
    if additional:
        for item in additional:
            lines.append(f"- `{item}` (not scanned by this consolidation)")
    else:
        lines.append("- (none)")
    lines.append("")
    return "\n".join(lines)


def write_outputs(result: dict, output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> dict:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    paths = {
        "unified_inventory": target / UNIFIED_JSON_NAME,
        "duplicate_review": target / DUPLICATE_JSON_NAME,
        "review_queues": target / QUEUES_JSON_NAME,
        "import_manifest_candidate": target / MANIFEST_JSON_NAME,
        "candidate_summary": target / SUMMARY_MD_NAME,
    }
    for key in (
        "unified_inventory",
        "duplicate_review",
        "review_queues",
        "import_manifest_candidate",
    ):
        path = paths[key]
        path.write_text(
            json.dumps(result[key], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    paths["candidate_summary"].write_text(
        _render_summary(result) + "\n", encoding="utf-8"
    )
    return {key: str(path) for key, path in paths.items()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bc11e1", default=str(DEFAULT_BC11E1_PATH))
    parser.add_argument("--bc11e2", default=str(DEFAULT_BC11E2_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--generated-at", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        bc11e1 = load_input(args.bc11e1)
        bc11e2 = load_input(args.bc11e2)
    except InputError as exc:
        print(
            json.dumps(
                {"status": exc.code, "path": exc.path, "detail": exc.detail},
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    reconciliation = reconcile_inputs(bc11e1, bc11e2)
    if not reconciliation["inputs_valid"]:
        print(
            json.dumps(
                {
                    "status": INPUT_COUNT_MISMATCH,
                    "mismatches": reconciliation["mismatches"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    result = consolidate_inventory(
        bc11e1,
        bc11e2,
        generated_at=args.generated_at or None,
        reconciliation=reconciliation,
    )
    paths = write_outputs(result, args.output_dir)
    summary = {
        "status": INPUTS_VALID,
        "counts": result["counts"],
        "coverage_status": result["coverage"]["coverage_status"],
        "full_history_asserted": False,
        "outputs": paths,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
