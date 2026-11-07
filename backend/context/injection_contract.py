"""Limits for explicit context snapshot injection.

The boundary accepts JSON-like snapshot data only. Runtime objects are not
snapshot data and are rejected before a reader runs.
"""

from __future__ import annotations

MAX_DEPTH = 8
MAX_NODES = 2000
MAX_STRING = 4000
MAX_COLLECTION = 256
MAX_BYTES = 65536
MAX_CYCLE_ID = 128

REJECTED = "READER_REJECTED"


class SnapshotRejected(Exception):
    """A snapshot failed a fixed check. The message is a token, not input data."""

    def __init__(self) -> None:
        super().__init__(REJECTED)
