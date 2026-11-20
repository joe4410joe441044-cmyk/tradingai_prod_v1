#!/usr/bin/env python3
"""BC-11E-4 metadata-only verification readiness for historical agent reports.

This module consumes the already-produced BC-11E-3 artefacts and prepares the
next review step without touching any report body:

* reads the BC-11E-3 unified inventory, duplicate review, review queues, and
  import manifest candidate JSON files,
* reconciles the recorded counts against the BC-11E-3 baseline,
* builds a candidate-disjoint duplicate verification plan,
* builds a provenance review plan that never confirms an origin from metadata,
* builds a priority-ordered verification queue,
* builds an import readiness candidate where every entry stays unapproved.

No report body is opened, decoded, hashed, or imported. No content hash is
computed. Nothing is written outside the requested output directory.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DUPLICATE_PLAN_SCHEMA_VERSION = "tradingai-bc11e4-duplicate-verification-plan/v1"
PROVENANCE_PLAN_SCHEMA_VERSION = "tradingai-bc11e4-provenance-review-plan/v1"
QUEUE_SCHEMA_VERSION = "tradingai-bc11e4-verification-queue/v1"
READINESS_SCHEMA_VERSION = "tradingai-bc11e4-import-readiness-candidate/v1"

DEFAULT_OUTPUT_DIR = Path("/tmp/work_bc_audit")
DEFAULT_UNIFIED_PATH = DEFAULT_OUTPUT_DIR / "BC11E3_UNIFIED_INVENTORY.json"
DEFAULT_DUPLICATE_PATH = DEFAULT_OUTPUT_DIR / "BC11E3_DUPLICATE_REVIEW.json"
DEFAULT_QUEUES_PATH = DEFAULT_OUTPUT_DIR / "BC11E3_REVIEW_QUEUES.json"
DEFAULT_MANIFEST_PATH = DEFAULT_OUTPUT_DIR / "BC11E3_IMPORT_MANIFEST_CANDIDATE.json"

DUPLICATE_PLAN_JSON_NAME = "BC11E4_DUPLICATE_VERIFICATION_PLAN.json"
PROVENANCE_PLAN_JSON_NAME = "BC11E4_PROVENANCE_REVIEW_PLAN.json"
QUEUE_JSON_NAME = "BC11E4_VERIFICATION_QUEUE.json"
READINESS_JSON_NAME = "BC11E4_IMPORT_READINESS_CANDIDATE.json"
SUMMARY_MD_NAME = "BC11E4_READINESS_SUMMARY.md"

MODE = "OFFLINE_METADATA_ONLY_VERIFICATION_READINESS"

CLASS_CURSOR = "CURSOR_CANDIDATE"
CLASS_OTHER_AGENT = "OTHER_AGENT_CANDIDATE"
CLASS_CHATGPT = "CHATGPT_CANDIDATE"
CLASS_UNKNOWN = "UNKNOWN_CANDIDATE"

DUP_EXACT_PATH = "EXACT_PATH_DUPLICATE"
DUP_POSSIBLE = "POSSIBLE_DUPLICATE"
DUP_NAME_COLLISION = "NAME_COLLISION"

PROVENANCE_UNKNOWN = "UNKNOWN"

APPROVAL_UNAPPROVED = "UNAPPROVED"

VERIFICATION_NOT_STARTED = "NOT_STARTED"
REVIEW_NOT_STARTED = "NOT_STARTED"
REVIEW_REQUIRED = True

LEVEL_0 = "LEVEL_0_METADATA_MATCH"
LEVEL_1 = "LEVEL_1_CONTENT_HASH"
LEVEL_2 = "LEVEL_2_BODY_REVIEW_IF_NEEDED"
LEVEL_3 = "LEVEL_3_PROVENANCE_HISTORY_VERIFICATION"

VERIFICATION_LEVELS = {
    "LEVEL_0": "Metadata consistency (name, size, path). Executed in this readiness task.",
    "LEVEL_1": "Content hash comparison. Not executed by this task.",
    "LEVEL_2": "Report body review, only when explicitly required. Not executed.",
    "LEVEL_3": "Authoring origin, history, and storage consistency. Not executed.",
}

# Lower value is stronger duplicate evidence and is used to assign each
# candidate to exactly one verification group.
DUP_KIND_RANK = {DUP_EXACT_PATH: 0, DUP_POSSIBLE: 1, DUP_NAME_COLLISION: 2}

# The verification method the next step will apply for each duplicate kind.
DUP_METHOD_BY_KIND = {
    DUP_EXACT_PATH: LEVEL_0,
    DUP_POSSIBLE: LEVEL_1,
    DUP_NAME_COLLISION: LEVEL_2,
}

PRIORITY_P0 = "P0"
PRIORITY_P1 = "P1"
PRIORITY_P2 = "P2"
PRIORITY_P3 = "P3"
PRIORITY_P4 = "P4"
PRIORITY_ORDER = [
    PRIORITY_P0,
    PRIORITY_P1,
    PRIORITY_P2,
    PRIORITY_P3,
    PRIORITY_P4,
]
PRIORITY_RANK = {value: index for index, value in enumerate(PRIORITY_ORDER)}
PRIORITY_BASIS = {
    PRIORITY_P0: "Cursor Agent candidate.",
    PRIORITY_P1: (
        "Same name/size candidate present across multiple worktrees "
        "(possible or exact duplicate)."
    ),
    PRIORITY_P2: "Other Agent candidate.",
    PRIORITY_P3: "ChatGPT candidate.",
    PRIORITY_P4: "UNKNOWN origin candidate. Never auto-excluded.",
}

EVIDENCE_BY_REASON = {
    "FILENAME_MATCH_BC_PREFIX": "FILENAME_PREFIX_HINT",
    "CHATGPT_ROOT_OR_FILENAME_HINT": "DIRECTORY_OR_FILENAME_HINT",
    "OPENCODE_ROOT_HINT": "DIRECTORY_HINT",
    "SUPPORTED_EXTENSION_ORIGIN_UNCONFIRMED": "EXTENSION_ONLY",
    "ORIGIN_UNCONFIRMED": "NONE",
    "JSON_CONTENT_NOT_READ_REVIEW_REQUIRED": "JSON_METADATA_REVIEW_REQUIRED",
}
DEFAULT_EVIDENCE_TYPE = "INVENTORY_METADATA_ONLY"

EXPECTED_BASELINE = {
    "UNIFIED_CANDIDATE_COUNT": 6646,
    "MANIFEST_CANDIDATE_COUNT": 6646,
    "DUPLICATE_GROUP_COUNT": 52,
    "POSSIBLE_DUPLICATE_COUNT": 6174,
    "UNIQUE_METADATA_COUNT": 472,
    "CURSOR_CANDIDATE_COUNT": 31,
    "OTHER_AGENT_CANDIDATE_COUNT": 242,
    "CHATGPT_CANDIDATE_COUNT": 353,
    "UNKNOWN_CANDIDATE_COUNT": 6020,
    "SOURCE_MISSING_COUNT": 0,
    "SOURCE_CHANGED_COUNT": 0,
    "ALL_APPROVED_FALSE": True,
}

REQUIRED_CANDIDATE_FIELDS = (
    "source_id",
    "absolute_path",
    "filename",
    "size_bytes",
    "mtime",
    "source_root",
    "inventory_origin",
    "source_classification",
    "provenance_status",
    "duplicate_group",
    "selection_status",
)

REQUIRED_MANIFEST_ENTRY_FIELDS = (
    "sourceId",
    "path",
    "provenanceStatus",
    "duplicateGroup",
    "selectionStatus",
    "approved",
    "sourceStatus",
)

INPUTS_VALID = "INPUTS_VALID"
INPUT_COUNT_MISMATCH = "INPUT_COUNT_MISMATCH"
BLOCKED_MISSING_INPUT = "BLOCKED_MISSING_INPUT"
BLOCKED_INVALID_INPUT = "BLOCKED_INVALID_INPUT"


class InputError(Exception):
    """A required input is missing or structurally invalid."""

    def __init__(self, code: str, path: str, detail: str) -> None:
        super().__init__(f"{code}: {path}: {detail}")
        self.code = code
        self.path = path
        self.detail = detail


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_input(path: str | Path) -> dict:
    """Load one BC-11E-3 JSON artefact. Raises InputError on problems."""

    target = Path(path)
    if not target.exists():
        raise InputError(BLOCKED_MISSING_INPUT, str(target), "file does not exist")
    if not target.is_file():
        raise InputError(BLOCKED_INVALID_INPUT, str(target), "not a regular file")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(
            BLOCKED_INVALID_INPUT, str(target), type(exc).__name__
        ) from None
    if not isinstance(payload, dict):
        raise InputError(
            BLOCKED_INVALID_INPUT, str(target), "top-level JSON is not an object"
        )
    return payload


def _require(condition: bool, origin: str, detail: str) -> None:
    if not condition:
        raise InputError(BLOCKED_INVALID_INPUT, origin, detail)


def validate_shapes(fixtures: dict) -> None:
    """Validate the structural shape of the four BC-11E-3 artefacts."""

    unified = fixtures["unified"]
    duplicate_review = fixtures["duplicate_review"]
    review_queues = fixtures["review_queues"]
    manifest = fixtures["manifest"]

    _require(isinstance(unified.get("candidates"), list), "unified", "candidates is not a list")
    _require(isinstance(unified.get("counts"), dict), "unified", "counts is not an object")
    for index, candidate in enumerate(unified["candidates"]):
        _require(isinstance(candidate, dict), "unified", f"candidate {index} is not an object")
        missing = [key for key in REQUIRED_CANDIDATE_FIELDS if key not in candidate]
        _require(
            not missing,
            "unified",
            f"candidate {index} missing fields: {','.join(missing)}",
        )

    _require(
        isinstance(duplicate_review.get("groups"), list),
        "duplicate_review",
        "groups is not a list",
    )
    for index, group in enumerate(duplicate_review["groups"]):
        _require(isinstance(group, dict), "duplicate_review", f"group {index} is not an object")
        _require(
            isinstance(group.get("members"), list),
            "duplicate_review",
            f"group {index} members is not a list",
        )
        for member_index, member in enumerate(group["members"]):
            _require(
                isinstance(member, dict) and "source_id" in member,
                "duplicate_review",
                f"group {index} member {member_index} missing source_id",
            )

    _require(
        isinstance(review_queues.get("queues"), list),
        "review_queues",
        "queues is not a list",
    )

    _require(isinstance(manifest.get("entries"), list), "manifest", "entries is not a list")
    _require(isinstance(manifest.get("counts"), dict), "manifest", "counts is not an object")
    for index, entry in enumerate(manifest["entries"]):
        _require(isinstance(entry, dict), "manifest", f"entry {index} is not an object")
        missing = [key for key in REQUIRED_MANIFEST_ENTRY_FIELDS if key not in entry]
        _require(
            not missing,
            "manifest",
            f"entry {index} missing fields: {','.join(missing)}",
        )


def _mismatch(key: str, expected: object, actual: object, detail: str = "") -> dict:
    return {
        "key": key,
        "expected": expected,
        "actual": actual,
        "match": expected == actual,
        "detail": detail,
    }


def validate_inputs(fixtures: dict, *, expected: dict) -> dict:
    """Reconcile the BC-11E-3 artefacts against the supplied baseline."""

    validate_shapes(fixtures)
    unified = fixtures["unified"]
    duplicate_review = fixtures["duplicate_review"]
    manifest = fixtures["manifest"]

    candidates = unified["candidates"]
    unified_counts = unified["counts"]
    dup_counts = duplicate_review.get("counts", {})
    manifest_counts = manifest.get("counts", {})
    groups = duplicate_review["groups"]

    comparisons: list[dict] = []

    def _cmp(key: str, expected_value: object, actual: object) -> None:
        if key in expected:
            comparisons.append(
                _mismatch(key, expected_value, actual)
            )

    def _field_match(key: str, expected_value: object, fields: dict) -> None:
        if key in fields:
            comparisons.append(_mismatch(key, expected_value, fields[key]))

    unified_actual = len(candidates)
    _cmp("UNIFIED_CANDIDATE_COUNT", expected.get("UNIFIED_CANDIDATE_COUNT"), unified_actual)
    _field_match("UNIFIED_COUNT_FIELD_MATCH", unified_actual, unified_counts)

    manifest_actual = len(manifest["entries"])
    _cmp("MANIFEST_CANDIDATE_COUNT", expected.get("MANIFEST_CANDIDATE_COUNT"), manifest_actual)
    _field_match("MANIFEST_COUNT_FIELD_MATCH", manifest_actual, manifest_counts)

    _cmp("DUPLICATE_GROUP_COUNT", expected.get("DUPLICATE_GROUP_COUNT"), len(groups))
    _field_match("DUPLICATE_GROUP_FIELD_MATCH", len(groups), unified_counts)

    classification_actual = {
        "CURSOR_CANDIDATE_COUNT": sum(
            1 for entry in candidates if entry.get("classification") == CLASS_CURSOR
        ),
        "OTHER_AGENT_CANDIDATE_COUNT": sum(
            1 for entry in candidates if entry.get("classification") == CLASS_OTHER_AGENT
        ),
        "CHATGPT_CANDIDATE_COUNT": sum(
            1 for entry in candidates if entry.get("classification") == CLASS_CHATGPT
        ),
        "UNKNOWN_CANDIDATE_COUNT": sum(
            1 for entry in candidates if entry.get("classification") == CLASS_UNKNOWN
        ),
    }
    for key, actual in classification_actual.items():
        _cmp(key, expected.get(key), actual)
        _field_match(f"{key}_FIELD_MATCH", actual, unified_counts)

    duplicate_candidates = [entry for entry in candidates if entry.get("duplicate_group") is not None]
    unique_candidates = [entry for entry in candidates if entry.get("duplicate_group") is None]
    _cmp("POSSIBLE_DUPLICATE_COUNT", expected.get("POSSIBLE_DUPLICATE_COUNT"), len(duplicate_candidates))
    _cmp("UNIQUE_METADATA_COUNT", expected.get("UNIQUE_METADATA_COUNT"), len(unique_candidates))
    _field_match("UNIQUE_FIELD_MATCH", len(unique_candidates), unified_counts)

    group_member_ids: set[str] = set()
    for group in groups:
        for member in group["members"]:
            group_member_ids.add(str(member["source_id"]))
    comparisons.append(
        _mismatch(
            "DUPLICATE_GROUP_MEMBER_UNION",
            len(duplicate_candidates),
            len(group_member_ids),
            "unique duplicate group members must equal candidate-level duplicate count",
        )
    )
    duplicate_ids = {str(entry["source_id"]) for entry in duplicate_candidates}
    comparisons.append(
        _mismatch(
            "DUPLICATE_MEMBER_ID_SET",
            len(duplicate_ids),
            len(group_member_ids & duplicate_ids),
        )
    )
    comparisons.append(
        _mismatch(
            "DUPLICATE_MEMBER_UNKNOWN_IN_UNIFIED",
            0,
            len(group_member_ids - duplicate_ids),
            "group members must exist in the unified inventory",
        )
    )

    possible_group_count = sum(
        1 for group in groups if group.get("duplicate_kind") == DUP_POSSIBLE
    )
    if "POSSIBLE_DUPLICATE_GROUP_COUNT" in dup_counts:
        comparisons.append(
            _mismatch(
                "POSSIBLE_DUPLICATE_GROUP_COUNT",
                dup_counts.get("POSSIBLE_DUPLICATE_GROUP_COUNT"),
                possible_group_count,
            )
        )

    approved_true = sum(1 for entry in manifest["entries"] if entry.get("approved") is not False)
    approved_flags = {
        "APPROVED_TRUE_COUNT": approved_true,
        "MANIFEST_TOP_APPROVED": manifest.get("approved"),
        "MANIFEST_IMPORT_READY": manifest.get("import_ready"),
        "MANIFEST_REAL_IMPORT_ALLOWED": manifest.get("real_import_allowed"),
    }
    comparisons.append(
        _mismatch("APPROVED_TRUE_COUNT", 0, approved_true)
    )
    comparisons.append(
        _mismatch("MANIFEST_TOP_APPROVED", False, approved_flags["MANIFEST_TOP_APPROVED"])
    )
    comparisons.append(
        _mismatch("MANIFEST_IMPORT_READY", False, approved_flags["MANIFEST_IMPORT_READY"])
    )
    comparisons.append(
        _mismatch(
            "MANIFEST_REAL_IMPORT_ALLOWED",
            False,
            approved_flags["MANIFEST_REAL_IMPORT_ALLOWED"],
        )
    )
    if "APPROVED_TRUE_COUNT" in unified_counts:
        comparisons.append(
            _mismatch(
                "UNIFIED_APPROVED_TRUE_COUNT",
                0,
                unified_counts.get("APPROVED_TRUE_COUNT"),
            )
        )

    all_approved_false = (
        approved_true == 0
        and manifest.get("approved") is False
        and manifest.get("import_ready") is False
        and manifest.get("real_import_allowed") is False
        and unified_counts.get("APPROVED_TRUE_COUNT", 0) == 0
    )
    if "ALL_APPROVED_FALSE" in expected:
        comparisons.append(
            _mismatch("ALL_APPROVED_FALSE", expected["ALL_APPROVED_FALSE"], all_approved_false)
        )

    _cmp("SOURCE_MISSING_COUNT", expected.get("SOURCE_MISSING_COUNT"), unified_counts.get("SOURCE_MISSING_COUNT"))
    _cmp("SOURCE_CHANGED_COUNT", expected.get("SOURCE_CHANGED_COUNT"), unified_counts.get("SOURCE_CHANGED_COUNT"))

    mismatches = [item for item in comparisons if not item["match"]]
    return {
        "status": INPUTS_VALID if not mismatches else INPUT_COUNT_MISMATCH,
        "inputs_valid": not mismatches,
        "all_approved_false": all_approved_false,
        "possible_duplicate_group_count": possible_group_count,
        "comparisons": comparisons,
        "mismatches": mismatches,
    }


def _priority_for_candidate(candidate: dict, group_kinds: dict[str, str]) -> str:
    classification = candidate.get("classification")
    if classification == CLASS_CURSOR:
        return PRIORITY_P0
    kind = group_kinds.get(str(candidate["source_id"]))
    if kind in (DUP_EXACT_PATH, DUP_POSSIBLE):
        return PRIORITY_P1
    if classification == CLASS_OTHER_AGENT:
        return PRIORITY_P2
    if classification == CLASS_CHATGPT:
        return PRIORITY_P3
    return PRIORITY_P4


def _evidence_type(candidate: dict) -> str:
    reason = str(candidate.get("candidate_reason", ""))
    return EVIDENCE_BY_REASON.get(reason, DEFAULT_EVIDENCE_TYPE)


def _evidence_basis(candidate: dict) -> list[str]:
    basis = [
        f"inventory_origin:{candidate.get('inventory_origin')}",
        f"source_classification:{candidate.get('source_classification')}",
        f"candidate_reason:{candidate.get('candidate_reason')}",
    ]
    return basis


def _build_group_assignment(
    duplicate_review: dict,
) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Assign every duplicate candidate to exactly one verification group.

    Groups are visited strongest-first (exact path, then possible duplicate,
    then name collision) and each source_id is claimed once. Weaker groups that
    are fully or partially covered are recorded as merged overlap records and
    are never registered as a second verification target.
    """

    groups = duplicate_review["groups"]
    ordered = sorted(
        enumerate(groups),
        key=lambda item: (
            DUP_KIND_RANK.get(str(item[1].get("duplicate_kind")), 99),
            str(item[1].get("duplicate_group", "")),
        ),
    )

    source_to_group_index: dict[str, int] = {}
    for original_index, group in ordered:
        for member in group["members"]:
            source_id = str(member["source_id"])
            if source_id not in source_to_group_index:
                source_to_group_index[source_id] = original_index

    assigned: dict[int, list[dict]] = {index: [] for index in range(len(groups))}
    for index, group in enumerate(groups):
        for member in group["members"]:
            source_id = str(member["source_id"])
            if source_to_group_index.get(source_id) == index:
                assigned[index].append(member)

    verification_groups: list[dict] = []
    overlapping_groups: list[dict] = []
    group_kinds: dict[str, str] = {}

    for index, group in enumerate(groups):
        kind = str(group.get("duplicate_kind"))
        original_members = group["members"]
        verification_members = assigned[index]
        original_ids = {str(member["source_id"]) for member in original_members}
        verification_ids = {str(member["source_id"]) for member in verification_members}

        if not verification_members:
            targets = sorted(
                {
                    str(groups[source_to_group_index[source_id]].get("duplicate_group"))
                    for source_id in original_ids
                    if source_id in source_to_group_index
                }
            )
            overlapping_groups.append(
                {
                    "duplicate_group": group.get("duplicate_group"),
                    "duplicate_kind": kind,
                    "filename": group.get("filename"),
                    "size_bytes": group.get("size_bytes"),
                    "original_member_count": len(original_members),
                    "registered_member_count": 0,
                    "representative_source_id": group.get("representative_source_id"),
                    "merged_into_group_ids": targets,
                    "overlap_status": "FULLY_OVERLAPPING_MERGED",
                    "note": (
                        "Every member is already registered in a stronger "
                        "duplicate group. The group is retained for audit only and "
                        "is not a second verification target."
                    ),
                }
            )
            continue

        if verification_ids != original_ids:
            reassigned = sorted(original_ids - verification_ids)
            overlapping_groups.append(
                {
                    "duplicate_group": group.get("duplicate_group"),
                    "duplicate_kind": kind,
                    "filename": group.get("filename"),
                    "size_bytes": group.get("size_bytes"),
                    "original_member_count": len(original_members),
                    "registered_member_count": len(verification_members),
                    "representative_source_id": group.get("representative_source_id"),
                    "merged_into_group_ids": [],
                    "reassigned_source_ids": reassigned,
                    "overlap_status": "PARTIALLY_OVERLAPPING_MEMBERS_REASSIGNED",
                    "note": (
                        "Overlapping members are registered in a stronger group and "
                        "are not duplicated in this group."
                    ),
                }
            )

        original_representative = group.get("representative_source_id")
        representative_preserved = original_representative in verification_ids
        if representative_preserved:
            representative = str(original_representative)
            representative_note = None
        else:
            representative = sorted(verification_ids)[0]
            representative_note = (
                "ORIGINAL_REPRESENTATIVE_REASSIGNED_DUE_TO_OVERLAP_RESOLUTION"
            )

        member_source_ids = sorted(verification_ids)
        group_kinds.update({source_id: kind for source_id in member_source_ids})
        verification_groups.append(
            {
                "group_id": group.get("duplicate_group"),
                "duplicate_kind": kind,
                "filename": group.get("filename"),
                "size_bytes": group.get("size_bytes"),
                "member_count": len(member_source_ids),
                "original_member_count": len(original_members),
                "representative_source_id": representative,
                "representative_preserved": representative_preserved,
                "representative_change_reason": representative_note,
                "member_source_ids": member_source_ids,
                "verification_method": DUP_METHOD_BY_KIND.get(kind, LEVEL_3),
                "verification_status": VERIFICATION_NOT_STARTED,
                "deduplication_confirmed": False,
                "metadata_match_only": True,
            }
        )

    verification_groups.sort(
        key=lambda group: (
            DUP_KIND_RANK.get(str(group["duplicate_kind"]), 99),
            str(group["group_id"]),
        )
    )
    overlapping_groups.sort(key=lambda group: str(group["duplicate_group"]))
    return verification_groups, overlapping_groups, group_kinds


