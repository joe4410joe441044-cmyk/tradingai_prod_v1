"""TradingAI relevance and privacy classification.

A generic word is not enough to auto-import. Secret-like material is always
moved to review, and the matched text is never copied into a result object.
"""

from __future__ import annotations

import re

from ..security import secret_bytes
from .models import (
    IN_SCOPE,
    OUT_OF_SCOPE,
    PRIVACY_CLEAN,
    PRIVACY_REVIEW,
    REVIEW_REQUIRED,
    UNKNOWN,
    PrivacyResult,
    RelevanceResult,
)


STRONG_TERMS: tuple[str, ...] = (
    "tradingai_prod_v1",
    "tradingai",
    "microstructure edge",
    "market intelligence",
    "trading cycle",
    "money management",
    "manual trading",
    "paper trading",
    "live trading",
    "account status",
    "ai advisor",
    "ai supervisor",
    "opencode",
    "cursor agent",
    "contabo",
    "worktree",
    "knowledge hub",
    "blackboard",
    "bb contract",
)

GENERIC_TERMS: tuple[str, ...] = (
    "trading",
    "market",
    "account",
    "order",
    "strategy",
    "supervisor",
    "advisor",
    "crypto",
    "bot",
)

_PRIVACY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----")),
    ("AUTHORIZATION", re.compile(r"(?i)authorization\s*:\s*bearer\s+\S+")),
    ("COOKIE", re.compile(r"(?i)set-cookie\s*:")),
    ("API_KEY", re.compile(r"(?i)api[_-]?key\s*[:=]\s*\S+")),
    ("API_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("API_KEY", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("API_KEY", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("PASSWORD", re.compile(r"(?i)(?:password|passwd|pwd)\s*[:=]\s*\S+")),
    ("SECRET", re.compile(r"(?i)(?:client[_-]?secret|secret[_-]?key)\s*[:=]\s*\S+")),
    ("TOKEN", re.compile(r"(?i)\btoken\s*[:=]\s*\S+")),
    ("CREDENTIALS", re.compile(r"(?i)\bcredentials?\s*[:=]\s*\S+")),
    ("SESSION", re.compile(r"(?i)\bsession(?:[_-]?id|[_-]?cookie)\s*[:=]\s*\S+")),
    ("PERSONAL_DATA", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
)


def classify_text(text: str, *, conversation_title: str = "") -> RelevanceResult:
    body = text.strip()
    if body == "":
        return RelevanceResult(UNKNOWN, "EMPTY_TEXT")
    lowered = body.lower()
    strong = tuple(term for term in STRONG_TERMS if term in lowered)
    if strong:
        return RelevanceResult(IN_SCOPE, "STRONG_TERM", strong)
    title_lowered = conversation_title.lower()
    if any(term in title_lowered for term in STRONG_TERMS):
        return RelevanceResult(REVIEW_REQUIRED, "TITLE_ONLY_MATCH")
    generic = tuple(term for term in GENERIC_TERMS if term in lowered)
    if generic:
        return RelevanceResult(REVIEW_REQUIRED, "GENERIC_TERM_ONLY", generic)
    return RelevanceResult(OUT_OF_SCOPE, "NO_TRADINGAI_TERM")


def inspect_privacy(*values: str) -> PrivacyResult:
    flags: list[str] = []
    for value in values:
        if not isinstance(value, str) or value == "":
            continue
        if secret_bytes(value.encode("utf-8", errors="ignore")):
            flags.append("SECRET_PATTERN")
        for name, pattern in _PRIVACY_RULES:
            if pattern.search(value):
                flags.append(name)
    unique = tuple(dict.fromkeys(flags))
    if unique:
        return PrivacyResult(PRIVACY_REVIEW, unique)
    return PrivacyResult(PRIVACY_CLEAN)
