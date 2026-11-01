"""Explicit read-only credential file provider.

The provider is constructed with an absolute, caller-supplied path.  It performs
no implicit search of the repository, the current directory, environment
variables, ``.env`` files, a vault, or a registry.  Import and construction never
touch the filesystem; only an explicit :meth:`resolve` call opens and reads the
file.

Filesystem boundary:
- absolute path only; relative paths are rejected;
- final file opened with ``O_NOFOLLOW``/``O_CLOEXEC`` where available and
  validated through descriptor metadata (``fstat``);
- every parent component is opened relative to the preceding directory fd and
  validated as a trusted, non-group/other-writable directory (root-owned sticky
  directories such as ``/tmp`` are the explicit exception);
- regular files only; symlinks are rejected;
- owner UID policy is explicit (defaults to the current effective UID);
- group/other permission bits must be zero;
- bounded size and bounded read;
- strict UTF-8/JSON with duplicate-key rejection and an exact schema.

Secrets live only in a transient local ``document`` and in the returned
:class:`ReadOnlyCredential`.  They are never cached, logged, rendered, or placed
in a provider exception.  Python cannot guarantee secure memory erasure; the
guarantee is limited to "never rendered, never serialized, and dropped when this
call returns".

Rotation: the file is re-read on every resolve, so an atomic ``os.replace`` that
changes the ``generation`` field is observed immediately and no stale value is
cached.  A readiness result bound to the previous generation must be rejected by
the caller's ``ReadinessBinding`` comparison; this provider exposes the new
generation through :class:`ReadOnlyCredential`.  Material changes that reuse a
generation are intentionally not detectable: deployment must assign a new,
non-secret generation for every key or secret change.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import stat
from typing import Any, Mapping, Optional

from backend.accounts.models import AccountId, ExecutionMode, ExecutionVenue
from backend.accounts.registry_models import (
    CredentialBundleReference,
    CredentialReferenceSource,
)
from backend.execution.read_only_adapter_contracts import EndpointProfile
from backend.execution.read_only_credentials import (
    CredentialProviderError,
    CredentialProviderErrorCode,
    CredentialScope,
    ReadOnlyCredential,
)


CREDENTIAL_FILE_SCHEMA_VERSION = "tradingai-read-only-credential-file/v1"

_DOCUMENT_KEYS = frozenset({"schema_version", "credentials"})
_ENTRY_KEYS = frozenset(
    {
        "account_id",
        "execution_mode",
        "execution_venue",
        "endpoint_profile",
        "generation",
        "api_key",
        "api_secret",
    }
)
_DEFAULT_ALLOWED_SOURCES = frozenset(
    {
        CredentialReferenceSource.SYSTEMD_CREDENTIAL_BUNDLE,
        CredentialReferenceSource.INJECTED_TEST,
    }
)
_MAX_GENERATION_LENGTH = 128


class _DuplicateKey(ValueError):
    """Internal marker; never exposed with file content."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey()
        result[key] = value
    return result


def _unavailable() -> CredentialProviderError:
    return CredentialProviderError(CredentialProviderErrorCode.UNAVAILABLE)


def _invalid() -> CredentialProviderError:
    return CredentialProviderError(CredentialProviderErrorCode.INVALID_CREDENTIAL)


@dataclass(frozen=True)
class _FilePolicy:
    path: str
    owner_uid: int
    allowed_root: Optional[str]
    max_bytes: int
    allowed_sources: frozenset[CredentialReferenceSource]