def _apply_group_priority(
    verification_groups: list[dict], candidates_by_id: dict[str, dict]
) -> None:
    for group in verification_groups:
        priorities = {
            _priority_for_candidate(
                candidates_by_id[source_id],
                {source_id: group["duplicate_kind"]},
            )
            for source_id in group["member_source_ids"]
            if source_id in candidates_by_id
        }
        if priorities:
            group["verification_priority"] = min(
                priorities, key=lambda value: PRIORITY_RANK[value]
            )
        else:
            group["verification_priority"] = PRIORITY_P4


def build_duplicate_verification_plan(
    fixtures: dict,
    *,
    generated_at: str,
    reconciliation: dict,
) -> dict:
    unified = fixtures["unified"]
    candidates_by_id = {
        str(candidate["source_id"]): candidate for candidate in unified["candidates"]
    }
    verification_groups, overlapping_groups, group_kinds = _build_group_assignment(
        fixtures["duplicate_review"]
    )
    _apply_group_priority(verification_groups, candidates_by_id)

    duplicate_member_ids = sorted(group_kinds)
    group_priority_counts = {priority: 0 for priority in PRIORITY_ORDER}
    for group in verification_groups:
        group_priority_counts[group["verification_priority"]] += 1

    return {
        "schema_version": DUPLICATE_PLAN_SCHEMA_VERSION,
        "generated_at": generated_at,
        "mode": MODE,
        "content_read": False,
        "hash_computed": False,
        "real_import_executed": False,
        "inputs_status": reconciliation["status"],
        "source_duplicate_group_count": len(fixtures["duplicate_review"]["groups"]),
        "verification_group_count": len(verification_groups),
        "overlapping_group_count": len(overlapping_groups),
        "duplicate_candidate_count": len(duplicate_member_ids),
        "counts": {
            "SOURCE_DUPLICATE_GROUP_COUNT": len(
                fixtures["duplicate_review"]["groups"]
            ),
            "VERIFICATION_GROUP_COUNT": len(verification_groups),
            "OVERLAPPING_GROUP_COUNT": len(overlapping_groups),
            "DUPLICATE_CANDIDATE_COUNT": len(duplicate_member_ids),
            "POSSIBLE_DUPLICATE_GROUP_COUNT": sum(
                1
                for group in verification_groups
                if group["duplicate_kind"] == DUP_POSSIBLE
            ),
            "NAME_COLLISION_GROUP_COUNT": sum(
                1
                for group in verification_groups
                if group["duplicate_kind"] == DUP_NAME_COLLISION
            ),
            "EXACT_PATH_DUPLICATE_GROUP_COUNT": sum(
                1
                for group in verification_groups
                if group["duplicate_kind"] == DUP_EXACT_PATH
            ),
            "GROUP_PRIORITY_COUNTS": group_priority_counts,
            "ALL_VERIFICATION_NOT_STARTED": all(
                group["verification_status"] == VERIFICATION_NOT_STARTED
                for group in verification_groups
            ),
        },
        "verification_levels": VERIFICATION_LEVELS,
        "executed_verification_level": "LEVEL_0",
        "level_0_executed": True,
        "level_1_or_higher_executed": False,
        "overlapping_groups_merged": overlapping_groups,
        "groups": verification_groups,
    }


