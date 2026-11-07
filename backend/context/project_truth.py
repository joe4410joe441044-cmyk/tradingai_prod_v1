"""Project / Decision truth registry loader.

The registry is a human-maintained document.  Loading never upgrades an
unconfirmed workstream to ``COMPLETE`` or ``DEPLOYED`` and never fabricates an
owner, branch, or verification timestamp.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import ValidationError

from .schema import (
    PROJECT_SCHEMA_VERSION,
    Availability,
    Freshness,
    ProjectTruth,
    ProvenanceEntry,
    SectionMeta,
    empty_project_truth,
)

READER_NAME = "project-truth-registry"
DEFAULT_REGISTRY_PATH = Path("docs/ai/PROJECT_STATE.yaml")


def _as_optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("updatedAt must be an ISO-8601 timestamp")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("updatedAt must be timezone-aware")
    return result.astimezone(timezone.utc)


def _meta(
    *,
    path: Path,
    observed_at: datetime,
    availability: Availability,
    detail: str | None = None,
) -> SectionMeta:
    return SectionMeta(
        source=f"file:{path.as_posix()}",
        observedAt=observed_at,
        freshness=Freshness.FRESH if availability is Availability.AVAILABLE else Freshness.UNKNOWN,
        availability=availability,
        provenance=(
            ProvenanceEntry(
                source=f"file:{path.as_posix()}",
                reader=READER_NAME,
                observedAt=observed_at,
                detail=detail,
            ),
        ),
        detail=detail,
    )


def load_project_truth(
    path: str | Path = DEFAULT_REGISTRY_PATH,
    *,
    observed_at: datetime | None = None,
    clock=lambda: datetime.now(timezone.utc),
) -> ProjectTruth:
    """Load and validate the project registry.

    A missing registry is reported as ``UNAVAILABLE`` instead of raising; a
    malformed registry raises so corruption is never silently accepted.
    """

    observed = observed_at if observed_at is not None else clock()
    if (
        not isinstance(observed, datetime)
        or observed.tzinfo is None
        or observed.utcoffset() is None
    ):
        raise ValueError("observed_at must be timezone-aware")
    observed = observed.astimezone(timezone.utc)

    registry_path = Path(path)
    if not registry_path.is_file():
        return empty_project_truth(
            observed,
            availability=Availability.UNAVAILABLE,
            detail="project registry file is missing",
        )

    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError("project registry could not be parsed") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ValueError("project registry root must be a mapping")

    payload = dict(raw)
    payload["updatedAt"] = _as_optional_datetime(payload.get("updatedAt"))
    payload.setdefault("schemaVersion", PROJECT_SCHEMA_VERSION)
    payload["meta"] = _meta(
        path=registry_path,
        observed_at=observed,
        availability=Availability.AVAILABLE,
        detail="validated YAML project registry",
    )
    try:
        return ProjectTruth.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"project registry validation failed: {exc}") from exc


def project_truth_meta(truth: ProjectTruth) -> SectionMeta:
    """Expose the registry meta for section construction."""

    return truth.meta
