"""MM-4F deterministic checkpoint metadata bootstrap."""
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Optional

from .loss_application_models import LossLimitCheckpointMetadata
from .loss_persistence_adapter import (
    LoadStatus,
    LossPersistenceLoadResult,
)
from .loss_persistence_serialization import build_canonical_loss_state_json


class CheckpointMetadataBootstrapStatus(str, Enum):
    MISSING = "MISSING"
    READY = "READY"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    PERSISTENCE_UNAVAILABLE = "PERSISTENCE_UNAVAILABLE"


@dataclass(frozen=True)
class LossLimitCheckpointMetadataBootstrapResult:
    status: CheckpointMetadataBootstrapStatus
    metadata: Optional[LossLimitCheckpointMetadata]
    load_result: Optional[LossPersistenceLoadResult] = field(repr=False)
    canonical_state: Optional[bytes] = field(default=None, repr=False)
    safe_reason: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(
            self, "status", CheckpointMetadataBootstrapStatus(self.status)
        )
        if self.metadata is not None and not isinstance(
            self.metadata, LossLimitCheckpointMetadata
        ):
            raise TypeError("metadata invalid")
        if self.load_result is not None and not isinstance(
            self.load_result, LossPersistenceLoadResult
        ):
            raise TypeError("load result invalid")
        if self.canonical_state is not None and not isinstance(
            self.canonical_state, bytes
        ):
            raise TypeError("canonical state invalid")

    def to_dict(self):
        return {
            "status": self.status.value,
            "metadata": self.metadata.to_dict() if self.metadata else None,
            "safe_reason": self.safe_reason,
        }


def bootstrap_loss_limit_checkpoint_metadata(persistence_adapter, configured_metadata):
    if configured_metadata is not None and not isinstance(
        configured_metadata, LossLimitCheckpointMetadata
    ):
        raise TypeError("configured metadata invalid")
    loader = getattr(persistence_adapter, "load", None)
    if not callable(loader):
        return LossLimitCheckpointMetadataBootstrapResult(
            CheckpointMetadataBootstrapStatus.PERSISTENCE_UNAVAILABLE,
            None,
            None,
            None,
            "persistence load unavailable",
        )
    try:
        load_result = loader()
    except Exception:
        return LossLimitCheckpointMetadataBootstrapResult(
            CheckpointMetadataBootstrapStatus.PERSISTENCE_UNAVAILABLE,
            None,
            None,
            None,
            "persistence load failed",
        )
    if not isinstance(load_result, LossPersistenceLoadResult):
        return LossLimitCheckpointMetadataBootstrapResult(
            CheckpointMetadataBootstrapStatus.PERSISTENCE_UNAVAILABLE,
            None,
            None,
            None,
            "persistence load result invalid",
        )
    if load_result.status is LoadStatus.MISSING:
        if configured_metadata is not None and (
            configured_metadata.last_persisted_revision != 0
            or configured_metadata.last_persisted_sequence != 0
            or configured_metadata.last_persisted_fingerprint is not None
        ):
            return LossLimitCheckpointMetadataBootstrapResult(
                CheckpointMetadataBootstrapStatus.RECOVERY_REQUIRED,
                None,
                load_result,
                None,
                "checkpoint metadata does not match persistence",
            )
        return LossLimitCheckpointMetadataBootstrapResult(
            CheckpointMetadataBootstrapStatus.MISSING,
            LossLimitCheckpointMetadata(),
            load_result,
        )
    if load_result.status is not LoadStatus.VALID or load_result.state is None:
        return LossLimitCheckpointMetadataBootstrapResult(
            CheckpointMetadataBootstrapStatus.RECOVERY_REQUIRED,
            None,
            load_result,
            None,
            "persisted state requires recovery",
        )
    try:
        canonical = build_canonical_loss_state_json(load_result.state)
        fingerprint = sha256(canonical).hexdigest()
    except Exception:
        return LossLimitCheckpointMetadataBootstrapResult(
            CheckpointMetadataBootstrapStatus.RECOVERY_REQUIRED,
            None,
            load_result,
            None,
            "persisted state metadata invalid",
        )
    metadata = configured_metadata or LossLimitCheckpointMetadata(1, 1, fingerprint)
    if metadata.last_persisted_revision == 0 or (
        metadata.last_persisted_fingerprint != fingerprint
    ):
        return LossLimitCheckpointMetadataBootstrapResult(
            CheckpointMetadataBootstrapStatus.RECOVERY_REQUIRED,
            None,
            load_result,
            None,
            "checkpoint metadata does not match persistence",
        )
    return LossLimitCheckpointMetadataBootstrapResult(
        CheckpointMetadataBootstrapStatus.READY,
        metadata,
        load_result,
        canonical,
    )