def build_provenance_review_plan(
    fixtures: dict,
    *,
    generated_at: str,
    reconciliation: dict,
    group_kinds: dict[str, str],
) -> dict:
    unified = fixtures["unified"]
    entries: list[dict] = []
    for candidate in unified["candidates"]:
        source_id = str(candidate["source_id"])
        entries.append(
            {
                "source_id": source_id,
                "source_classification": candidate.get("source_classification"),
                "classification": candidate.get("classification"),
                "provenance_status": candidate.get("provenance_status", PROVENANCE_UNKNOWN),
                "evidence_type": _evidence_type(candidate),
                "evidence_basis": _evidence_basis(candidate),
                "duplicate_group": candidate.get("duplicate_group"),
                "duplicate_kind": group_kinds.get(source_id),
                "review_priority": _priority_for_candidate(candidate, group_kinds),
                "review_required": REVIEW_REQUIRED,
                "review_status": REVIEW_NOT_STARTED,
                "metadata_confirmed_cursor": False,
                "metadata_confirmed_other_agent": False,
                "metadata_confirmed_chatgpt": False,
                "confirmed_cursor": False,
                "confirmed_other_agent": False,
                "confirmed_chatgpt": False,
            }
        )
    entries.sort(
        key=lambda entry: (
            PRIORITY_RANK[entry["review_priority"]],
            str(entry["source_id"]),
        )
    )

    priority_counts = {priority: 0 for priority in PRIORITY_ORDER}
    evidence_counts: dict[str, int] = {}
    for entry in entries:
        priority_counts[entry["review_priority"]] += 1
        evidence_counts[entry["evidence_type"]] = (
            evidence_counts.get(entry["evidence_type"], 0) + 1
        )

    return {
        "schema_version": PROVENANCE_PLAN_SCHEMA_VERSION,
        "generated_at": generated_at,
        "mode": MODE,
        "content_read": False,
        "hash_computed": False,
        "real_import_executed": False,
        "inputs_status": reconciliation["status"],
        "provenance_policy": (
            "Metadata hints never confirm an authoring origin. Every confirmation "
            "flag stays false until an explicit operator provenance review."
        ),
        "counts": {
            "PROVENANCE_REVIEW_COUNT": len(entries),
            "PRIORITY_COUNTS": priority_counts,
            "EVIDENCE_TYPE_COUNTS": dict(sorted(evidence_counts.items())),
            "CONFIRMED_CURSOR_COUNT": 0,
            "CONFIRMED_OTHER_AGENT_COUNT": 0,
            "CONFIRMED_CHATGPT_COUNT": 0,
            "ALL_REVIEW_NOT_STARTED": all(
                entry["review_status"] == REVIEW_NOT_STARTED for entry in entries
            ),
        },
        "entries": entries,
    }


