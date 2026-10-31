"""Bounded read-only source evidence for authenticated answer paths.

``read_source_truth`` supplies the Git revision. This module does not search
the filesystem from a caller path. It reads only a fixed catalog, and only
after the relative path stays inside the repository root.

The evidence is source text. It is not a runtime observation and it is not
a Production revision.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from backend.context.source_truth import read_source_truth

MAX_CATALOG_ITEMS = 4
MAX_FILE_BYTES = 700_000
MAX_EXCERPT_CHARS = 240
_RELATIVE = re.compile(r"^(backend|frontend/src|docs)/[A-Za-z0-9_./-]+$")
_FORBIDDEN_PARTS = {
    ".env",
    ".git",
    "node_modules",
    "dist",
    "credentials",
    "secrets",
    "secret",
    "id_rsa",
    "cookies",
    "cookie",
}
_INJECTION = re.compile(
    r"(?i)(ignore\s+(all\s+|any\s+|previous\s+|prior\s+)*instructions|"
    r"system\s+prompt|you\s+are\s+now|do\s+not\s+follow|"
    r"disregard\s+(all\s+|any\s+|previous\s+)*instructions)"
)
_SECRET_LINE = re.compile(
    r"(?i)(api[_-]?key|secret|passwd|password|token|BEGIN PRIVATE|BEGIN RSA)"
)


@dataclass(frozen=True)
class CatalogEntry:
    topic: str
    relative_path: str
    symbol: str
    kind: str
    keywords: tuple[str, ...]


CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        "ORDER_CONTROL",
        "backend/utils/order.py",
        "place_order_safe",
        "FUNCTION",
        ("注文", "place_order", "order"),
    ),
    CatalogEntry(
        "ORDER_CONTROL",
        "backend/execution/base.py",
        "place_order",
        "FUNCTION",
        ("注文", "place_order", "order"),
    ),
    CatalogEntry(
        "ORDER_CONTROL",
        "backend/execution/kucoin_trade.py",
        "place_order",
        "FUNCTION",
        ("注文", "place_order", "order"),
    ),
    CatalogEntry(
        "ORDER_CONTROL",
        "backend/execution/bitget_trade.py",
        "execute_order",
        "FUNCTION",
        ("注文", "execute_order", "order"),
    ),
    CatalogEntry(
        "STEP4",
        "backend/runtime/cycle_diagnostics.py",
        "STEP_DEFINITIONS",
        "CONSTANT",
        ("step4", "step 4", "ステップ4", "microstructure", "micro edge"),
    ),
    CatalogEntry(
        "STEP4",
        "backend/strategy/MicrostructureEdgeStrategy.py",
        "build_entry_readiness",
        "FUNCTION",
        ("step4", "step 4", "ステップ4", "microstructure", "micro edge"),
    ),
    CatalogEntry(
        "MANUAL_TRADE",
        "frontend/src/components/BotControl.jsx",
        "handleManualTrade",
        "FUNCTION",
        ("manual buy", "manual-trade", "手動"),
    ),
    CatalogEntry(
        "MANUAL_TRADE",
        "backend/api/bot_api.py",
        "manual_trade",
        "FUNCTION",
        ("manual buy", "manual-trade", "手動"),
    ),
    CatalogEntry(
        "MANUAL_TRADE",
        "backend/bot_manager/bot_manager.py",
        "execute_manual_trade",
        "FUNCTION",
        ("manual buy", "manual-trade", "手動"),
    ),
)


def collect_source_evidence(
    question: str,
    repository: str | Path | None = None,
) -> dict[str, object]:
    """Return revision-bound catalog evidence. Exceptions stay UNAVAILABLE."""

    try:
        root = _repository_root(repository)
        revision = _revision(root)
        selected = _select(question)
        items = [
            _read_entry(root, entry, str(revision["sourceRevisionStatus"]))
            for entry in selected[:MAX_CATALOG_ITEMS]
        ]
        verified = any(item.get("sourceStatus") == "VERIFIED" for item in items)
        if not items:
            availability = "UNAVAILABLE"
            reason = "NO_MATCHING_SOURCE"
        elif verified and revision["sourceRevisionStatus"] == "VERIFIED":
            availability = "READY"
            reason = None
        else:
            availability = "UNKNOWN"
            reason = "SOURCE_INCOMPLETE"
        body: dict[str, object] = {
            "classification": "UNTRUSTED_SOURCE_EVIDENCE",
            "boundaryStart": "BEGIN_UNTRUSTED_SOURCE_EVIDENCE",
            "boundaryEnd": "END_UNTRUSTED_SOURCE_EVIDENCE",
            "truthKind": "SOURCE_TRUTH",
            "authority": "NONE",
            "tradingControl": "FORBIDDEN",
            "availability": availability,
            "sourceRepository": revision["sourceRepository"],
            "sourceBranch": revision["sourceBranch"],
            "sourceRevision": revision["sourceRevision"],
            "sourceRevisionStatus": revision["sourceRevisionStatus"],
            "productionRevision": "UNKNOWN",
            "productionRevisionStatus": "UNKNOWN",
            "singleControllerAsserted": False,
            "candidateCount": len(items),
            "items": items,
        }
        if reason is not None:
            body["reason"] = reason
        if len(items) > 1:
            body["selection"] = "MULTIPLE_CANDIDATES"
        elif len(items) == 1:
            body["selection"] = "SINGLE_CANDIDATE_NOT_EXCLUSIVE"
        else:
            body["selection"] = "NONE"
        return body
    except Exception:
        return _unavailable("SOURCE_EXCEPTION")


def resolve_catalog_path(root: Path, relative: str) -> Path | None:
    """Resolve one catalog-relative path, or return None when it is unsafe."""

    if not isinstance(relative, str) or not _RELATIVE.fullmatch(relative):
        return None
    parts = tuple(Path(relative).parts)
    if ".." in parts or any(_forbidden_part(part) for part in parts):
        return None
    try:
        root_resolved = root.resolve(strict=True)
    except OSError:
        return None
    current = root_resolved
    for part in parts:
        current = current / part
        try:
            if current.is_symlink():
                return None
        except OSError:
            return None
    if not current.is_file():
        return None
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (OSError, ValueError):
        return None
    return resolved


def _repository_root(repository: str | Path | None) -> Path:
    if repository is None:
        return Path(__file__).resolve().parents[2]
    path = Path(repository)
    if not path.is_dir():
        raise ValueError("repository path must be a directory")
    return path


def _revision(root: Path) -> dict[str, str | None]:
    try:
        truth = read_source_truth(root)
    except Exception:
        return {
            "sourceRepository": "UNKNOWN",
            "sourceBranch": "UNKNOWN",
            "sourceRevision": None,
            "sourceRevisionStatus": "UNAVAILABLE",
        }
    revision = truth.head if isinstance(truth.head, str) and truth.head else None
    status = "VERIFIED" if revision else "UNKNOWN"
    branch = truth.branch if isinstance(truth.branch, str) and truth.branch else "UNKNOWN"
    return {
        "sourceRepository": "local-worktree" if status == "VERIFIED" else "UNKNOWN",
        "sourceBranch": branch,
        "sourceRevision": revision,
        "sourceRevisionStatus": status,
    }


def _select(question: str) -> tuple[CatalogEntry, ...]:
    if not isinstance(question, str) or not question.strip():
        return ()
    folded = question.casefold()
    scores: dict[str, int] = {}
    for entry in CATALOG:
        score = sum(1 for keyword in entry.keywords if keyword.casefold() in folded)
        if score:
            scores[entry.topic] = scores.get(entry.topic, 0) + score
    if not scores:
        return ()
    ranked = [
        topic
        for topic, _score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    ]
    groups = {
        topic: [entry for entry in CATALOG if entry.topic == topic]
        for topic in ranked
    }
    indexes = {topic: 0 for topic in ranked}
    chosen: list[CatalogEntry] = []
    while len(chosen) < MAX_CATALOG_ITEMS:
        progressed = False
        for topic in ranked:
            group = groups[topic]
            index = indexes[topic]
            if index < len(group):
                chosen.append(group[index])
                indexes[topic] = index + 1
                progressed = True
                if len(chosen) >= MAX_CATALOG_ITEMS:
                    break
        if not progressed:
            break
    return tuple(chosen)


def _read_entry(
    root: Path,
    entry: CatalogEntry,
    revision_status: str,
) -> dict[str, object]:
    base: dict[str, object] = {
        "sourceFile": entry.relative_path,
        "sourceSymbol": entry.symbol,
        "sourceKind": entry.kind,
        "sourceTopic": entry.topic,
        "sourceLineStart": None,
        "sourceLineEnd": None,
        "excerpt": None,
    }
    path = resolve_catalog_path(root, entry.relative_path)
    if path is None:
        return {
            **base,
            "sourceStatus": "UNAVAILABLE",
            "reason": "SOURCE_FILE_UNAVAILABLE",
        }
    try:
        size = path.stat().st_size
        raw = path.read_bytes()[:MAX_FILE_BYTES]
    except OSError:
        return {
            **base,
            "sourceStatus": "UNAVAILABLE",
            "reason": "SOURCE_FILE_UNAVAILABLE",
        }
    text = raw.decode("utf-8", errors="replace")
    match = _symbol_match(text, entry.symbol)
    if match is None:
        reason = "READ_LIMIT" if size > MAX_FILE_BYTES else "SYMBOL_NOT_FOUND"
        return {**base, "sourceStatus": "UNKNOWN", "reason": reason}
    line_start = text.count("\n", 0, match.start()) + 1
    line_from = text.rfind("\n", 0, match.start()) + 1
    line_to = text.find("\n", match.start())
    if line_to < 0:
        line_to = len(text)
    line_text = _INJECTION.sub("[REMOVED:PROMPT_INJECTION]", text[line_from:line_to].strip())
    if _SECRET_LINE.search(line_text):
        line_text = "[REMOVED:SENSITIVE]"
    status = "VERIFIED" if revision_status == "VERIFIED" else "UNKNOWN"
    if len(line_text) > MAX_EXCERPT_CHARS:
        return {
            **base,
            "sourceLineStart": line_start,
            "sourceLineEnd": line_start,
            "sourceStatus": status,
            "reason": "EXCERPT_LIMIT",
        }
    return {
        **base,
        "sourceLineStart": line_start,
        "sourceLineEnd": line_start,
        "excerpt": line_text,
        "sourceStatus": status,
    }


def _symbol_match(text: str, symbol: str):
    escaped = re.escape(symbol)
    pattern = re.compile(
        rf"(?m)^[ \t]*(?:async[ \t]+def|def|class)[ \t]+{escaped}\b"
        rf"|^[ \t]*{escaped}[ \t]*="
        rf"|^[ \t]*const[ \t]+{escaped}[ \t]*="
    )
    return pattern.search(text)


def _forbidden_part(part: str) -> bool:
    folded = part.casefold()
    if folded in _FORBIDDEN_PARTS or folded.startswith(".env"):
        return True
    return folded.endswith((".pem", ".key", ".p12"))


def _unavailable(reason: str) -> dict[str, object]:
    return {
        "classification": "UNTRUSTED_SOURCE_EVIDENCE",
        "boundaryStart": "BEGIN_UNTRUSTED_SOURCE_EVIDENCE",
        "boundaryEnd": "END_UNTRUSTED_SOURCE_EVIDENCE",
        "truthKind": "SOURCE_TRUTH",
        "authority": "NONE",
        "tradingControl": "FORBIDDEN",
        "availability": "UNAVAILABLE",
        "reason": reason,
        "sourceRepository": "UNKNOWN",
        "sourceBranch": "UNKNOWN",
        "sourceRevision": None,
        "sourceRevisionStatus": "UNAVAILABLE",
        "productionRevision": "UNKNOWN",
        "productionRevisionStatus": "UNKNOWN",
        "singleControllerAsserted": False,
        "selection": "NONE",
        "candidateCount": 0,
        "items": [],
    }
