#!/usr/bin/env python3
"""BC-11E-6 historical agent report import target finalization.

Consumes the BC-11E-5 SHA-256 verification evidence and produces the
content-unique review set, provenance review queue, and unapproved import
manifest review. It never reads an original report body, never recomputes a
hash, never mutates a source file, and never performs an import.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTENT_REVIEW_SCHEMA_VERSION = "tradingai-bc11e6-content-unique-review/v1"
PROVENANCE_QUEUE_SCHEMA_VERSION = "tradingai-bc11e6-provenance-review-queue/v1"
MANIFEST_REVIEW_SCHEMA_VERSION = "tradingai-bc11e6-import-manifest-review/v1"

DEFAULT_OUTPUT_DIR = Path("/tmp/work_bc_audit")
DEFAULT_HASH_RESULTS_PATH = DEFAULT_OUTPUT_DIR / "BC11E5_CONTENT_HASH_RESULTS.json"
DEFAULT_CONFIRMED_PATH = DEFAULT_OUTPUT_DIR / "BC11E5_CONFIRMED_DUPLICATES.json"
DEFAULT_UNIQUE_PATH = DEFAULT_OUTPUT_DIR / "BC11E5_UNIQUE_CONTENT_CANDIDATES.json"
DEFAULT_CONTENT_FINAL_PATH = DEFAULT_OUTPUT_DIR / "BC11E5_CONTENT_VERIFICATION_FINAL.md"
DEFAULT_PROVENANCE_PLAN_PATH = DEFAULT_OUTPUT_DIR / "BC11E4_PROVENANCE_REVIEW_PLAN.json"
DEFAULT_READINESS_PATH = DEFAULT_OUTPUT_DIR / "BC11E4_IMPORT_READINESS_CANDIDATE.json"
DEFAULT_MANIFEST_PATH = DEFAULT_OUTPUT_DIR / "BC11E3_IMPORT_MANIFEST_CANDIDATE.json"

CONTENT_REVIEW_JSON_NAME = "BC11E6_CONTENT_UNIQUE_REVIEW.json"
PROVENANCE_QUEUE_JSON_NAME = "BC11E6_PROVENANCE_REVIEW_QUEUE.json"
MANIFEST_REVIEW_JSON_NAME = "BC11E6_IMPORT_MANIFEST_REVIEW.json"
SUMMARY_MD_NAME = "BC11E6_IMPORT_TARGET_SUMMARY.md"
FINAL_MD_NAME = "BC11E6_IMPORT_TARGET_FINAL.md"

MODE = "OFFLINE_IMPORT_TARGET_FINALIZATION"

TASK_ID = "TRADINGAI-WORK-BC-11E6-IMPORT-TARGET-FINALIZATION-1"
VERDICT_REVIEW_READY = "BC11E6_IMPORT_TARGET_REVIEW_READY"
VERDICT_INPUT_BLOCKED = "BC11E6_INPUT_BLOCKED"
VERDICT_SECURITY_BLOCKED = "BC11E6_SECURITY_BLOCKED"
VERDICT_TEST_FAILED = "BC11E6_TEST_FAILED"

INPUTS_VALID = "INPUTS_VALID"
INPUT_COUNT_MISMATCH = "INPUT_COUNT_MISMATCH"
BLOCKED_MISSING_INPUT = "BLOCKED_MISSING_INPUT"
BLOCKED_INVALID_INPUT = "BLOCKED_INVALID_INPUT"

CONTENT_IDENTICAL = "CONTENT_IDENTICAL"
CONTENT_DIFFERENT = "CONTENT_DIFFERENT"
HASHED = "HASHED"
VERIFIED_CONTENT_STATUSES = frozenset(
    {CONTENT_IDENTICAL, CONTENT_DIFFERENT, HASHED}
)

CLASS_CURSOR = "CURSOR_CANDIDATE"
CLASS_OTHER_AGENT = "OTHER_AGENT_CANDIDATE"
CLASS_CHATGPT = "CHATGPT_CANDIDATE"
CLASS_UNKNOWN = "UNKNOWN_CANDIDATE"

PRIORITY_P0 = "P0"
PRIORITY_P1 = "P1"
PRIORITY_P2 = "P2"
PRIORITY_P3 = "P3"
PRIORITY_ORDER = (PRIORITY_P0, PRIORITY_P1, PRIORITY_P2, PRIORITY_P3)

PROVENANCE_UNKNOWN = "UNKNOWN"
SOURCE_TRUTH_CLASS = "AGENT_REPORTED"
AUTHORITY_SCOPE = "NONE"

ELIGIBLE_CANDIDATE = "ELIGIBLE_CANDIDATE"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
EXCLUDED_BY_POLICY = "EXCLUDED_BY_POLICY"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
ELIGIBILITY_ORDER = (
    ELIGIBLE_CANDIDATE,
    REVIEW_REQUIRED,
    EXCLUDED_BY_POLICY,
    SOURCE_UNAVAILABLE,
)

SECRET_REVIEW_NOT_PERFORMED = "NOT_PERFORMED"
SECRET_SCAN_PASS = "PASS"

REVIEW_NOT_STARTED = "NOT_STARTED"
APPROVAL_NOT_APPROVED = "NOT_APPROVED"

COVERAGE_STATUS = "ADDITIONAL_SOURCE_ROOTS_REQUIRED"
FULL_HISTORY_ASSERTED = False

SOURCE_PRESENT_STATUSES = frozenset(
    {"SOURCE_PRESENT", "PRESENT", "OK", "AVAILABLE"}
)
EXCLUDING_SOURCE_STATUSES = frozenset(
    {"SOURCE_REJECTED", "REJECTED", "EXCLUDED_BY_POLICY"}
)

EXPECTED_BASELINE = {
    "TOTAL_SOURCE_ENTRIES": 6646,
    "DISTINCT_CONTENT_HASHES": 491,
    "SINGLETON_CONTENT_COUNT": 461,
    "CONFIRMED_DUPLICATE_GROUPS": 30,
    "CONFIRMED_DUPLICATE_GROUP_MEMBERS": 6185,
    "ADDITIONAL_COPY_COUNT": 6155,
    "UNIQUE_CONTENT_CANDIDATE_COUNT": 461,
    "PROVENANCE_REVIEW_COUNT": 6646,
    "IMPORT_READINESS_CANDIDATE_COUNT": 6646,
    "MANIFEST_CANDIDATE_COUNT": 6646,
}

REQUIRED_HASH_FIELDS = (
    "source_id",
    "absolute_path",
    "source_root",
    "sha256",
    "verification_status",
)
REQUIRED_CONFIRMED_FIELDS = (
    "content_hash",
    "representative_source_id",
    "member_source_ids",
    "source_paths",
    "member_count",
)
REQUIRED_UNIQUE_FIELDS = ("source_id", "absolute_path", "sha256")
REQUIRED_PROVENANCE_FIELDS = (
    "source_id",
    "provenance_status",
    "classification",
    "source_classification",
    "review_priority",
    "confirmed_cursor",
    "confirmed_other_agent",
    "confirmed_chatgpt",
)
REQUIRED_READINESS_FIELDS = ("source_id",)
REQUIRED_MANIFEST_FIELDS = ("sourceId", "path")


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


def load_text_reference(path: str | Path) -> dict:
    target = Path(path)
    if not target.exists():
        raise InputError(BLOCKED_MISSING_INPUT, str(target), "file does not exist")
    if not target.is_file():
        raise InputError(BLOCKED_INVALID_INPUT, str(target), "not a regular file")
    try:
        size_bytes = target.stat().st_size
    except OSError:
        raise InputError(
            BLOCKED_INVALID_INPUT, str(target), "cannot stat file"
        ) from None
    if size_bytes <= 0:
        raise InputError(BLOCKED_INVALID_INPUT, str(target), "file is empty")
    return {"path": str(target), "exists": True, "size_bytes": size_bytes}


def _require(condition: bool, origin: str, detail: str) -> None:
    if not condition:
        raise InputError(BLOCKED_INVALID_INPUT, origin, detail)


def _require_fields(entries: list, fields: tuple[str, ...], origin: str) -> None:
    for index, entry in enumerate(entries):
        _require(isinstance(entry, dict), origin, f"entry {index} is not an object")
        missing = [key for key in fields if key not in entry]
        _require(
            not missing,
            origin,
            f"entry {index} missing fields: {','.join(missing)}",
        )


def validate_shapes(fixtures: dict) -> None:
    hash_results = fixtures["hash_results"]
    confirmed = fixtures["confirmed_duplicates"]
    unique = fixtures["unique_content_candidates"]
    provenance = fixtures["provenance_plan"]
    readiness = fixtures["readiness"]
    manifest = fixtures["manifest"]

    _require(
        isinstance(hash_results.get("entries"), list),
        "hash_results",
        "entries is not a list",
    )
    _require_fields(hash_results["entries"], REQUIRED_HASH_FIELDS, "hash_results")

    _require(
        isinstance(confirmed.get("groups"), list),
        "confirmed_duplicates",
        "groups is not a list",
    )
    _require_fields(confirmed["groups"], REQUIRED_CONFIRMED_FIELDS, "confirmed_duplicates")

    _require(
        isinstance(unique.get("entries"), list),
        "unique_content_candidates",
        "entries is not a list",
    )
    _require_fields(unique["entries"], REQUIRED_UNIQUE_FIELDS, "unique_content_candidates")

    _require(
        isinstance(provenance.get("entries"), list),
        "provenance_plan",
        "entries is not a list",
    )
    _require_fields(provenance["entries"], REQUIRED_PROVENANCE_FIELDS, "provenance_plan")

    _require(
        isinstance(readiness.get("entries"), list),
        "readiness",
        "entries is not a list",
    )
    _require_fields(readiness["entries"], REQUIRED_READINESS_FIELDS, "readiness")

    _require(
        isinstance(manifest.get("entries"), list),
        "manifest",
        "entries is not a list",
    )
    _require_fields(manifest["entries"], REQUIRED_MANIFEST_FIELDS, "manifest")

    _require(
        isinstance(fixtures.get("content_final"), dict),
        "content_final",
        "content final reference is not an object",
    )


def _mismatch(key: str, expected: object, actual: object, detail: str = "") -> dict:
    return {
        "key": key,
        "expected": expected,
        "actual": actual,
        "match": expected == actual,
        "detail": detail,
    }


def _hash_groups(hash_entries: list[dict]) -> dict[str, list[str]]:
    by_hash: dict[str, list[str]] = {}
    for entry in hash_entries:
        sha256 = entry.get("sha256")
        if not sha256:
            continue
        by_hash.setdefault(str(sha256), []).append(str(entry["source_id"]))
    for members in by_hash.values():
        members.sort()
    return by_hash


def compute_counts(fixtures: dict) -> dict:
    hash_entries = fixtures["hash_results"]["entries"]
    confirmed = fixtures["confirmed_duplicates"]["groups"]
    unique = fixtures["unique_content_candidates"]["entries"]
    by_hash = _hash_groups(hash_entries)
    group_members = sum(len(members) for members in by_hash.values() if len(members) > 1)
    additional = sum(
        max(len(members) - 1, 0) for members in by_hash.values() if len(members) > 1
    )
    return {
        "TOTAL_SOURCE_ENTRIES": len(hash_entries),
        "DISTINCT_CONTENT_HASHES": len(by_hash),
        "SINGLETON_CONTENT_COUNT": sum(
            1 for members in by_hash.values() if len(members) == 1
        ),
        "CONFIRMED_DUPLICATE_GROUPS": len(confirmed),
        "CONFIRMED_DUPLICATE_GROUP_MEMBERS": group_members,
        "ADDITIONAL_COPY_COUNT": additional,
        "UNIQUE_CONTENT_CANDIDATE_COUNT": len(unique),
        "SOURCE_REFERENCE_COUNT": sum(len(members) for members in by_hash.values()),
    }


def validate_inputs(fixtures: dict, *, expected: dict | None = None) -> dict:
    validate_shapes(fixtures)
    expected = expected or {}

    hash_entries = fixtures["hash_results"]["entries"]
    confirmed = fixtures["confirmed_duplicates"]["groups"]
    unique = fixtures["unique_content_candidates"]["entries"]
    provenance = fixtures["provenance_plan"]["entries"]
    readiness = fixtures["readiness"]["entries"]
    manifest = fixtures["manifest"]["entries"]

    counts = compute_counts(fixtures)
    hash_ids = [str(entry["source_id"]) for entry in hash_entries]
    hash_id_set = set(hash_ids)
    _require(
        len(hash_ids) == len(hash_id_set),
        "hash_results",
        "duplicate source_id values present",
    )
    _require(
        all(entry.get("sha256") for entry in hash_entries),
        "hash_results",
        "a source entry has no sha256",
    )

    group_hashes: set[str] = set()
    group_member_ids: list[str] = []
    for index, group in enumerate(confirmed):
        content_hash = str(group["content_hash"])
        _require(
            content_hash not in group_hashes,
            "confirmed_duplicates",
            f"group {index} repeats a content hash",
        )
        group_hashes.add(content_hash)
        members = [str(item) for item in group["member_source_ids"]]
        _require(
            int(group["member_count"]) == len(members),
            "confirmed_duplicates",
            f"group {index} member_count mismatch",
        )
        _require(
            len(group["source_paths"]) == len(members),
            "confirmed_duplicates",
            f"group {index} source_paths count mismatch",
        )
        _require(
            str(group["representative_source_id"]) in members,
            "confirmed_duplicates",
            f"group {index} representative is not a member",
        )
        group_member_ids.extend(members)

    _require(
        len(group_member_ids) == len(set(group_member_ids)),
        "confirmed_duplicates",
        "a source_id appears in more than one duplicate group",
    )

    unique_ids = [str(entry["source_id"]) for entry in unique]
    unique_hashes = {str(entry["sha256"]) for entry in unique}
    _require(
        len(unique_ids) == len(set(unique_ids)),
        "unique_content_candidates",
        "duplicate source_id values present",
    )
    _require(
        len(unique_hashes) == len(unique),
        "unique_content_candidates",
        "duplicate content hashes present",
    )
    _require(
        not (unique_hashes & group_hashes),
        "unique_content_candidates",
        "a unique content hash is also a duplicate group",
    )

    preserved_ids = set(unique_ids) | set(group_member_ids)
    _require(
        preserved_ids == hash_id_set,
        "hash_results",
        "content-unique source set does not cover every source_id",
    )
    _require(
        len(preserved_ids) == counts["TOTAL_SOURCE_ENTRIES"],
        "hash_results",
        "source reference count mismatch",
    )

    provenance_ids = [str(entry["source_id"]) for entry in provenance]
    _require(
        len(provenance_ids) == len(set(provenance_ids)),
        "provenance_plan",
        "duplicate source_id values present",
    )
    _require(
        set(provenance_ids) == hash_id_set,
        "provenance_plan",
        "provenance review does not cover every source_id",
    )

    readiness_ids = [str(entry["source_id"]) for entry in readiness]
    _require(
        len(readiness_ids) == len(set(readiness_ids)),
        "readiness",
        "duplicate source_id values present",
    )
    _require(
        set(readiness_ids) == hash_id_set,
        "readiness",
        "readiness candidate does not cover every source_id",
    )

    manifest_ids = [str(entry["sourceId"]) for entry in manifest]
    _require(
        len(manifest_ids) == len(set(manifest_ids)),
        "manifest",
        "duplicate sourceId values present",
    )
    _require(
        set(manifest_ids) == hash_id_set,
        "manifest",
        "manifest candidate does not cover every source_id",
    )

    comparisons: list[dict] = []

    def _cmp(key: str, actual: object) -> None:
        if key in expected:
            comparisons.append(_mismatch(key, expected[key], actual))

    _cmp("TOTAL_SOURCE_ENTRIES", counts["TOTAL_SOURCE_ENTRIES"])
    _cmp("DISTINCT_CONTENT_HASHES", counts["DISTINCT_CONTENT_HASHES"])
    _cmp("SINGLETON_CONTENT_COUNT", counts["SINGLETON_CONTENT_COUNT"])
    _cmp("CONFIRMED_DUPLICATE_GROUPS", counts["CONFIRMED_DUPLICATE_GROUPS"])
    _cmp(
        "CONFIRMED_DUPLICATE_GROUP_MEMBERS",
        counts["CONFIRMED_DUPLICATE_GROUP_MEMBERS"],
    )
    _cmp("ADDITIONAL_COPY_COUNT", counts["ADDITIONAL_COPY_COUNT"])
    _cmp("UNIQUE_CONTENT_CANDIDATE_COUNT", counts["UNIQUE_CONTENT_CANDIDATE_COUNT"])
    _cmp("PROVENANCE_REVIEW_COUNT", len(provenance))
    _cmp("IMPORT_READINESS_CANDIDATE_COUNT", len(readiness))
    _cmp("MANIFEST_CANDIDATE_COUNT", len(manifest))
    comparisons.append(
        _mismatch(
            "CONTENT_UNIQUE_HASH_COUNT",
            counts["DISTINCT_CONTENT_HASHES"],
            counts["SINGLETON_CONTENT_COUNT"]
            + counts["CONFIRMED_DUPLICATE_GROUPS"],
            "singletons plus duplicate groups",
        )
    )
    comparisons.append(
        _mismatch(
            "SOURCE_REFERENCE_RECONCILIATION",
            counts["TOTAL_SOURCE_ENTRIES"],
            counts["DISTINCT_CONTENT_HASHES"] + counts["ADDITIONAL_COPY_COUNT"],
            "unique content plus additional copies",
        )
    )
    comparisons.append(
        _mismatch(
            "GROUP_MEMBER_RECONCILIATION",
            counts["TOTAL_SOURCE_ENTRIES"],
            counts["SINGLETON_CONTENT_COUNT"]
            + counts["CONFIRMED_DUPLICATE_GROUP_MEMBERS"],
            "singletons plus duplicate group members",
        )
    )

    mismatches = [item for item in comparisons if not item["match"]]
    return {
        "status": INPUTS_VALID if not mismatches else INPUT_COUNT_MISMATCH,
        "inputs_valid": not mismatches,
        "counts": counts,
        "comparisons": comparisons,
        "mismatches": mismatches,
    }


def _priority_for(classifications: set[str]) -> str:
    if CLASS_CURSOR in classifications:
        return PRIORITY_P0
    if CLASS_OTHER_AGENT in classifications:
        return PRIORITY_P1
    if CLASS_CHATGPT in classifications:
        return PRIORITY_P2
    return PRIORITY_P3


def _is_absolute_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        return Path(value).is_absolute()
    except (OSError, ValueError):
        return False


def _member_availability(
    member_id: str,
    *,
    content_hash: str,
    hash_by_id: dict[str, dict],
    manifest_by_id: dict[str, dict],
) -> tuple[bool, str]:
    entry = hash_by_id.get(member_id)
    if entry is None:
        return False, "MEMBER_NOT_IN_HASH_RESULTS"
    if str(entry.get("sha256") or "") != content_hash:
        return False, "CONTENT_HASH_MISMATCH"
    if entry.get("verification_status") not in VERIFIED_CONTENT_STATUSES:
        return False, "CONTENT_NOT_VERIFIED"
    if not _is_absolute_path(entry.get("absolute_path")):
        return False, "SOURCE_PATH_NOT_ABSOLUTE"
    if not _is_absolute_path(entry.get("source_root")):
        return False, "SOURCE_ROOT_NOT_ABSOLUTE"
    manifest_entry = manifest_by_id.get(member_id, {})
    status = str(manifest_entry.get("sourceStatus") or "")
    if status in {"SOURCE_MISSING", "SOURCE_MISSING_SINCE_INVENTORY"}:
        return False, "SOURCE_MISSING"
    return True, ""


def _policy_exclusion_reasons(
    members: list[str],
    *,
    provenance_by_id: dict[str, dict],
    readiness_by_id: dict[str, dict],
    manifest_by_id: dict[str, dict],
) -> list[str]:
    reasons: list[str] = []
    for member_id in members:
        provenance = provenance_by_id.get(member_id, {})
        readiness = readiness_by_id.get(member_id, {})
        manifest = manifest_by_id.get(member_id, {})
        classification = str(provenance.get("classification") or "")
        if classification == EXCLUDED_BY_POLICY:
            reasons.append(f"{member_id}:CLASSIFICATION_EXCLUDED_BY_POLICY")
        if str(readiness.get("import_eligibility") or "") == EXCLUDED_BY_POLICY:
            reasons.append(f"{member_id}:READINESS_EXCLUDED_BY_POLICY")
        if str(manifest.get("sourceStatus") or "") in EXCLUDING_SOURCE_STATUSES:
            reasons.append(f"{member_id}:SOURCE_STATUS_EXCLUDED_BY_POLICY")
    return sorted(set(reasons))


def _eligibility_for(
    *,
    members: list[str],
    content_hash: str,
    hash_by_id: dict[str, dict],
    provenance_by_id: dict[str, dict],
    readiness_by_id: dict[str, dict],
    manifest_by_id: dict[str, dict],
    secret_review_status: str,
) -> tuple[str, list[str]]:
    reasons = _policy_exclusion_reasons(
        members,
        provenance_by_id=provenance_by_id,
        readiness_by_id=readiness_by_id,
        manifest_by_id=manifest_by_id,
    )
    if reasons:
        return EXCLUDED_BY_POLICY, reasons

    unavailable: list[str] = []
    for member_id in members:
        available, reason = _member_availability(
            member_id,
            content_hash=content_hash,
            hash_by_id=hash_by_id,
            manifest_by_id=manifest_by_id,
        )
        if not available:
            unavailable.append(f"{member_id}:{reason}")
    if unavailable:
        return SOURCE_UNAVAILABLE, sorted(unavailable)

    if secret_review_status != SECRET_SCAN_PASS:
        return REVIEW_REQUIRED, ["SECRET_REVIEW_NOT_PERFORMED"]
    return ELIGIBLE_CANDIDATE, []


def build_content_records(fixtures: dict, *, generated_at: str) -> list[dict]:
    hash_entries = fixtures["hash_results"]["entries"]
    confirmed = fixtures["confirmed_duplicates"]["groups"]
    unique = fixtures["unique_content_candidates"]["entries"]
    provenance = fixtures["provenance_plan"]["entries"]
    readiness = fixtures["readiness"]["entries"]
    manifest = fixtures["manifest"]["entries"]

    hash_by_id = {str(entry["source_id"]): entry for entry in hash_entries}
    provenance_by_id = {str(entry["source_id"]): entry for entry in provenance}
    readiness_by_id = {str(entry["source_id"]): entry for entry in readiness}
    manifest_by_id = {str(entry["sourceId"]): entry for entry in manifest}
    groups_by_hash = {str(group["content_hash"]): group for group in confirmed}
    unique_by_hash = {str(entry["sha256"]): entry for entry in unique}

    all_hashes = sorted(
        set(groups_by_hash)
        | set(unique_by_hash)
        | {str(entry["sha256"]) for entry in hash_entries}
    )

    records: list[dict] = []
    for content_hash in all_hashes:
        group = groups_by_hash.get(content_hash)
        unique_entry = unique_by_hash.get(content_hash)
        if group is not None:
            members = sorted(str(item) for item in group["member_source_ids"])
            representative = str(group["representative_source_id"])
            record_kind = "CONFIRMED_DUPLICATE_GROUP"
        elif unique_entry is not None:
            members = [str(unique_entry["source_id"])]
            representative = members[0]
            record_kind = "UNIQUE_CONTENT"
        else:
            raise InputError(
                BLOCKED_INVALID_INPUT,
                "content_hash",
                f"{content_hash} is not classified as unique or duplicate",
            )

        _require(
            representative in members,
            "representative",
            f"{content_hash} representative is not a member",
        )

        member_entries: list[dict] = []
        source_paths: list[str] = []
        source_roots: list[str] = []
        classifications: dict[str, str] = {}
        source_classifications: dict[str, str] = {}
        member_provenance: list[dict] = []
        classification_set: set[str] = set()

        for member_id in members:
            hash_entry = hash_by_id.get(member_id)
            if hash_entry is None:
                raise InputError(
                    BLOCKED_INVALID_INPUT,
                    "hash_results",
                    f"member {member_id} has no hash entry",
                )
            provenance_entry = provenance_by_id.get(member_id)
            if provenance_entry is None:
                raise InputError(
                    BLOCKED_INVALID_INPUT,
                    "provenance_plan",
                    f"member {member_id} has no provenance entry",
                )
            classification = str(
                provenance_entry.get("classification") or CLASS_UNKNOWN
            )
            source_classification = str(
                provenance_entry.get("source_classification")
                or "UNKNOWN_REPORT_CANDIDATE"
            )
            classifications[member_id] = classification
            source_classifications[member_id] = source_classification
            classification_set.add(classification)
            path = str(hash_entry.get("absolute_path") or "")
            source_paths.append(path)
            source_roots.append(str(hash_entry.get("source_root") or ""))
            member_provenance.append(
                {
                    "source_id": member_id,
                    "classification": classification,
                    "source_classification": source_classification,
                    "provenance_status": str(
                        provenance_entry.get("provenance_status")
                        or PROVENANCE_UNKNOWN
                    ),
                    "review_priority": str(
                        provenance_entry.get("review_priority") or PRIORITY_P3
                    ),
                    "confirmed_cursor": bool(
                        provenance_entry.get("confirmed_cursor")
                    ),
                    "confirmed_other_agent": bool(
                        provenance_entry.get("confirmed_other_agent")
                    ),
                    "confirmed_chatgpt": bool(
                        provenance_entry.get("confirmed_chatgpt")
                    ),
                }
            )
            member_entries.append(hash_entry)

        if group is not None:
            recorded_paths = {str(item) for item in group.get("source_paths", [])}
            if recorded_paths:
                _require(
                    recorded_paths == set(source_paths),
                    "confirmed_duplicates",
                    f"{content_hash} source_paths do not match hash results",
                )

        classification_counts: dict[str, int] = {}
        for classification in classifications.values():
            classification_counts[classification] = (
                classification_counts.get(classification, 0) + 1
            )

        priority = _priority_for(classification_set)
        secret_review_status = SECRET_REVIEW_NOT_PERFORMED
        import_eligibility, eligibility_reasons = _eligibility_for(
            members=members,
            content_hash=content_hash,
            hash_by_id=hash_by_id,
            provenance_by_id=provenance_by_id,
            readiness_by_id=readiness_by_id,
            manifest_by_id=manifest_by_id,
            secret_review_status=secret_review_status,
        )

        records.append(
            {
                "content_hash": content_hash,
                "record_kind": record_kind,
                "representative_source_id": representative,
                "member_source_ids": list(members),
                "member_count": len(members),
                "source_paths": source_paths,
                "source_roots": source_roots,
                "content_hash_algorithm": "SHA-256",
                "hash_verified": all(
                    str(entry.get("sha256") or "") == content_hash
                    for entry in member_entries
                ),
                "source_classifications": dict(sorted(source_classifications.items())),
                "classifications": sorted(classification_set),
                "classification_counts": dict(sorted(classification_counts.items())),
                "member_provenance": member_provenance,
                "source_classification": source_classifications.get(
                    representative, "UNKNOWN_REPORT_CANDIDATE"
                ),
                "provenance_status": PROVENANCE_UNKNOWN,
                "confirmed_cursor": False,
                "confirmed_other_agent": False,
                "confirmed_chatgpt": False,
                "source_truth_class": SOURCE_TRUTH_CLASS,
                "authority_scope": AUTHORITY_SCOPE,
                "historical_record": True,
                "historical_runtime_authority": False,
                "review_priority": priority,
                "review_status": REVIEW_NOT_STARTED,
                "review_required": True,
                "secret_review_status": secret_review_status,
                "import_eligibility": import_eligibility,
                "eligibility_reasons": eligibility_reasons,
                "approval_status": APPROVAL_NOT_APPROVED,
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "generated_at": generated_at,
            }
        )

    records.sort(key=lambda record: record["content_hash"])
    return records


def _eligibility_counts(records: list[dict]) -> dict[str, int]:
    counts = {status: 0 for status in ELIGIBILITY_ORDER}
    for record in records:
        status = record["import_eligibility"]
        counts[status] = counts.get(status, 0) + 1
    return counts


def _priority_counts(records: list[dict]) -> dict[str, int]:
    counts = {priority: 0 for priority in PRIORITY_ORDER}
    for record in records:
        priority = record["review_priority"]
        counts[priority] = counts.get(priority, 0) + 1
    return counts


def _all_false(records: list[dict], field: str) -> bool:
    return all(record[field] is False for record in records)


def build_content_unique_review(
    fixtures: dict, records: list[dict], *, generated_at: str
) -> dict:
    counts = compute_counts(fixtures)
    eligibility = _eligibility_counts(records)
    priority = _priority_counts(records)
    return {
        "schema_version": CONTENT_REVIEW_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "generated_at": generated_at,
        "mode": MODE,
        "real_import_executed": False,
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "content_read": False,
        "hash_recalculated": False,
        "source_body_stored": False,
        "coverage_status": COVERAGE_STATUS,
        "full_history_asserted": FULL_HISTORY_ASSERTED,
        "provenance_status": PROVENANCE_UNKNOWN,
        "authority_scope": AUTHORITY_SCOPE,
        "source_truth_class": SOURCE_TRUTH_CLASS,
        "historical_runtime_authority": False,
        "counts": {
            "TOTAL_SOURCE_ENTRIES": counts["TOTAL_SOURCE_ENTRIES"],
            "CONTENT_UNIQUE_COUNT": len(records),
            "DISTINCT_CONTENT_HASHES": counts["DISTINCT_CONTENT_HASHES"],
            "SINGLETON_CONTENT_COUNT": counts["SINGLETON_CONTENT_COUNT"],
            "CONFIRMED_DUPLICATE_GROUPS": counts["CONFIRMED_DUPLICATE_GROUPS"],
            "CONFIRMED_DUPLICATE_GROUP_MEMBERS": counts[
                "CONFIRMED_DUPLICATE_GROUP_MEMBERS"
            ],
            "ADDITIONAL_COPY_COUNT": counts["ADDITIONAL_COPY_COUNT"],
            "SOURCE_REFERENCE_COUNT": counts["SOURCE_REFERENCE_COUNT"],
            "PROVENANCE_UNKNOWN_COUNT": sum(
                1 for record in records if record["provenance_status"] == PROVENANCE_UNKNOWN
            ),
            "SECRET_REVIEW_NOT_PERFORMED_COUNT": sum(
                1
                for record in records
                if record["secret_review_status"] == SECRET_REVIEW_NOT_PERFORMED
            ),
            "ELIGIBLE_CANDIDATE_COUNT": eligibility[ELIGIBLE_CANDIDATE],
            "REVIEW_REQUIRED_COUNT": eligibility[REVIEW_REQUIRED],
            "EXCLUDED_BY_POLICY_COUNT": eligibility[EXCLUDED_BY_POLICY],
            "SOURCE_UNAVAILABLE_COUNT": eligibility[SOURCE_UNAVAILABLE],
            "PRIORITY_COUNTS": priority,
            "ALL_APPROVED_FALSE": _all_false(records, "approved"),
            "ALL_IMPORT_READY_FALSE": _all_false(records, "import_ready"),
            "ALL_REAL_IMPORT_ALLOWED_FALSE": _all_false(
                records, "real_import_allowed"
            ),
        },
        "records": records,
    }


def build_provenance_review_queue(
    records: list[dict], *, generated_at: str
) -> dict:
    entries = []
    for record in records:
        entries.append(
            {
                "content_hash": record["content_hash"],
                "representative_source_id": record["representative_source_id"],
                "member_source_ids": list(record["member_source_ids"]),
                "source_paths": list(record["source_paths"]),
                "member_count": record["member_count"],
                "review_priority": record["review_priority"],
                "classifications": list(record["classifications"]),
                "classification_counts": dict(record["classification_counts"]),
                "source_classifications": dict(record["source_classifications"]),
                "member_provenance": list(record["member_provenance"]),
                "provenance_status": PROVENANCE_UNKNOWN,
                "confirmed_cursor": False,
                "confirmed_other_agent": False,
                "confirmed_chatgpt": False,
                "review_status": REVIEW_NOT_STARTED,
                "review_required": True,
                "source_truth_class": SOURCE_TRUTH_CLASS,
                "authority_scope": AUTHORITY_SCOPE,
                "historical_record": True,
                "historical_runtime_authority": False,
            }
        )
    entries.sort(key=lambda entry: entry["content_hash"])
    return {
        "schema_version": PROVENANCE_QUEUE_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "generated_at": generated_at,
        "mode": MODE,
        "real_import_executed": False,
        "content_read": False,
        "provenance_policy": (
            "Metadata hints never confirm an authoring origin. Every confirmation "
            "flag stays false until an explicit operator provenance review."
        ),
        "counts": {
            "PROVENANCE_REVIEW_COUNT": len(entries),
            "PRIORITY_COUNTS": _priority_counts(records),
            "CONFIRMED_CURSOR_COUNT": 0,
            "CONFIRMED_OTHER_AGENT_COUNT": 0,
            "CONFIRMED_CHATGPT_COUNT": 0,
            "ALL_REVIEW_NOT_STARTED": all(
                entry["review_status"] == REVIEW_NOT_STARTED for entry in entries
            ),
        },
        "entries": entries,
    }


def build_import_manifest_review(
    records: list[dict], *, generated_at: str
) -> dict:
    entries = []
    for record in records:
        entries.append(
            {
                "content_hash": record["content_hash"],
                "representative_source_id": record["representative_source_id"],
                "member_source_ids": list(record["member_source_ids"]),
                "source_paths": list(record["source_paths"]),
                "member_count": record["member_count"],
                "source_classification": record["source_classification"],
                "classifications": list(record["classifications"]),
                "provenance_status": PROVENANCE_UNKNOWN,
                "import_eligibility": record["import_eligibility"],
                "eligibility_reasons": list(record["eligibility_reasons"]),
                "review_priority": record["review_priority"],
                "review_status": REVIEW_NOT_STARTED,
                "secret_review_status": SECRET_REVIEW_NOT_PERFORMED,
                "approval_status": APPROVAL_NOT_APPROVED,
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "source_truth_class": SOURCE_TRUTH_CLASS,
                "authority_scope": AUTHORITY_SCOPE,
                "historical_record": True,
                "historical_runtime_authority": False,
            }
        )
    entries.sort(key=lambda entry: entry["content_hash"])
    eligibility = _eligibility_counts(records)
    return {
        "schema_version": MANIFEST_REVIEW_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "generated_at": generated_at,
        "mode": MODE,
        "manifest_kind": "IMPORT_MANIFEST_REVIEW",
        "real_import_executed": False,
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "operator_review_required": True,
        "note": (
            "Unapproved import manifest review. No record may be imported until an "
            "operator completes provenance and secret review and explicitly approves "
            "a separate manifest."
        ),
        "coverage_status": COVERAGE_STATUS,
        "full_history_asserted": FULL_HISTORY_ASSERTED,
        "counts": {
            "IMPORT_MANIFEST_COUNT": len(entries),
            "ELIGIBLE_CANDIDATE_COUNT": eligibility[ELIGIBLE_CANDIDATE],
            "REVIEW_REQUIRED_COUNT": eligibility[REVIEW_REQUIRED],
            "EXCLUDED_BY_POLICY_COUNT": eligibility[EXCLUDED_BY_POLICY],
            "SOURCE_UNAVAILABLE_COUNT": eligibility[SOURCE_UNAVAILABLE],
            "SECRET_REVIEW_NOT_PERFORMED_COUNT": sum(
                1
                for entry in entries
                if entry["secret_review_status"] == SECRET_REVIEW_NOT_PERFORMED
            ),
            "ALL_APPROVED_FALSE": all(entry["approved"] is False for entry in entries),
            "ALL_IMPORT_READY_FALSE": all(
                entry["import_ready"] is False for entry in entries
            ),
            "ALL_REAL_IMPORT_ALLOWED_FALSE": all(
                entry["real_import_allowed"] is False for entry in entries
            ),
        },
        "entries": entries,
    }


def build_import_target_review(
    fixtures: dict,
    *,
    expected: dict | None = None,
    generated_at: str | None = None,
) -> dict:
    timestamp = generated_at or _now_iso()
    validation = validate_inputs(fixtures, expected=expected or {})
    if not validation["inputs_valid"]:
        raise InputError(
            INPUT_COUNT_MISMATCH,
            "inputs",
            "; ".join(item["key"] for item in validation["mismatches"]),
        )
    records = build_content_records(fixtures, generated_at=timestamp)
    content_review = build_content_unique_review(
        fixtures, records, generated_at=timestamp
    )
    provenance_queue = build_provenance_review_queue(
        records, generated_at=timestamp
    )
    manifest_review = build_import_manifest_review(records, generated_at=timestamp)
    return {
        "task_id": TASK_ID,
        "verdict": VERDICT_REVIEW_READY,
        "generated_at": timestamp,
        "validation": validation,
        "records": records,
        "content_unique_review": content_review,
        "provenance_review_queue": provenance_queue,
        "import_manifest_review": manifest_review,
        "counts": content_review["counts"],
    }


def render_summary(result: dict) -> str:
    counts = result["counts"]
    lines = [
        "# BC-11E-6 Import Target Summary",
        "",
        f"TASK_ID={TASK_ID}",
        f"VERDICT={result['verdict']}",
        f"generated_at={result['generated_at']}",
        "",
        f"TOTAL_SOURCE_ENTRIES={counts['TOTAL_SOURCE_ENTRIES']}",
        f"CONTENT_UNIQUE_COUNT={counts['CONTENT_UNIQUE_COUNT']}",
        f"DISTINCT_CONTENT_HASHES={counts['DISTINCT_CONTENT_HASHES']}",
        f"SINGLETON_CONTENT_COUNT={counts['SINGLETON_CONTENT_COUNT']}",
        f"CONFIRMED_DUPLICATE_GROUPS={counts['CONFIRMED_DUPLICATE_GROUPS']}",
        f"CONFIRMED_DUPLICATE_GROUP_MEMBERS={counts['CONFIRMED_DUPLICATE_GROUP_MEMBERS']}",
        f"ADDITIONAL_COPY_COUNT={counts['ADDITIONAL_COPY_COUNT']}",
        f"SOURCE_REFERENCE_COUNT={counts['SOURCE_REFERENCE_COUNT']}",
        "",
        "## Eligibility",
        "",
        f"ELIGIBLE_CANDIDATE_COUNT={counts['ELIGIBLE_CANDIDATE_COUNT']}",
        f"REVIEW_REQUIRED_COUNT={counts['REVIEW_REQUIRED_COUNT']}",
        f"EXCLUDED_BY_POLICY_COUNT={counts['EXCLUDED_BY_POLICY_COUNT']}",
        f"SOURCE_UNAVAILABLE_COUNT={counts['SOURCE_UNAVAILABLE_COUNT']}",
        f"SECRET_REVIEW_NOT_PERFORMED_COUNT={counts['SECRET_REVIEW_NOT_PERFORMED_COUNT']}",
        "",
        "## Review Priority",
        "",
    ]
    for priority, value in counts["PRIORITY_COUNTS"].items():
        lines.append(f"{priority}_COUNT={value}")
    lines.extend(
        [
            "",
            "## Approval State",
            "",
            f"ALL_APPROVED_FALSE={str(counts['ALL_APPROVED_FALSE']).upper()}",
            f"ALL_IMPORT_READY_FALSE={str(counts['ALL_IMPORT_READY_FALSE']).upper()}",
            f"ALL_REAL_IMPORT_ALLOWED_FALSE={str(counts['ALL_REAL_IMPORT_ALLOWED_FALSE']).upper()}",
            "",
            "## Coverage",
            "",
            f"COVERAGE_STATUS={COVERAGE_STATUS}",
            f"FULL_HISTORY_ASSERTED={str(FULL_HISTORY_ASSERTED).upper()}",
            "",
            "REAL_IMPORT_EXECUTED=NO",
            "SOURCE_BODY_READ=NO",
            "HASH_RECALCULATION=NO",
            "",
        ]
    )
    return "\n".join(lines)


def render_final(result: dict, meta: dict) -> str:
    counts = result["counts"]
    test_results = meta.get("test_results", "PENDING")
    changed_files = meta.get("changed_files", "UNKNOWN")
    commit = meta.get("commit", "NONE")
    lines = [
        "# BC-11E-6 Import Target Final Report",
        "",
        f"TASK_ID={TASK_ID}",
        f"VERDICT={result['verdict']}",
        f"WORKTREE={meta.get('worktree', 'UNKNOWN')}",
        f"BRANCH={meta.get('branch', 'UNKNOWN')}",
        f"HEAD_BEFORE={meta.get('head_before', 'UNKNOWN')}",
        f"HEAD_AFTER={meta.get('head_after', 'UNKNOWN')}",
        "",
        f"TOTAL_SOURCE_ENTRIES={counts['TOTAL_SOURCE_ENTRIES']}",
        f"CONTENT_UNIQUE_COUNT={counts['CONTENT_UNIQUE_COUNT']}",
        f"ADDITIONAL_COPY_COUNT={counts['ADDITIONAL_COPY_COUNT']}",
        f"DUPLICATE_GROUP_COUNT={counts['CONFIRMED_DUPLICATE_GROUPS']}",
        f"PROVENANCE_REVIEW_COUNT={result['provenance_review_queue']['counts']['PROVENANCE_REVIEW_COUNT']}",
        f"IMPORT_MANIFEST_COUNT={result['import_manifest_review']['counts']['IMPORT_MANIFEST_COUNT']}",
        f"ELIGIBLE_CANDIDATE_COUNT={counts['ELIGIBLE_CANDIDATE_COUNT']}",
        f"REVIEW_REQUIRED_COUNT={counts['REVIEW_REQUIRED_COUNT']}",
        f"EXCLUDED_BY_POLICY_COUNT={counts['EXCLUDED_BY_POLICY_COUNT']}",
        f"SOURCE_UNAVAILABLE_COUNT={counts['SOURCE_UNAVAILABLE_COUNT']}",
        f"SECRET_REVIEW_NOT_PERFORMED_COUNT={counts['SECRET_REVIEW_NOT_PERFORMED_COUNT']}",
        f"ALL_APPROVED_FALSE={str(counts['ALL_APPROVED_FALSE']).upper()}",
        f"ALL_IMPORT_READY_FALSE={str(counts['ALL_IMPORT_READY_FALSE']).upper()}",
        f"ALL_REAL_IMPORT_ALLOWED_FALSE={str(counts['ALL_REAL_IMPORT_ALLOWED_FALSE']).upper()}",
        "",
        f"COVERAGE_STATUS={COVERAGE_STATUS}",
        f"FULL_HISTORY_ASSERTED={str(FULL_HISTORY_ASSERTED).upper()}",
        "",
        "TEST_RESULTS=" + test_results,
        "CHANGED_FILES=" + changed_files,
        "COMMIT=" + commit,
        "PRODUCTION_DB_UNCHANGED=YES",
        "CANONICAL_UNCHANGED=YES",
        "WORK_AA_UNCHANGED=YES",
        "BB_CC_UNCHANGED=YES",
        "REAL_IMPORT_EXECUTED=NO",
        "GIT_PUSH=NO",
        "PRODUCTION_RESTART=NO",
        "",
        "NEXT_RECOMMENDED_TASK="
        + meta.get(
            "next_recommended_task",
            "BC-11E-7 PROVENANCE EVIDENCE REVIEW AND SECRET SCAN FOR 491 CONTENT-UNIQUE RECORDS",
        ),
        "",
    ]
    return "\n".join(lines)


def write_outputs(
    result: dict, *, output_dir: str | Path = DEFAULT_OUTPUT_DIR, meta: dict | None = None
) -> dict:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    meta = meta or {}
    paths = {
        "content_unique_review": target / CONTENT_REVIEW_JSON_NAME,
        "provenance_review_queue": target / PROVENANCE_QUEUE_JSON_NAME,
        "import_manifest_review": target / MANIFEST_REVIEW_JSON_NAME,
        "import_target_summary": target / SUMMARY_MD_NAME,
        "import_target_final": target / FINAL_MD_NAME,
    }
    paths["content_unique_review"].write_text(
        json.dumps(result["content_unique_review"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["provenance_review_queue"].write_text(
        json.dumps(result["provenance_review_queue"], indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    paths["import_manifest_review"].write_text(
        json.dumps(result["import_manifest_review"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["import_target_summary"].write_text(
        render_summary(result) + "\n", encoding="utf-8"
    )
    paths["import_target_final"].write_text(
        render_final(result, meta) + "\n", encoding="utf-8"
    )
    return {key: str(path) for key, path in paths.items()}


INPUT_KEYS = (
    "hash_results",
    "confirmed_duplicates",
    "unique_content_candidates",
    "provenance_plan",
    "readiness",
    "manifest",
)


def load_fixtures(paths: dict[str, str | Path]) -> dict:
    fixtures: dict = {}
    for key in INPUT_KEYS:
        fixtures[key] = load_input(paths[key])
    fixtures["content_final"] = load_text_reference(paths["content_final"])
    return fixtures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hash-results", default=str(DEFAULT_HASH_RESULTS_PATH))
    parser.add_argument("--confirmed-duplicates", default=str(DEFAULT_CONFIRMED_PATH))
    parser.add_argument("--unique-content-candidates", default=str(DEFAULT_UNIQUE_PATH))
    parser.add_argument("--content-verification-final", default=str(DEFAULT_CONTENT_FINAL_PATH))
    parser.add_argument("--provenance-plan", default=str(DEFAULT_PROVENANCE_PLAN_PATH))
    parser.add_argument("--readiness", default=str(DEFAULT_READINESS_PATH))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--worktree", default="UNKNOWN")
    parser.add_argument("--branch", default="UNKNOWN")
    parser.add_argument("--head-before", default="UNKNOWN")
    parser.add_argument("--head-after", default="UNKNOWN")
    parser.add_argument("--test-results", default="PENDING")
    parser.add_argument("--changed-files", default="UNKNOWN")
    parser.add_argument("--commit", default="NONE")
    parser.add_argument("--next-recommended-task", default="")
    return parser


def _fixture_paths(args: argparse.Namespace) -> dict[str, str | Path]:
    return {
        "hash_results": args.hash_results,
        "confirmed_duplicates": args.confirmed_duplicates,
        "unique_content_candidates": args.unique_content_candidates,
        "content_final": args.content_verification_final,
        "provenance_plan": args.provenance_plan,
        "readiness": args.readiness,
        "manifest": args.manifest,
    }


def _meta_from_args(args: argparse.Namespace) -> dict:
    return {
        "worktree": args.worktree,
        "branch": args.branch,
        "head_before": args.head_before,
        "head_after": args.head_after,
        "test_results": args.test_results,
        "changed_files": args.changed_files,
        "commit": args.commit,
        "next_recommended_task": args.next_recommended_task,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        fixtures = load_fixtures(_fixture_paths(args))
    except InputError as exc:
        print(
            json.dumps(
                {
                    "status": exc.code,
                    "verdict": VERDICT_INPUT_BLOCKED,
                    "path": exc.path,
                    "detail": exc.detail,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    try:
        result = build_import_target_review(
            fixtures,
            expected=EXPECTED_BASELINE,
            generated_at=args.generated_at or None,
        )
    except InputError as exc:
        print(
            json.dumps(
                {
                    "status": exc.code,
                    "verdict": VERDICT_INPUT_BLOCKED,
                    "detail": exc.detail,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    outputs = write_outputs(
        result, output_dir=args.output_dir, meta=_meta_from_args(args)
    )
    print(
        json.dumps(
            {
                "status": INPUTS_VALID,
                "verdict": result["verdict"],
                "counts": result["counts"],
                "outputs": outputs,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
