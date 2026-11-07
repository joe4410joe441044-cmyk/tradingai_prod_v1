"""Path, filename, and content gates.

Rejected inputs produce a fixed code. Matched secret text is not copied
into exceptions or returned records.
"""

from __future__ import annotations

from pathlib import Path
import re

from .config import DENY_PARTS


_SECRET_FILENAME = re.compile(
    r"(?ix)^(?:"
    r"\.env(?:\.|$)|"
    r".*\.(?:pem|p12|pfx|key|kdbx)|"
    r"id_rsa.*|id_dsa.*|id_ed25519.*|id_ecdsa.*|"
    r"credentials?(?:\.[a-z0-9]+)?|"
    r"cookies?(?:\.[a-z0-9]+)?|"
    r".*secret.*|.*password.*|"
    r"\.netrc|"
    r".*api[_-]?key.*|"
    r"(?:.*[._-])?token(?:[._-].*)?"
    r")$"
)
_SECRET_CONTENT = re.compile(
    r"(?i)("
    r"api[_-]?key\s*[:=]\s*\S|"
    r"(?:secret|password|passwd)\s*[:=]\s*\S|"
    r"\btoken\s*[:=]\s*\S|"
    r"authorization\s*:\s*bearer\s+\S|"
    r"set-cookie\s*:|"
    r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"
    r")"
)
_SHA = re.compile(r"^[0-9a-f]{7,40}$")


class PathRejected(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def secret_filename(name: str) -> bool:
    return _SECRET_FILENAME.search(name) is not None


def secret_bytes(sample: bytes) -> bool:
    if _SECRET_CONTENT.search(sample.decode("utf-8", errors="ignore")):
        return True
    return False


def redact_text(value: str, limit: int = 300) -> str | None:
    clipped = value.strip().replace("\n", " ")[:limit]
    if not clipped or secret_bytes(clipped.encode("utf-8", errors="ignore")):
        return None
    return clipped


def valid_commit_sha(value: str) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def normalize_relative(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or value == "" or "\x00" in value:
        raise PathRejected("PATH_REJECTED")
    if value.startswith(("/", "\\")) or (len(value) >= 2 and value[1] == ":"):
        raise PathRejected("ABSOLUTE_PATH")
    slash = value.replace("\\", "/")
    if slash.startswith("./"):
        slash = slash[2:]
    parts = tuple(part for part in slash.split("/") if part != "" and part != ".")
    if not parts or any(part in {".", ".."} for part in parts):
        raise PathRejected("PATH_TRAVERSAL")
    return parts


def assert_allow_prefix(prefix: str) -> str:
    parts = normalize_relative(prefix if prefix.endswith("/") else prefix + "/")
    if any(part in DENY_PARTS or secret_filename(part) for part in parts):
        raise PathRejected("DENYLIST")
    return "/".join(parts) + "/"


def path_is_denied(parts: tuple[str, ...]) -> str | None:
    for part in parts:
        if secret_filename(part):
            return "SECRET_EXCLUDED"
        if part in DENY_PARTS or part.startswith("."):
            return "DENYLIST"
    return None


def allowed_by_prefix(relative: str, prefixes: tuple[str, ...]) -> bool:
    return any(relative == prefix[:-1] or relative.startswith(prefix) for prefix in prefixes)


def contained_file(root: Path, parts: tuple[str, ...]) -> Path:
    """Return a file that stays inside ``root`` without following links."""

    if root.is_symlink():
        raise PathRejected("SYMLINK_REJECTED")
    try:
        anchor = root.resolve(strict=True)
    except (OSError, RuntimeError):
        raise PathRejected("SOURCE_ROOT_NOT_FOUND") from None
    current = root
    for part in parts:
        if part in DENY_PARTS:
            raise PathRejected("DENYLIST")
        current = current / part
        if current.is_symlink():
            raise PathRejected("SYMLINK_REJECTED")
    if not current.exists():
        raise PathRejected("MISSING_FILE")
    try:
        resolved = current.resolve(strict=True)
    except (OSError, RuntimeError):
        raise PathRejected("PATH_REJECTED") from None
    if not resolved.is_relative_to(anchor):
        raise PathRejected("PATH_ESCAPE")
    if not current.is_file():
        raise PathRejected("NOT_A_FILE")
    return current


def directory_inside(requested: Path, allowed_root: Path) -> bool:
    if requested.is_symlink() or allowed_root.is_symlink():
        return False
    try:
        requested_real = requested.resolve(strict=True)
        allowed_real = allowed_root.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    if allowed_real in {Path("/"), Path("/tmp"), Path.home()}:
        return False
    return requested_real == allowed_real or requested_real.is_relative_to(allowed_real)