def build_verification_queue(
    fixtures: dict,
    *,
    generated_at: str,
    reconciliation: dict,
    verification_groups: list[dict],
    group_kinds: dict[str, str],
) -> dict:
    unified = fixtures["unified"]
    method_by_source = {
        source_id: DUP_METHOD_BY_KIND.get(kind, LEVEL_0)
        for source_id, kind in group_kinds.items()
    }
    group_id_by_source: dict[str, str] = {}
    for group in verification_groups:
        for source_id in group["member_source_ids"]:
            group_id_by_source[source_id] = str(group["group_id"])

    items: list[dict] = []
    for candidate in unified["candidates"]:
        source_id = str(candidate["source_id"])
        priority = _priority_for_candidate(candidate, group_kinds)
        in_duplicate_group = source_id in group_kinds
        items.append(
            {
                "source_id": source_id,
                "absolute_path": candidate.get("absolute_path"),
                "classification": candidate.get("classification"),
                "duplicate_group": group_id_by_source.get(source_id),
                "verification_priority": priority,
                "verification_method": method_by_source.get(
                    source_id, LEVEL_0
                ),
                "verification_status": VERIFICATION_NOT_STARTED,
                "review_priority": priority,
                "review_status": REVIEW_NOT_STARTED,
                "duplicate_verification_required": in_duplicate_group,
            }
        )
    items.sort(
        key=lambda item: (
            PRIORITY_RANK[item["verification_priority"]],
            str(item["absolute_path"]),
            str(item["source_id"]),
        )
    )
    for position, item in enumerate(items, start=1):
        item["queue_position"] = position

    priority_counts = {priority: 0 for priority in PRIORITY_ORDER}
    for item in items:
        priority_counts[item["verification_priority"]] += 1

    duplicate_group_queue = sorted(
        (
            {
                "group_id": group["group_id"],
                "duplicate_kind": group["duplicate_kind"],
                "member_count": group["member_count"],
                "verification_priority": group["verification_priority"],
                "verification_method": group["verification_method"],
                "verification_status": group["verification_status"],
            }
            for group in verification_groups
        ),
        key=lambda group: (
            PRIORITY_RANK[group["verification_priority"]],
            DUP_KIND_RANK.get(str(group["duplicate_kind"]), 99),
            str(group["group_id"]),
        ),
    )

    return {
        "schema_version": QUEUE_SCHEMA_VERSION,
        "generated_at": generated_at,
        "mode": MODE,
        "content_read": False,
        "hash_computed": False,
        "real_import_executed": False,
        "inputs_status": reconciliation["status"],
        "priority_policy": PRIORITY_BASIS,
        "counts": {
            "VERIFICATION_QUEUE_COUNT": len(items),
            "DUPLICATE_VERIFICATION_REQUIRED_COUNT": sum(
                1 for item in items if item["duplicate_verification_required"]
            ),
            "PRIORITY_COUNTS": priority_counts,
            "ALL_VERIFICATION_NOT_STARTED": all(
                item["verification_status"] == VERIFICATION_NOT_STARTED
                for item in items
            ),
        },
        "duplicate_group_queue": duplicate_group_queue,
        "items": items,
    }


