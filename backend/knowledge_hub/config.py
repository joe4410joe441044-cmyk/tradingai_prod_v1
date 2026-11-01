"""Limits and allowlists for the isolated collectors.

Values here are library defaults. Nothing in this module reads the
repository or starts a collector.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCHEMA_VERSION = "tradingai-knowledge-collector/v1"

DEFAULT_SOURCE_PREFIXES: tuple[str, ...] = (
    "backend/",
    "frontend/src/",
    "tests/",
    "docs/",
)

SOURCE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".css",
        ".md",
        ".txt",
        ".yml",
        ".yaml",
        ".json",
    }
)

DENY_PARTS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "dist",
        "venv",
        "__pycache__",
        "logs",
        ".pytest_cache",
        ".mypy_cache",
        ".env",
    }
)

DEFAULT_REPORT_ROOTS: tuple[Path, ...] = (
    Path("/tmp/work_bc_audit"),
    Path("/tmp/work_bb_audit"),
)

REPORT_SUFFIXES: frozenset[str] = frozenset({".md", ".txt", ".json"})


@dataclass(frozen=True)
class CollectorConfig:
    """Explicit bounds. Callers may narrow them. They cannot disable denial."""

    allow_prefixes: tuple[str, ...] = DEFAULT_SOURCE_PREFIXES
    max_file_bytes: int = 262_144
    max_total_bytes: int = 2_000_000
    max_files: int = 200
    timeout_seconds: float = 5.0
    max_commits: int = 20
    max_worktrees: int = 20
    max_status_lines: int = 50
    max_report_files: int = 50
    include_text: bool = False
    git_timeout_seconds: float = 5.0
