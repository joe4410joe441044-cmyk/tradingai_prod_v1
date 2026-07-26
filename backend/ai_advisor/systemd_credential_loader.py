"""Strict systemd credential loader and content-free availability probe."""

import os
import stat
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from backend.ai_advisor.credential_loader import (
    CredentialFailureCode,
    CredentialResolutionInput,
    CredentialResolutionResult,
    CredentialResolutionStatus,
    EphemeralCredential,
)
from backend.ai_advisor.provider_config import CredentialSource
from backend.ai_advisor.provider_models import AdvisorProviderContractModel

MAX_SYSTEMD_CREDENTIAL_BYTES = 8192


class SystemdCredentialAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    DIRECTORY_UNAVAILABLE = "DIRECTORY_UNAVAILABLE"
    REFERENCE_NOT_ALLOWED = "REFERENCE_NOT_ALLOWED"
    NOT_FOUND = "NOT_FOUND"
    NOT_REGULAR = "NOT_REGULAR"
    SYMLINK_REJECTED = "SYMLINK_REJECTED"
    SIZE_INVALID = "SIZE_INVALID"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    UNAVAILABLE = "UNAVAILABLE"


class SystemdCredentialProbeResult(AdvisorProviderContractModel):
    availability: SystemdCredentialAvailability


def _resolution_failure(
    code: CredentialFailureCode,
) -> CredentialResolutionResult:
    return CredentialResolutionResult(
        status=CredentialResolutionStatus.FAILED,
        failureCode=code,
        safeMessage="advisor credential unavailable",
    )


def _valid_reference(value: str) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and "\x00" not in value
        and value not in {".", ".."}
        and "/" not in value
        and "\\" not in value
        and not os.path.isabs(value)
    )


@dataclass(frozen=True)
class SystemdCredentialLoader:
    allowedCredentialIds: tuple[str, ...]
    credentialsDirectoryReader: Callable[[], str | None] = field(
        default=lambda: os.environ.get("CREDENTIALS_DIRECTORY"),
        repr=False,
        compare=False,
    )
    maximumCredentialBytes: int = MAX_SYSTEMD_CREDENTIAL_BYTES

    def __post_init__(self) -> None:
        if (
            not self.allowedCredentialIds
            or len(set(self.allowedCredentialIds)) != len(self.allowedCredentialIds)
            or any(not _valid_reference(value) for value in self.allowedCredentialIds)
            or not isinstance(self.maximumCredentialBytes, int)
            or isinstance(self.maximumCredentialBytes, bool)
            or self.maximumCredentialBytes < 1
            or self.maximumCredentialBytes > MAX_SYSTEMD_CREDENTIAL_BYTES
        ):
            raise ValueError("systemd credential loader configuration invalid")

    def _reference(self, resolution_input: CredentialResolutionInput) -> str | None:
        try:
            trusted = CredentialResolutionInput.model_validate(
                resolution_input.model_dump(warnings=False)
            )
            reference = trusted.credentialReference
            if (
                reference.source is not CredentialSource.SYSTEMD_CREDENTIAL
                or not _valid_reference(reference.credentialId)
                or reference.credentialId not in self.allowedCredentialIds
            ):
                return None
            return reference.credentialId
        except Exception:
            return None

    def probe(
        self,
        resolution_input: CredentialResolutionInput,
    ) -> SystemdCredentialProbeResult:
        reference = self._reference(resolution_input)
        if reference is None:
            return SystemdCredentialProbeResult(
                availability=SystemdCredentialAvailability.REFERENCE_NOT_ALLOWED
            )
        try:
            directory = self.credentialsDirectoryReader()
        except Exception:
            directory = None
        if not isinstance(directory, str) or not os.path.isabs(directory):
            return SystemdCredentialProbeResult(
                availability=SystemdCredentialAvailability.DIRECTORY_UNAVAILABLE
            )
        directory_fd = None
        try:
            directory_fd = os.open(
                directory,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
            )
            metadata = os.stat(reference, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                availability = SystemdCredentialAvailability.SYMLINK_REJECTED
            elif not stat.S_ISREG(metadata.st_mode):
                availability = SystemdCredentialAvailability.NOT_REGULAR
            elif not 0 < metadata.st_size <= self.maximumCredentialBytes:
                availability = SystemdCredentialAvailability.SIZE_INVALID
            elif not os.access(
                reference,
                os.R_OK,
                dir_fd=directory_fd,
                effective_ids=True,
                follow_symlinks=False,
            ):
                availability = SystemdCredentialAvailability.PERMISSION_DENIED
            else:
                availability = SystemdCredentialAvailability.AVAILABLE
        except FileNotFoundError:
            availability = SystemdCredentialAvailability.NOT_FOUND
        except PermissionError:
            availability = SystemdCredentialAvailability.PERMISSION_DENIED
        except (NotADirectoryError, OSError):
            availability = SystemdCredentialAvailability.UNAVAILABLE
        finally:
            if directory_fd is not None:
                os.close(directory_fd)
        return SystemdCredentialProbeResult(availability=availability)

    def resolve(
        self,
        resolution_input: CredentialResolutionInput,
    ) -> CredentialResolutionResult:
        reference = self._reference(resolution_input)
        if reference is None:
            return _resolution_failure(
                CredentialFailureCode.CREDENTIAL_REFERENCE_INVALID
            )
        try:
            directory = self.credentialsDirectoryReader()
        except Exception:
            directory = None
        if not isinstance(directory, str) or not os.path.isabs(directory):
            return _resolution_failure(
                CredentialFailureCode.CREDENTIAL_SOURCE_NOT_ALLOWED
            )
        directory_fd = credential_fd = None
        try:
            directory_fd = os.open(
                directory,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
            )
            credential_fd = os.open(
                reference,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
            metadata = os.fstat(credential_fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or not 0 < metadata.st_size <= self.maximumCredentialBytes
            ):
                raise ValueError
            payload = os.read(credential_fd, self.maximumCredentialBytes + 1)
            if not 0 < len(payload) <= self.maximumCredentialBytes:
                raise ValueError
            value = payload.decode("utf-8", errors="strict")
            if value != value.strip() or any(
                ord(character) < 32 or ord(character) == 127 for character in value
            ):
                raise ValueError
            return CredentialResolutionResult(
                status=CredentialResolutionStatus.SUCCEEDED,
                credential=EphemeralCredential(value),
            )
        except PermissionError:
            return _resolution_failure(CredentialFailureCode.CREDENTIAL_ACCESS_DENIED)
        except FileNotFoundError:
            return _resolution_failure(CredentialFailureCode.CREDENTIAL_NOT_FOUND)
        except (UnicodeDecodeError, ValueError, OSError):
            return _resolution_failure(CredentialFailureCode.CREDENTIAL_EMPTY)
        finally:
            if credential_fd is not None:
                os.close(credential_fd)
            if directory_fd is not None:
                os.close(directory_fd)