def build_import_readiness_candidate(
    fixtures: dict,
    *,
    generated_at: str,
    reconciliation: dict,
    group_kinds: dict[str, str],
) -> dict:
    unified = fixtures["unified"]
    entries: list[dict] = []
    for candidate in unified["candidates"]:
        source_id = str(candidate["source_id"])
        entries.append(
            {
                "source_id": source_id,
                "path": candidate.get("absolute_path"),
                "classification": candidate.get("classification"),
                "provenance_status": candidate.get(
                    "provenance_status", PROVENANCE_UNKNOWN
                ),
                "duplicate_group": candidate.get("duplicate_group"),
                "verification_status": VERIFICATION_NOT_STARTED,
                "review_status": REVIEW_NOT_STARTED,
                "approval_status": APPROVAL_UNAPPROVED,
                "priority": _priority_for_candidate(candidate, group_kinds),
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
            }
        )
    entries.sort(key=lambda entry: str(entry["source_id"]))

    approved_true = sum(1 for entry in entries if entry["approved"])
    import_ready_true = sum(1 for entry in entries if entry["import_ready"])
    return {
        "schema_version": READINESS_SCHEMA_VERSION,
        "generated_at": generated_at,
        "mode": MODE,
        "content_read": False,
        "hash_computed": False,
        "real_import_executed": False,
        "inputs_status": reconciliation["status"],
        "manifest_kind": "IMPORT_READINESS_CANDIDATE",
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "operator_review_required": True,
        "note": (
            "Unapproved readiness candidate. Nothing here may be imported until a "
            "separate approved manifest is produced after provenance and duplicate "
            "verification are complete."
        ),
        "counts": {
            "IMPORT_READINESS_CANDIDATE_COUNT": len(entries),
            "APPROVED_TRUE_COUNT": approved_true,
            "IMPORT_READY_TRUE_COUNT": import_ready_true,
            "REAL_IMPORT_ALLOWED_TRUE_COUNT": sum(
                1 for entry in entries if entry["real_import_allowed"]
            ),
            "ALL_APPROVED_FALSE": approved_true == 0,
            "ALL_IMPORT_READY_FALSE": import_ready_true == 0,
            "ALL_VERIFICATION_NOT_STARTED": all(
                entry["verification_status"] == VERIFICATION_NOT_STARTED
                for entry in entries
            ),
        },
        "entries": entries,
    }


