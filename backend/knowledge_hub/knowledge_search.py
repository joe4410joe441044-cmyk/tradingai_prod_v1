"""Read-only search over a knowledge store.

The query text is bound as a parameter. It is also reduced to plain tokens
before it is given to FTS5, so operator characters cannot change the statement.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3

from .knowledge_store import KnowledgeStore, StoreError


_TOKEN = re.compile(r"[0-9A-Za-z]+")


@dataclass(frozen=True)
class SearchHit:
    record_id: str
    source_type: str
    source_identifier: str
    record_type: str
    title: str
    snippet: str
    commit_sha: str | None
    worktree: str | None
    branch: str | None
    source_timestamp: str | None
    collected_at: str
    indexed_at: str
    verification_state: str
    authority_scope: str
    truth_kind: str
    freshness: str
    presence: str
    score: float
    workstream: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "source_type": self.source_type,
            "source_identifier": self.source_identifier,
            "record_type": self.record_type,
            "title": self.title,
            "snippet": self.snippet,
            "commit_sha": self.commit_sha,
            "worktree": self.worktree,
            "branch": self.branch,
            "source_timestamp": self.source_timestamp,
            "collected_at": self.collected_at,
            "indexed_at": self.indexed_at,
            "verification_state": self.verification_state,
            "authority_scope": self.authority_scope,
            "truth_kind": self.truth_kind,
            "freshness": self.freshness,
            "presence": self.presence,
            "score": self.score,
            "workstream": self.workstream,
        }


@dataclass(frozen=True)
class SearchQuery:
    text: str
    phrase: bool = False
    source_type: str | None = None
    record_type: str | None = None
    workstream: str | None = None
    branch: str | None = None
    worktree: str | None = None
    commit_sha: str | None = None
    verification_state: str | None = None
    authority_scope: str | None = None
    freshness: str | None = None
    presence: str | None = None
    time_from: str | None = None
    time_to: str | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True)
class SearchPage:
    hits: tuple[SearchHit, ...]
    limit: int
    offset: int
    has_more: bool
    error: str | None = None


def compile_match(text: str, *, phrase: bool, max_length: int) -> tuple[str, tuple[str, ...]]:
    if not isinstance(text, str) or len(text) > max_length:
        raise StoreError("QUERY_TOO_LONG" if isinstance(text, str) and len(text) > max_length else "QUERY_REJECTED")
    tokens = tuple(_TOKEN.findall(text))
    if not tokens or any(len(token) > 64 for token in tokens):
        raise StoreError("QUERY_REJECTED")
    if phrase:
        return '"' + " ".join(tokens) + '"', tokens
    return " AND ".join(f'"{token}"' for token in tokens), tokens


def _snippet(content: str, tokens: tuple[str, ...], limit: int) -> str:
    lowered = content.lower()
    position = -1
    for token in tokens:
        position = lowered.find(token.lower())
        if position >= 0:
            break
    if position < 0:
        piece = content[:limit]
    else:
        start = max(0, position - 32)
        piece = content[start : start + limit]
    if len(piece) > limit:
        piece = piece[:limit]
    return piece


def search(store: KnowledgeStore, query: SearchQuery) -> SearchPage:
    limits = store._limits
    try:
        match, tokens = compile_match(query.text, phrase=query.phrase, max_length=limits.max_query_length)
    except StoreError as exc:
        return SearchPage((), 0, query.offset, False, error=exc.code)
    if query.offset < 0 or query.offset > limits.max_offset:
        return SearchPage((), 0, query.offset, False, error="OFFSET_REJECTED")
    limit = limits.max_results if query.limit is None else min(query.limit, limits.max_results)
    if limit < 1:
        return SearchPage((), 0, query.offset, False, error="RESULT_LIMIT")
    statement = """
        SELECT records.*, bm25(records_fts) AS rank
        FROM records_fts
        JOIN records ON records.record_id = records_fts.record_id
        WHERE records_fts MATCH ?
          AND (? IS NULL OR records.source_type = ?)
          AND (? IS NULL OR records.record_type = ?)
          AND (? IS NULL OR records.workstream = ?)
          AND (? IS NULL OR records.branch = ?)
          AND (? IS NULL OR records.worktree = ?)
          AND (? IS NULL OR records.commit_sha = ?)
          AND (? IS NULL OR records.verification_state = ?)
          AND (? IS NULL OR records.authority_scope = ?)
          AND (? IS NULL OR records.freshness = ?)
          AND (? IS NULL OR records.presence = ?)
          AND (? IS NULL OR COALESCE(records.source_timestamp, records.collected_at) >= ?)
          AND (? IS NULL OR COALESCE(records.source_timestamp, records.collected_at) <= ?)
        ORDER BY rank ASC, records.record_id ASC
        LIMIT ? OFFSET ?
    """
    parameters = (
        match,
        query.source_type,
        query.source_type,
        query.record_type,
        query.record_type,
        query.workstream,
        query.workstream,
        query.branch,
        query.branch,
        query.worktree,
        query.worktree,
        query.commit_sha,
        query.commit_sha,
        query.verification_state,
        query.verification_state,
        query.authority_scope,
        query.authority_scope,
        query.freshness,
        query.freshness,
        query.presence,
        query.presence,
        query.time_from,
        query.time_from,
        query.time_to,
        query.time_to,
        limit + 1,
        query.offset,
    )
    try:
        rows = store._connection.execute(statement, parameters).fetchall()
    except sqlite3.Error:
        return SearchPage((), limit, query.offset, False, error="QUERY_REJECTED")
    has_more = len(rows) > limit
    chosen = rows[:limit]
    hits = []
    for row in chosen:
        rank = float(row["rank"])
        hits.append(
            SearchHit(
                record_id=row["record_id"],
                source_type=row["source_type"],
                source_identifier=row["source_identifier"],
                record_type=row["record_type"],
                title=row["title"],
                snippet=_snippet(row["content"], tokens, limits.max_snippet_length),
                commit_sha=row["commit_sha"],
                worktree=row["worktree"],
                branch=row["branch"],
                source_timestamp=row["source_timestamp"],
                collected_at=row["collected_at"],
                indexed_at=row["indexed_at"],
                verification_state=row["verification_state"],
                authority_scope=row["authority_scope"],
                truth_kind=row["truth_kind"],
                freshness=row["freshness"],
                presence=row["presence"],
                score=round(-rank, 6),
                workstream=row["workstream"],
            )
        )
    return SearchPage(tuple(hits), limit, query.offset, has_more)