class ReadOnlyCredentialFileProvider:
    """File-backed credential provider with an explicit, non-implicit boundary."""

    def __init__(
        self,
        path: str,
        *,
        expected_owner_uid: Optional[int] = None,
        allowed_root: Optional[str] = None,
        max_bytes: int = 65_536,
        allowed_sources: Optional[frozenset[CredentialReferenceSource]] = None,
    ) -> None:
        raw_path = os.fspath(path)
        if not isinstance(raw_path, str):
            raise TypeError("credential path must be a string path")
        if not os.path.isabs(raw_path):
            raise ValueError("credential path must be absolute")
        if os.path.normpath(raw_path) != raw_path:
            raise ValueError("credential path must be normalized")
        if isinstance(expected_owner_uid, bool) or not isinstance(
            expected_owner_uid, (int, type(None))
        ):
            raise TypeError("expected_owner_uid must be an integer or None")
        owner_uid = os.geteuid() if expected_owner_uid is None else expected_owner_uid
        if owner_uid < 0:
            raise ValueError("expected_owner_uid must be nonnegative")
        if allowed_root is not None:
            raw_root = os.fspath(allowed_root)
            if not isinstance(raw_root, str):
                raise TypeError("allowed_root must be a string path")
            if not os.path.isabs(raw_root):
                raise ValueError("allowed_root must be absolute")
            if os.path.normpath(raw_root) != raw_root:
                raise ValueError("allowed_root must be normalized")
            allowed_root = raw_root
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
            raise ValueError("max_bytes must be an integer")
        if not 1 <= max_bytes <= 1_048_576:
            raise ValueError("max_bytes must be in [1, 1048576]")
        if allowed_sources is None:
            sources = _DEFAULT_ALLOWED_SOURCES
        else:
            if not isinstance(allowed_sources, frozenset) or not allowed_sources:
                raise ValueError("allowed_sources must be a non-empty frozenset")
            for source in allowed_sources:
                if not isinstance(source, CredentialReferenceSource):
                    raise TypeError("allowed_sources must contain CredentialReferenceSource")
            sources = allowed_sources
        self._policy = _FilePolicy(
            path=raw_path,
            owner_uid=owner_uid,
            allowed_root=allowed_root,
            max_bytes=max_bytes,
            allowed_sources=sources,
        )

    def __repr__(self) -> str:
        return "ReadOnlyCredentialFileProvider(<redacted>)"

    def __str__(self) -> str:
        return self.__repr__()

    @property
    def generation_schema_version(self) -> str:
        return CREDENTIAL_FILE_SCHEMA_VERSION

    def _check_root(self) -> None:
        root = self._policy.allowed_root
        if root is None:
            return
        try:
            if os.path.commonpath([root, self._policy.path]) != root:
                raise _unavailable()
        except CredentialProviderError:
            raise
        except (OSError, ValueError):
            raise _unavailable() from None

    def _validate_directory(self, fd: int) -> None:
        try:
            info = os.fstat(fd)
        except OSError:
            raise _unavailable() from None
        if not stat.S_ISDIR(info.st_mode):
            raise _unavailable()
        if info.st_uid not in (0, self._policy.owner_uid):
            raise _unavailable()
        writable_by_others = bool(info.st_mode & 0o022)
        root_owned_sticky = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
        if writable_by_others and not root_owned_sticky:
            raise _unavailable()

    def _open_file(self) -> int:
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        file_flags = (
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        components = tuple(part for part in self._policy.path.split(os.sep) if part)
        if not components:
            raise _unavailable()
        try:
            directory_fd = os.open(os.sep, directory_flags)
        except OSError:
            raise _unavailable() from None
        try:
            self._validate_directory(directory_fd)
            for component in components[:-1]:
                try:
                    next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
                except OSError:
                    raise _unavailable() from None
                try:
                    self._validate_directory(next_fd)
                except Exception:
                    os.close(next_fd)
                    raise
                os.close(directory_fd)
                directory_fd = next_fd
            try:
                return os.open(components[-1], file_flags, dir_fd=directory_fd)
            except OSError:
                raise _unavailable() from None
        finally:
            try:
                os.close(directory_fd)
            except OSError:
                pass

    def _read(self) -> bytes:
        fd = self._open_file()
        try:
            try:
                info = os.fstat(fd)
            except OSError:
                raise _unavailable() from None
            if not stat.S_ISREG(info.st_mode):
                raise _unavailable()
            if info.st_uid != self._policy.owner_uid:
                raise _unavailable()
            if info.st_mode & 0o077:
                raise _unavailable()
            if info.st_size < 1 or info.st_size > self._policy.max_bytes:
                raise _unavailable()
            chunks: list[bytes] = []
            total = 0
            while True:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    raise _unavailable() from None
                if not chunk:
                    break
                total += len(chunk)
                if total > self._policy.max_bytes:
                    raise _unavailable()
                chunks.append(chunk)
            if total < 1:
                raise _invalid()
            return b"".join(chunks)
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    def _parse(self, data: bytes) -> Mapping[str, Any]:
        try:
            text = data.decode("utf-8", "strict")
            document = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeDecodeError, ValueError):
            raise _invalid() from None
        if not isinstance(document, dict) or set(document) != _DOCUMENT_KEYS:
            raise _invalid()
        if document.get("schema_version") != CREDENTIAL_FILE_SCHEMA_VERSION:
            raise _invalid()
        credentials = document.get("credentials")
        if not isinstance(credentials, dict):
            raise _invalid()
        return credentials

    def _entry_scope(self, entry: Mapping[str, Any]) -> CredentialScope:
        try:
            account_id = AccountId(entry["account_id"])
            mode = ExecutionMode(entry["execution_mode"])
            venue = ExecutionVenue(entry["execution_venue"])
            profile = EndpointProfile(entry["endpoint_profile"])
        except (KeyError, TypeError, ValueError):
            raise _invalid() from None
        try:
            return CredentialScope(
                account_id=account_id,
                execution_mode=mode,
                execution_venue=venue,
                endpoint_profile=profile,
            )
        except (TypeError, ValueError):
            raise _invalid() from None

    @staticmethod
    def _generation(entry: Mapping[str, Any]) -> str:
        value = entry.get("generation")
        if not isinstance(value, str) or not value:
            raise _invalid()
        if len(value) > _MAX_GENERATION_LENGTH:
            raise _invalid()
        if any(ord(char) < 33 or ord(char) > 126 for char in value):
            raise _invalid()
        return value

    def resolve(
        self, reference: CredentialBundleReference, scope: CredentialScope
    ) -> ReadOnlyCredential:
        if not isinstance(reference, CredentialBundleReference):
            raise TypeError("reference must be CredentialBundleReference")
        if not isinstance(scope, CredentialScope):
            raise TypeError("scope must be CredentialScope")
        if reference.source not in self._policy.allowed_sources:
            raise CredentialProviderError(CredentialProviderErrorCode.REFERENCE_UNKNOWN)
        self._check_root()
        credentials = self._parse(self._read())
        credential_id = reference.credential_id
        entry = credentials.get(credential_id)
        if not isinstance(entry, Mapping):
            raise CredentialProviderError(CredentialProviderErrorCode.REFERENCE_UNKNOWN)
        if set(entry) != _ENTRY_KEYS:
            raise _invalid()
        entry_scope = self._entry_scope(entry)
        if entry_scope != scope:
            raise CredentialProviderError(CredentialProviderErrorCode.SCOPE_MISMATCH)
        generation = self._generation(entry)
        api_key = entry.get("api_key")
        api_secret = entry.get("api_secret")
        try:
            return ReadOnlyCredential(
                reference=reference,
                api_key=api_key,
                api_secret=api_secret,
                scope=scope,
                credential_generation=generation,
            )
        except (TypeError, ValueError):
            raise _invalid() from None