def build_readiness(
    fixtures: dict,
    *,
    expected: dict,
    generated_at: str | None = None,
) -> dict:
    """Build every readiness payload without writing anything."""

    reconciliation = validate_inputs(fixtures, expected=expected)
    timestamp = generated_at or _now_iso()

    duplicate_plan = build_duplicate_verification_plan(
        fixtures, generated_at=timestamp, reconciliation=reconciliation
    )
    _, _, group_kinds = _build_group_assignment(fixtures["duplicate_review"])
    provenance_plan = build_provenance_review_plan(
        fixtures,
        generated_at=timestamp,
        reconciliation=reconciliation,
        group_kinds=group_kinds,
    )
    verification_queue = build_verification_queue(
        fixtures,
        generated_at=timestamp,
        reconciliation=reconciliation,
        verification_groups=duplicate_plan["groups"],
        group_kinds=group_kinds,
    )
    readiness = build_import_readiness_candidate(
        fixtures,
        generated_at=timestamp,
        reconciliation=reconciliation,
        group_kinds=group_kinds,
    )

    unified = fixtures["unified"]
    coverage_status = (
        unified.get("coverage_status") or "ADDITIONAL_SOURCE_ROOTS_REQUIRED"
    )
    result = {
        "duplicate_verification_plan": duplicate_plan,
        "provenance_review_plan": provenance_plan,
        "verification_queue": verification_queue,
        "import_readiness_candidate": readiness,
        "reconciliation": reconciliation,
        "counts": {
            "UNIFIED_CANDIDATE_COUNT": len(unified["candidates"]),
            "DUPLICATE_CANDIDATE_COUNT": duplicate_plan["duplicate_candidate_count"],
            "SOURCE_DUPLICATE_GROUP_COUNT": duplicate_plan[
                "source_duplicate_group_count"
            ],
            "VERIFICATION_GROUP_COUNT": duplicate_plan["verification_group_count"],
            "OVERLAPPING_GROUP_COUNT": duplicate_plan["overlapping_group_count"],
            "VERIFICATION_QUEUE_COUNT": verification_queue["counts"][
                "VERIFICATION_QUEUE_COUNT"
            ],
            "PROVENANCE_REVIEW_COUNT": provenance_plan["counts"][
                "PROVENANCE_REVIEW_COUNT"
            ],
            "IMPORT_READINESS_CANDIDATE_COUNT": readiness["counts"][
                "IMPORT_READINESS_CANDIDATE_COUNT"
            ],
            "ALL_APPROVED_FALSE": readiness["counts"]["ALL_APPROVED_FALSE"],
            "ALL_VERIFICATION_NOT_STARTED": (
                duplicate_plan["counts"]["ALL_VERIFICATION_NOT_STARTED"]
                and verification_queue["counts"]["ALL_VERIFICATION_NOT_STARTED"]
                and readiness["counts"]["ALL_VERIFICATION_NOT_STARTED"]
            ),
            "ALL_IMPORT_READY_FALSE": readiness["counts"]["ALL_IMPORT_READY_FALSE"],
        },
        "coverage_status": coverage_status,
        "full_history_asserted": False,
    }
    return result


