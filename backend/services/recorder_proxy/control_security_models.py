# -*- coding: utf-8 -*-
"""Immutable result types for the Market Recorder control security stores.

ReplayStore and RateLimitStore return these contracts so that callers
never inspect raw store internals.  Every failure path carries a safe
error code; implementation details are never exposed.
"""

from dataclasses import dataclass
from enum import Enum


class ReplayVerdict(str, Enum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    STORE_FAILURE = "STORE_FAILURE"


class RateLimitVerdict(str, Enum):
    ALLOWED = "ALLOWED"
    EXCEEDED = "EXCEEDED"
    STORE_FAILURE = "STORE_FAILURE"


@dataclass(frozen=True)
class ReplayResult:
    verdict: ReplayVerdict
    key: str
    expires_at_epoch: float


@dataclass(frozen=True)
class RateLimitResult:
    verdict: RateLimitVerdict
    key: str
    current_count: int
    limit: int
    window_seconds: float
    retry_after_seconds: float
