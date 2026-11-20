"""Offline import readiness for ChatGPT exports and Cursor saved reports.

This module is an orchestrator only. It reuses the existing BC-5 ChatGPT
importer, the BC-6 Cursor report sync, the BC-3 store/search, and the BC-10
read-only Advisor/Supervisor access. It does not implement a second importer
or a second collector, does not create a new schema, and does not contact a
network, an LLM, or a production service.

Every store path is guarded: the production knowledge store, a symlinked
store, and any path outside the explicit temporary root are rejected before
a database is opened.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile
import time
import zipfile
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from .chatgpt_import import ImportLimits, import_export, preview_export
from .continuous_sync import (
    AGENT_CURSOR,
    SOURCE_KIND_REPORT_DIR,
    ContinuousSyncEngine,
    SourceSpec,
    SyncLimits,
)
from .knowledge_access import query_advisor_knowledge, query_supervisor_knowledge
from .knowledge_store import KnowledgeStore, StoreError
from .reader import ReaderFilters, ReaderLimits, RequestContext, open_reader


READINESS_SCHEMA_VERSION = "tradingai-knowledge-import-readiness/v1"
PRODUCTION_STORE_PATH = Path(
    "/home/joe4410joe/tradingai_prod_v1/logs/runtime/knowledge_hub/knowledge_store.sqlite3"
)
PRODUCTION_RUNTIME_ROOT = Path("/home/joe4410joe/tradingai_prod_v1/logs")
DEFAULT_ALLOWED_STORE_ROOT = Path(tempfile.gettempdir())
OPERATOR = RequestContext(caller_scope="OPERATOR", caller_id="bc11a-readiness")

_ACCOUNT_A = "chatgpt_account_a"
_ACCOUNT_B = "chatgpt_account_b"


class ReadinessError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SearchProbe:
    name: str
    text: str
    filters: ReaderFilters | None = None


@dataclass(frozen=True)
class SyntheticCorpus:
    root: Path
    export_a: Path
    export_b: Path
    report_dir: Path


@dataclass(frozen=True)
class ReadinessResult:
    schema_version: str
    store_path: str
    store_sha256: str
    store_bytes: int
    integrity: str
    accounts: tuple[dict[str, Any], ...]
    reports: dict[str, Any]
    reports_reimport: dict[str, Any]
    counts: dict[str, Any]
    search: tuple[dict[str, Any], ...]
    advisor: dict[str, Any]
    supervisor: dict[str, Any]
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "store_path": self.store_path,
            "store_sha256": self.store_sha256,
            "store_bytes": self.store_bytes,
            "integrity": self.integrity,
            "accounts": [dict(account) for account in self.accounts],
            "reports": dict(self.reports),
            "reports_reimport": dict(self.reports_reimport),
            "counts": dict(self.counts),
            "search": [dict(item) for item in self.search],
            "advisor": dict(self.advisor),
            "supervisor": dict(self.supervisor),
            "duration_seconds": self.duration_seconds,
        }


def assert_temporary_store(
    store_path: str | Path,
    *,
    allowed_root: str | Path = DEFAULT_ALLOWED_STORE_ROOT,
) -> Path:
    """Reject a production, symlinked, or out-of-root store path."""

    if store_path is None or str(store_path) == "":
        raise ReadinessError("STORE_PATH_REQUIRED")
    target = Path(store_path)
    if target.is_symlink():
        raise ReadinessError("STORE_SYMLINK_REJECTED")
    try:
        resolved = target.resolve(strict=False)
        root = Path(allowed_root).resolve(strict=False)
        production = PRODUCTION_STORE_PATH.resolve(strict=False)
    except (OSError, RuntimeError):
        raise ReadinessError("STORE_PATH_REJECTED") from None
    if resolved == production:
        raise ReadinessError("PRODUCTION_STORE_REJECTED")
    if resolved == root or not resolved.is_relative_to(root):
        raise ReadinessError("STORE_OUTSIDE_ALLOWED_ROOT")
    return target


def _assert_report_root(
    directory: str | Path,
    *,
    allowed_roots: Sequence[str | Path],
) -> Path:
    requested = Path(directory)
    if requested.is_symlink():
        raise ReadinessError("REPORT_SYMLINK_REJECTED")
    try:
        resolved = requested.resolve(strict=False)
    except (OSError, RuntimeError):
        raise ReadinessError("REPORT_ROOT_REJECTED") from None
    if resolved in {Path("/"), Path("/tmp"), Path.home()}:
        raise ReadinessError("REPORT_ROOT_REJECTED")
    if resolved == PRODUCTION_RUNTIME_ROOT or resolved.is_relative_to(PRODUCTION_RUNTIME_ROOT):
        raise ReadinessError("PRODUCTION_RUNTIME_ROOT_REJECTED")
    if not allowed_roots:
        raise ReadinessError("REPORT_ALLOWLIST_REQUIRED")
    allowed = tuple(Path(root).resolve(strict=False) for root in allowed_roots)
    if not any(resolved == root or resolved.is_relative_to(root) for root in allowed):
        raise ReadinessError("REPORT_ROOT_NOT_ALLOWLISTED")
    return requested


def run_import_readiness(
    store_path: str | Path,
    *,
    chatgpt_exports: Mapping[str, str | Path],
    report_directories: Sequence[str | Path] = (),
    report_roots: Sequence[str | Path] = (),
    indexed_at: str,
    search_probes: Sequence[SearchProbe] = (),
    probe_question: str = "TradingAI",
    import_limits: ImportLimits | None = None,
    sync_limits: SyncLimits | None = None,
    allowed_store_root: str | Path = DEFAULT_ALLOWED_STORE_ROOT,
    scan_scope: str = "bc11a-readiness",
) -> ReadinessResult:
    """Import a synthetic or approved corpus into a guarded temporary store.

    Preview and import use the BC-5 importer. Cursor saved reports use the
    BC-6 continuous sync engine. Counts and search are read from the resulting
    temporary store only.
    """

    if not indexed_at or not isinstance(indexed_at, str):
        raise ReadinessError("TIMESTAMP_REQUIRED")
    target = assert_temporary_store(store_path, allowed_root=allowed_store_root)
    report_paths = tuple(Path(item) for item in report_directories)
    for directory in report_paths:
        _assert_report_root(directory, allowed_roots=report_roots)
    if not chatgpt_exports and not report_paths:
        raise ReadinessError("SOURCE_REQUIRED")

    started = time.monotonic()
    store = KnowledgeStore.create(target)
    try:
        accounts: list[dict[str, Any]] = []
        for alias, source in chatgpt_exports.items():
            resolved_alias = str(alias)
            preview = preview_export(
                source,
                resolved_alias,
                store_path=target,
                limits=import_limits,
            )
            report = import_export(
                source,
                resolved_alias,
                store,
                indexed_at=indexed_at,
                scan_scope=f"{scan_scope}:chatgpt",
                limits=import_limits,
            )
            reimport = import_export(
                source,
                resolved_alias,
                store,
                indexed_at=indexed_at,
                scan_scope=f"{scan_scope}:chatgpt",
                limits=import_limits,
            )
            accounts.append(
                {
                    "account_alias": resolved_alias,
                    "preview": preview.to_dict(),
                    "import": report.to_dict(),
                    "reimport": reimport.to_dict(),
                }
            )

        report_result: dict[str, Any] = {"status": "SKIPPED", "source_count": 0}
        report_reimport: dict[str, Any] = {"status": "SKIPPED", "source_count": 0}
        if report_paths:
            limits = sync_limits or SyncLimits(allowed_report_roots=tuple(report_roots))
            engine = ContinuousSyncEngine(limits=limits)
            sources = tuple(
                SourceSpec(path=path, kind=SOURCE_KIND_REPORT_DIR, agent=AGENT_CURSOR)
                for path in report_paths
            )
            report_result = engine.sync(
                sources,
                store,
                store_path=target,
                indexed_at=indexed_at,
                scan_scope=f"{scan_scope}:cursor",
            ).to_dict()
            report_reimport = engine.sync(
                sources,
                store,
                store_path=target,
                indexed_at=indexed_at,
                scan_scope=f"{scan_scope}:cursor",
            ).to_dict()

        integrity = store.integrity_check()
    finally:
        store.close()

    counts = _store_counts(target)
    search = _run_search(target, search_probes)
    advisor = _run_access_check(target, probe_question, role="ADVISOR")
    supervisor = _run_access_check(target, probe_question, role="SUPERVISOR")
    elapsed = round(time.monotonic() - started, 6)
    return ReadinessResult(
        schema_version=READINESS_SCHEMA_VERSION,
        store_path=str(target),
        store_sha256=_sha256(target),
        store_bytes=target.stat().st_size,
        integrity=integrity,
        accounts=tuple(accounts),
        reports=report_result,
        reports_reimport=report_reimport,
        counts=counts,
        search=tuple(search),
        advisor=advisor,
        supervisor=supervisor,
        duration_seconds=elapsed,
    )


def _store_counts(path: Path) -> dict[str, Any]:
    uri = "file:" + quote(path.absolute().as_posix(), safe="/:") + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        raise ReadinessError("STORE_READ_FAILED") from None
    connection.row_factory = sqlite3.Row
    try:
        total = int(connection.execute("SELECT count(*) FROM records").fetchone()[0])
        fts = int(connection.execute("SELECT count(*) FROM records_fts").fetchone()[0])
        by_source = {
            row["source_type"]: int(row["count"])
            for row in connection.execute(
                "SELECT source_type, count(*) AS count FROM records GROUP BY source_type"
            )
        }
        by_presence = {
            row["presence"]: int(row["count"])
            for row in connection.execute(
                "SELECT presence, count(*) AS count FROM records GROUP BY presence"
            )
        }
        by_account = {
            row["source_account"]: int(row["count"])
            for row in connection.execute(
                "SELECT source_account, count(*) AS count FROM records "
                "WHERE source_account IS NOT NULL GROUP BY source_account"
            )
        }
        by_authority = {
            row["authority_scope"]: int(row["count"])
            for row in connection.execute(
                "SELECT authority_scope, count(*) AS count FROM records GROUP BY authority_scope"
            )
        }
        by_truth = {
            row["truth_kind"]: int(row["count"])
            for row in connection.execute(
                "SELECT truth_kind, count(*) AS count FROM records GROUP BY truth_kind"
            )
        }
    except sqlite3.Error:
        raise ReadinessError("STORE_READ_FAILED") from None
    finally:
        connection.close()
    return {
        "total": total,
        "fts": fts,
        "by_source_type": by_source,
        "by_presence": by_presence,
        "by_account": by_account,
        "by_authority": by_authority,
        "by_truth_kind": by_truth,
    }


def _run_search(path: Path, probes: Sequence[SearchProbe]) -> list[dict[str, Any]]:
    reader, failure = open_reader(path, ReaderLimits(max_results=20))
    if reader is None:
        return [{"name": "OPEN", "status": failure or "NOT_AVAILABLE"}]
    results: list[dict[str, Any]] = []
    try:
        for probe in probes:
            response = reader.search(
                probe.text,
                request=OPERATOR,
                filters=probe.filters,
            )
            results.append(
                {
                    "name": probe.name,
                    "query": probe.text,
                    "status": response.status,
                    "error_code": response.error_code,
                    "total_count": response.total_count,
                    "returned_count": response.returned_count,
                    "source_types": sorted({hit.source_type for hit in response.results}),
                    "source_identifiers": sorted(
                        {hit.source_identifier for hit in response.results}
                    ),
                    "record_ids": sorted({hit.record_id for hit in response.results}),
                    "accounts": sorted(
                        {
                            hit.source_account
                            for hit in response.results
                            if hit.source_account is not None
                        }
                    ),
                    "conversation_ids": sorted(
                        {
                            hit.conversation_id
                            for hit in response.results
                            if hit.conversation_id is not None
                        }
                    ),
                    "message_ids": sorted(
                        {
                            hit.message_id
                            for hit in response.results
                            if hit.message_id is not None
                        }
                    ),
                    "relative_paths": sorted(
                        {
                            hit.relative_path
                            for hit in response.results
                            if hit.relative_path is not None
                        }
                    ),
                }
            )
    finally:
        reader.close()
    return results


def _run_access_check(path: Path, question: str, *, role: str) -> dict[str, Any]:
    public = RequestContext(caller_scope="PUBLIC", caller_id="bc11a-public")
    query = query_advisor_knowledge if role == "ADVISOR" else query_supervisor_knowledge
    operator_result = query(question, store_path=str(path), request=OPERATOR)
    public_result = query(question, store_path=str(path), request=public)
    bb = {"schemaVersion": "tradingai-context/v1", "authority": "NONE"}
    guarded = query(question, store_path=str(path), request=OPERATOR, bb_context=bb)
    return {
        "role": role,
        "operator_status": operator_result.get("knowledge_status"),
        "operator_authority": operator_result.get("authority"),
        "operator_trading_control": operator_result.get("trading_control"),
        "operator_system_instruction": operator_result.get("system_instruction"),
        "public_status": public_result.get("knowledge_status"),
        "public_returned": (public_result.get("knowledge") or {}).get("returned_count", 0),
        "bb_context_unchanged": guarded.get("bb_context") is bb,
        "untrusted_fence": str(operator_result.get("untrusted_context", "")).startswith(
            "BEGIN_UNTRUSTED_KNOWLEDGE"
        ),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _message(message_id: str, role: str, text: str, created: int = 1700000000) -> dict[str, Any]:
    return {
        "id": message_id,
        "author": {"role": role},
        "create_time": created,
        "content": {"content_type": "text", "parts": [text]},
    }


def _node(
    node_id: str,
    parent: str | None,
    children: list[str],
    message: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": node_id,
        "parent": parent,
        "children": children,
        "message": message,
    }


def _conversation(
    conversation_id: str,
    title: str,
    messages: tuple[tuple[str, str, str], ...],
    *,
    created: int = 1700000000,
    updated: int = 1700000100,
) -> dict[str, Any]:
    nodes = []
    parent: str | None = None
    for index, (message_id, role, text) in enumerate(messages):
        next_id = messages[index + 1][0] if index + 1 < len(messages) else None
        nodes.append(
            _node(
                message_id,
                parent,
                [next_id] if next_id else [],
                _message(message_id, role, text, created + index),
            )
        )
        parent = message_id
    return {
        "id": conversation_id,
        "title": title,
        "create_time": created,
        "update_time": updated,
        "mapping": {node["id"]: node for node in nodes},
    }


def _write_export(path: Path, conversations: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("conversations.json", json.dumps(conversations))


def build_synthetic_corpus(root: str | Path) -> SyntheticCorpus:
    """Build two explicit synthetic accounts and one Cursor report directory.

    Account A and Account B deliberately share the conversation ID and the
    message IDs. The account alias is the only separator, and the importer
    must never merge the two sources.
    """

    base = Path(root)
    base.mkdir(parents=True, exist_ok=True)
    export_a = base / "chatgpt_account_a.zip"
    export_b = base / "chatgpt_account_b.zip"
    report_dir = base / "cursor_reports"
    report_dir.mkdir(exist_ok=True)

    shared = lambda marker: _conversation(  # noqa: E731
        "conv-shared",
        "TradingAI shared conversation",
        (
            ("m1", "user", f"TradingAI {marker} first message"),
            ("m2", "assistant", f"Knowledge hub {marker} second message"),
        ),
    )
    outside = _conversation(
        "conv-pasta",
        "Pasta recipes",
        (("p1", "user", "Boil water and add salt."),),
    )
    secret = _conversation(
        "conv-secret",
        "TradingAI credentials",
        (("s1", "user", "TradingAI setup api_key=sk-synthetic000000000000000000"),),
    )
    _write_export(export_a, [shared("alphamarker"), outside, secret])
    _write_export(export_b, [shared("betamarker")])

    (report_dir / "cursor_alpha.md").write_text(
        "\n".join(
            [
                "TASK_ID: TRADINGAI-WORK-BC-11A-SYNTHETIC-A",
                "PHASE: BC-11A",
                "VERDICT: PASS",
                "cursoralphamarker TradingAI saved report",
            ]
        ),
        encoding="utf-8",
    )
    (report_dir / "cursor_beta.json").write_text(
        json.dumps(
            {
                "TASK_ID": "TRADINGAI-WORK-BC-11A-SYNTHETIC-B",
                "PHASE": "BC-11A",
                "VERDICT": "PASS",
                "TEST_RESULTS": "cursorbetamarker TradingAI saved report",
            }
        ),
        encoding="utf-8",
    )
    (report_dir / "notes.txt").write_text(
        "cursortextmarker TradingAI saved notes\n",
        encoding="utf-8",
    )
    (report_dir / "secret.md").write_text(
        "TASK_ID: SHOULD-NOT-IMPORT\npassword=hunter2\n",
        encoding="utf-8",
    )
    (report_dir / ".hidden.md").write_text("hidden cursorhiddenmarker\n", encoding="utf-8")
    (report_dir / "ignored.py").write_text("cursorignoredmarker = 1\n", encoding="utf-8")
    return SyntheticCorpus(
        root=base,
        export_a=export_a,
        export_b=export_b,
        report_dir=report_dir,
    )


def build_synthetic_stress_export(
    path: str | Path,
    *,
    conversation_count: int = 100,
    messages_per_conversation: int = 8,
    marker: str = "stressmarker",
) -> Path:
    """Build one larger synthetic export for an offline timing check."""

    conversations = []
    for index in range(conversation_count):
        messages = tuple(
            (
                f"c{index}-m{position}",
                "user" if position % 2 == 0 else "assistant",
                f"TradingAI {marker} conversation {index} message {position}",
            )
            for position in range(messages_per_conversation)
        )
        conversations.append(
            _conversation(
                f"conv-stress-{index}",
                f"TradingAI stress conversation {index}",
                messages,
            )
        )
    target = Path(path)
    _write_export(target, conversations)
    return target


__all__ = [
    "DEFAULT_ALLOWED_STORE_ROOT",
    "PRODUCTION_STORE_PATH",
    "READINESS_SCHEMA_VERSION",
    "ReadinessError",
    "ReadinessResult",
    "SearchProbe",
    "SyntheticCorpus",
    "assert_temporary_store",
    "build_synthetic_corpus",
    "build_synthetic_stress_export",
    "run_import_readiness",
]