def _render_summary(result: dict) -> str:
    counts = result["counts"]
    duplicate_plan = result["duplicate_verification_plan"]
    provenance_plan = result["provenance_review_plan"]
    queue_counts = result["verification_queue"]["counts"]
    readiness_counts = result["import_readiness_candidate"]["counts"]
    lines = [
        "# BC-11E-4 Verification Readiness Summary",
        "",
        f"- schema_version: `{duplicate_plan['schema_version']}`",
        f"- generated_at: `{duplicate_plan['generated_at']}`",
        f"- mode: `{duplicate_plan['mode']}`",
        f"- inputs_status: `{result['reconciliation']['status']}`",
        "- content_read: `False`",
        "- hash_computed: `False`",
        "- real_import_executed: `False`",
        f"- coverage_status: `{result['coverage_status']}`",
        "- full_history_asserted: `NO`",
        "",
        "## Duplicate verification",
        "",
        f"- DUPLICATE_CANDIDATE_COUNT: {counts['DUPLICATE_CANDIDATE_COUNT']}",
        f"- SOURCE_DUPLICATE_GROUP_COUNT: {counts['SOURCE_DUPLICATE_GROUP_COUNT']}",
        f"- VERIFICATION_GROUP_COUNT: {counts['VERIFICATION_GROUP_COUNT']}",
        f"- OVERLAPPING_GROUP_COUNT: {counts['OVERLAPPING_GROUP_COUNT']}",
        "- All members of a weaker overlapping group are registered exactly once.",
        "- No candidate is a verification target twice.",
        "",
        "## Verification queue",
        "",
        f"- VERIFICATION_QUEUE_COUNT: {counts['VERIFICATION_QUEUE_COUNT']}",
        f"- DUPLICATE_VERIFICATION_REQUIRED_COUNT: {queue_counts['DUPLICATE_VERIFICATION_REQUIRED_COUNT']}",
    ]
    for priority in PRIORITY_ORDER:
        lines.append(
            f"- {priority}: {queue_counts['PRIORITY_COUNTS'][priority]}"
        )
    lines.extend(
        [
            "",
            "## Provenance review",
            "",
            f"- PROVENANCE_REVIEW_COUNT: {counts['PROVENANCE_REVIEW_COUNT']}",
            f"- CONFIRMED_CURSOR_COUNT: {provenance_plan['counts']['CONFIRMED_CURSOR_COUNT']}",
            f"- CONFIRMED_OTHER_AGENT_COUNT: {provenance_plan['counts']['CONFIRMED_OTHER_AGENT_COUNT']}",
            f"- CONFIRMED_CHATGPT_COUNT: {provenance_plan['counts']['CONFIRMED_CHATGPT_COUNT']}",
            "- Metadata hints never confirm an authoring origin.",
            "",
            "## Import readiness",
            "",
            f"- IMPORT_READINESS_CANDIDATE_COUNT: {counts['IMPORT_READINESS_CANDIDATE_COUNT']}",
            f"- ALL_APPROVED_FALSE: {counts['ALL_APPROVED_FALSE']}",
            f"- ALL_VERIFICATION_NOT_STARTED: {counts['ALL_VERIFICATION_NOT_STARTED']}",
            f"- ALL_IMPORT_READY_FALSE: {counts['ALL_IMPORT_READY_FALSE']}",
            f"- APPROVED_TRUE_COUNT: {readiness_counts['APPROVED_TRUE_COUNT']}",
            f"- IMPORT_READY_TRUE_COUNT: {readiness_counts['IMPORT_READY_TRUE_COUNT']}",
            "",
            "## Safety",
            "",
            "- Report bodies were not opened, read, decoded, or stored.",
            "- No content hash was computed.",
            "- No real import, production write, or git push was performed by this script.",
            "- No approved or import-ready manifest was produced.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(result: dict, output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> dict:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    paths = {
        "duplicate_verification_plan": target / DUPLICATE_PLAN_JSON_NAME,
        "provenance_review_plan": target / PROVENANCE_PLAN_JSON_NAME,
        "verification_queue": target / QUEUE_JSON_NAME,
        "import_readiness_candidate": target / READINESS_JSON_NAME,
        "readiness_summary": target / SUMMARY_MD_NAME,
    }
    for key in (
        "duplicate_verification_plan",
        "provenance_review_plan",
        "verification_queue",
        "import_readiness_candidate",
    ):
        paths[key].write_text(
            json.dumps(result[key], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    paths["readiness_summary"].write_text(
        _render_summary(result) + "\n", encoding="utf-8"
    )
    return {key: str(path) for key, path in paths.items()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unified", default=str(DEFAULT_UNIFIED_PATH))
    parser.add_argument("--duplicate-review", default=str(DEFAULT_DUPLICATE_PATH))
    parser.add_argument("--review-queues", default=str(DEFAULT_QUEUES_PATH))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--generated-at", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = {
        "unified": args.unified,
        "duplicate_review": args.duplicate_review,
        "review_queues": args.review_queues,
        "manifest": args.manifest,
    }
    fixtures: dict = {}
    try:
        for key, path in paths.items():
            fixtures[key] = load_input(path)
    except InputError as exc:
        print(
            json.dumps(
                {"status": exc.code, "path": exc.path, "detail": exc.detail},
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    reconciliation = validate_inputs(fixtures, expected=EXPECTED_BASELINE)
    if not reconciliation["inputs_valid"]:
        print(
            json.dumps(
                {
                    "status": INPUT_COUNT_MISMATCH,
                    "verdict": "BC11E4_INPUT_BLOCKED",
                    "mismatches": reconciliation["mismatches"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    result = build_readiness(
        fixtures,
        expected=EXPECTED_BASELINE,
        generated_at=args.generated_at or None,
    )
    outputs = write_outputs(result, args.output_dir)
    summary = {
        "status": INPUTS_VALID,
        "counts": result["counts"],
        "coverage_status": result["coverage_status"],
        "full_history_asserted": False,
        "outputs": outputs,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
