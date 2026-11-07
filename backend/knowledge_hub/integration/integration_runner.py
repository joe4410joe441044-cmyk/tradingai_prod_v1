"""Opt-in end-to-end integration of the isolated Knowledge Hub components.

This runner reuses the existing BC-2 through BC-7 modules. It writes only to
the caller-supplied store path and reads only caller-supplied synthetic paths.
It does not call the production Advisor or Supervisor, register a scheduler,
contact a network, or touch a production runtime.
"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from ..chatgpt_import import import_export
from ..chatgpt_sync import create_approval, preview_export_sync, sync_export
from ..config import CollectorConfig
from ..continuous_sync import (
    SOURCE_KIND_REPORT_DIR,
    SOURCE_KIND_REPOSITORY,
    ContinuousSyncEngine,
    SourceSpec,
    SyncLimits,
)
from ..knowledge_access import (
    executed_commands,
    query_advisor_knowledge,
    query_supervisor_knowledge,
)
from ..knowledge_ingest import ingest_collection
from ..knowledge_store import FORBIDDEN_TRUTH, KnowledgeStore, StoreLimits
from ..reader import ReaderFilters, ReaderLimits, RequestContext, open_reader
from ..source_collector import collect_sources
from .integration_models import (
    STAGE_FAILED,
    STAGE_OK,
    IntegrationConfig,
    IntegrationResult,
    StageResult,
)


COLLECTOR_CONFIG = CollectorConfig(include_text=True, max_files=200)
STORE_LIMITS = StoreLimits(max_results=2_000, max_batch_size=500)
READER_LIMITS = ReaderLimits(max_results=50)

OPERATOR = RequestContext(caller_scope="OPERATOR", caller_id="bc8-operator")
PUBLIC = RequestContext(caller_scope="PUBLIC", caller_id="bc8-public")


def _sync_limits(workdir: Path) -> SyncLimits:
    root = Path(workdir).resolve()
    return SyncLimits(
        max_commit_scan_depth=50,
        max_worktrees=20,
        max_scan_seconds=120,
        max_report_files=50,
        max_report_file_bytes=262_144,
        max_report_content_bytes=131_072,
        max_batch_size=200,
        allowed_repository_roots=(root,),
        allowed_worktree_roots=(root,),
        allowed_report_roots=(root,),
    )


def _open_or_create_store(store_path: Path) -> None:
    if not Path(store_path).exists():
        KnowledgeStore.create(store_path, STORE_LIMITS).close()


def _store_counts(store_path: Path) -> tuple[int, dict[str, int]]:
    store = KnowledgeStore.open(store_path, STORE_LIMITS)
    try:
        rows = store.list_records(limit=STORE_LIMITS.max_results)
    finally:
        store.close()
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row["source_type"])
        counts[key] = counts.get(key, 0) + 1
    return len(rows), counts


def _stage(name: str, started: float, status: str, detail: str = "", **metrics: Any) -> StageResult:
    payload = dict(metrics)
    payload["elapsed_seconds"] = round(perf_counter() - started, 6)
    return StageResult(name=name, status=status, detail=detail, metrics=payload)


def _bc2_source_collection(config: IntegrationConfig) -> StageResult:
    started = perf_counter()
    batch = collect_sources(config.repository, config=COLLECTOR_CONFIG)
    store = KnowledgeStore.open(config.store_path, STORE_LIMITS)
    try:
        result = ingest_collection(
            store,
            batch,
            indexed_at=config.indexed_at,
            scan_scope="bc2-source",
        )
    finally:
        store.close()
    ok = batch.error is None and result.error is None
    detail = "" if ok else f"collector={batch.error} store={result.error}"
    return _stage(
        "BC2_SOURCE_COLLECTION",
        started,
        STAGE_OK if ok else STAGE_FAILED,
        detail,
        collected=len(batch.records),
        inserted=result.inserted,
        skipped=result.skipped,
        rejected=result.rejected,
    )


def _bc6_continuous_sync(config: IntegrationConfig) -> StageResult:
    started = perf_counter()
    sources: list[SourceSpec] = [SourceSpec(path=config.repository, kind=SOURCE_KIND_REPOSITORY)]
    for path, agent in config.report_sources:
        sources.append(SourceSpec(path=path, kind=SOURCE_KIND_REPORT_DIR, agent=agent))
    engine = ContinuousSyncEngine(
        limits=_sync_limits(config.workdir),
        config=COLLECTOR_CONFIG,
    )
    store = KnowledgeStore.open(config.store_path, STORE_LIMITS)
    try:
        report = engine.sync(
            tuple(sources),
            store,
            store_path=config.store_path,
            indexed_at=config.indexed_at,
            scan_scope="bc6-continuous",
        )
    finally:
        store.close()
    ok = report.status != "ERROR"
    return _stage(
        "BC6_CONTINUOUS_SYNC",
        started,
        STAGE_OK if ok else STAGE_FAILED,
        "" if ok else ",".join(report.errors),
        report_status=report.status,
        repositories=report.repository_count,
        worktrees=report.worktree_count,
        commits=report.commit_count,
        reports=report.report_count,
        inserted=report.inserted,
        skipped=report.skipped,
        rejected=report.rejected,
    )


def _bc3_store(config: IntegrationConfig) -> StageResult:
    started = perf_counter()
    store = KnowledgeStore.open(config.store_path, STORE_LIMITS)
    try:
        integrity = store.integrity_check()
        version = store.schema_version()
        rows = store.list_records(limit=STORE_LIMITS.max_results)
    finally:
        store.close()
    ok = integrity == "OK" and bool(rows)
    return _stage(
        "BC3_KNOWLEDGE_STORE",
        started,
        STAGE_OK if ok else STAGE_FAILED,
        "",
        integrity=integrity,
        schema_version=version,
        record_count=len(rows),
    )


def _bc5_import(config: IntegrationConfig, alias: str, source: Path) -> StageResult:
    started = perf_counter()
    store = KnowledgeStore.open(config.store_path, STORE_LIMITS)
    try:
        report = import_export(
            source,
            alias,
            store,
            indexed_at=config.indexed_at,
            scan_scope=f"bc5-import:{alias}",
        )
    finally:
        store.close()
    ok = report.status == "OK" and report.inserted > 0
    return _stage(
        f"BC5_IMPORT_{alias}",
        started,
        STAGE_OK if ok else STAGE_FAILED,
        "" if ok else str(report.error),
        report_status=report.status,
        conversations=report.conversation_count,
        messages=report.message_count,
        inserted=report.inserted,
        skipped=report.skipped,
        rejected=report.rejected,
    )


def _bc7_refresh(
    config: IntegrationConfig,
    alias: str,
    source: Path,
    *,
    observed_at: str,
    indexed_at: str,
) -> StageResult:
    started = perf_counter()
    preview = preview_export_sync(
        source,
        alias,
        store_path=config.store_path,
        observed_at=observed_at,
    )
    if preview.status != "OK" or preview.export_identity is None:
        return _stage(
            f"BC7_REFRESH_{alias}",
            started,
            STAGE_FAILED,
            str(preview.error),
        )
    approval = create_approval(preview, store_path=config.store_path, approved_at=observed_at)
    report = sync_export(
        source,
        alias,
        config.store_path,
        observed_at=observed_at,
        indexed_at=indexed_at,
        preview=preview,
        approval=approval,
    )
    ok = report.status in {"OK", "PARTIAL"}
    return _stage(
        f"BC7_REFRESH_{alias}",
        started,
        STAGE_OK if ok else STAGE_FAILED,
        "" if ok else str(report.error),
        report_status=report.status,
        export_state=report.export_state,
        inserted=report.inserted,
        skipped=report.skipped,
        superseded=report.superseded,
        checkpoint_updated=report.checkpoint_updated,
    )


def _reader_summary(response) -> dict[str, Any]:
    payload = response.to_dict()
    return {
        "status": payload["status"],
        "error_code": payload["error_code"],
        "returned_count": payload["returned_count"],
        "total_count": payload["total_count"],
        "source_types": sorted({hit["source_type"] for hit in payload["results"]}),
        "record_ids": [hit["record_id"] for hit in payload["results"]],
        "provenance_complete": all(
            hit["source_type"]
            and hit["source_identifier"]
            and hit["truth_kind"]
            and hit["authority_scope"] == "NONE"
            for hit in payload["results"]
        ),
    }


def _bc4_search(config: IntegrationConfig) -> tuple[StageResult, dict[str, Any], float]:
    started = perf_counter()
    plan = {
        "source": ReaderFilters(source_type="SOURCE_FILE"),
        "git": ReaderFilters(source_type="GIT_COMMIT"),
        "worktree": ReaderFilters(source_type="GIT_WORKTREE"),
        "cursor": ReaderFilters(source_type="CURSOR_REPORT"),
        "vscode": ReaderFilters(source_type="VSCODE_REPORT"),
        "chatgpt_a": ReaderFilters(source_type="CHATGPT_EXPORT", source_account=config.account_a),
        "chatgpt_b": ReaderFilters(source_type="CHATGPT_EXPORT", source_account=config.account_b),
    }
    summaries: dict[str, Any] = {}
    reader, failure = open_reader(config.store_path, READER_LIMITS)
    if reader is None:
        return (
            _stage("BC4_KNOWLEDGE_SEARCH", started, STAGE_FAILED, str(failure)),
            {"failure": failure},
            0.0,
        )
    search_started = perf_counter()
    try:
        for label, filters in plan.items():
            response = reader.search(
                config.search_question,
                request=OPERATOR,
                filters=filters,
            )
            summaries[label] = _reader_summary(response)
    finally:
        reader.close()
    latency = round(perf_counter() - search_started, 6)
    missing = [label for label, item in summaries.items() if item["returned_count"] < 1]
    ok = not missing
    return (
        _stage(
            "BC4_KNOWLEDGE_SEARCH",
            started,
            STAGE_OK if ok else STAGE_FAILED,
            "" if ok else "NO_RESULT:" + ",".join(missing),
            queries=len(summaries),
            latency_seconds=latency,
        ),
        summaries,
        latency,
    )


def _knowledge_queries(config: IntegrationConfig) -> tuple[StageResult, dict, dict, dict]:
    started = perf_counter()
    advisor = query_advisor_knowledge(
        config.advisor_question,
        store_path=str(config.store_path),
        request=OPERATOR,
        bb_context=config.bb_context,
    )
    supervisor = query_supervisor_knowledge(
        config.supervisor_question,
        store_path=str(config.store_path),
        request=OPERATOR,
        bb_context=config.bb_context,
    )
    access = _access_checks(config)
    advisor_ok = (
        advisor["knowledge_status"] in {"OK", "EMPTY"}
        and advisor["authority"] == "NONE"
        and advisor["trading_control"] == "FORBIDDEN"
        and advisor["system_instruction"] is False
        and advisor["bb_context_unchanged"] is True
        and dict(advisor["bb_context"]) == dict(config.bb_context)
        and executed_commands(advisor) == ()
    )
    supervisor_ok = (
        supervisor["knowledge_status"] in {"OK", "EMPTY"}
        and supervisor["authority"] == "NONE"
        and supervisor["trading_control"] == "FORBIDDEN"
        and supervisor["system_instruction"] is False
        and supervisor["bb_context_unchanged"] is True
        and dict(supervisor["bb_context"]) == dict(config.bb_context)
        and executed_commands(supervisor) == ()
    )
    access_ok = (
        access["public_returns_operator_only"] is False
        and access["privilege_escalation_denied"] is True
    )
    ok = advisor_ok and supervisor_ok and access_ok
    return (
        _stage(
            "BC4_ADVISOR_SUPERVISOR_ACCESS",
            started,
            STAGE_OK if ok else STAGE_FAILED,
            "",
            advisor_status=advisor["knowledge_status"],
            supervisor_status=supervisor["knowledge_status"],
            advisor_ok=advisor_ok,
            supervisor_ok=supervisor_ok,
            access_ok=access_ok,
        ),
        _summarize_attachment(advisor),
        _summarize_attachment(supervisor),
        access,
    )


def _access_checks(config: IntegrationConfig) -> dict[str, Any]:
    reader, failure = open_reader(config.store_path, READER_LIMITS)
    if reader is None:
        return {
            "failure": failure,
            "public_returns_operator_only": True,
            "privilege_escalation_denied": False,
        }
    try:
        public = reader.search(config.search_question, request=PUBLIC)
        operator_public = reader.search(
            config.search_question,
            request=OPERATOR,
            filters=ReaderFilters(requested_access="PUBLIC"),
        )
        escalation = reader.search(
            config.search_question,
            request=PUBLIC,
            filters=ReaderFilters(requested_access="OPERATOR"),
        )
    finally:
        reader.close()
    return {
        "public_returned": public.returned_count,
        "operator_public_returned": operator_public.returned_count,
        "public_returns_operator_only": public.returned_count > 0,
        "escalation_status": escalation.status,
        "privilege_escalation_denied": escalation.status == "ACCESS_DENIED",
    }


def _summarize_attachment(attachment: dict) -> dict[str, Any]:
    knowledge = attachment.get("knowledge") or {}
    return {
        "knowledge_status": attachment["knowledge_status"],
        "authority": attachment["authority"],
        "trading_control": attachment["trading_control"],
        "system_instruction": attachment["system_instruction"],
        "bb_context_unchanged": attachment["bb_context_unchanged"],
        "executed_commands": list(executed_commands(attachment)),
        "context_truncated": attachment["context_truncated"],
        "untrusted_context": attachment["untrusted_context"],
        "result_count": len(knowledge.get("results", ())) if knowledge else 0,
        "truth_kinds": sorted({hit.get("truth_kind") for hit in knowledge.get("results", ()) if hit})
        if knowledge
        else [],
    }


def _provenance_stage(config: IntegrationConfig) -> StageResult:
    started = perf_counter()
    store = KnowledgeStore.open(config.store_path, STORE_LIMITS)
    try:
        rows = store.list_records(limit=STORE_LIMITS.max_results)
    finally:
        store.close()
    incomplete = [
        row["record_id"]
        for row in rows
        if not row["source_type"]
        or not row["source_identifier"]
        or not row["truth_kind"]
        or row["authority_scope"] != "NONE"
        or not row["collected_at"]
    ]
    forbidden = [row["record_id"] for row in rows if row["truth_kind"] in FORBIDDEN_TRUTH]
    ok = not incomplete and not forbidden
    return _stage(
        "PROVENANCE_AND_TRUTH_BOUNDARY",
        started,
        STAGE_OK if ok else STAGE_FAILED,
        "" if ok else "INCOMPLETE_OR_FORBIDDEN",
        records=len(rows),
        incomplete=len(incomplete),
        forbidden_truth=len(forbidden),
    )


def run_isolated_integration(config: IntegrationConfig) -> IntegrationResult:
    """Run the bounded synthetic end-to-end pipeline once.

    The caller owns every path. A failure in one stage is recorded and does
    not raise, so a degraded stage cannot take down a caller.
    """

    _open_or_create_store(config.store_path)
    stages: list[StageResult] = []
    stages.append(_bc2_source_collection(config))
    stages.append(_bc6_continuous_sync(config))
    stages.append(_bc3_store(config))

    stages.append(_bc5_import(config, config.account_a, config.account_a_export))
    stages.append(_bc5_import(config, config.account_b, config.account_b_export))
    stages.append(
        _bc7_refresh(
            config,
            config.account_a,
            config.refresh_a_export or config.account_a_export,
            observed_at=config.refresh_observed_at,
            indexed_at=config.refresh_indexed_at,
        )
    )
    stages.append(
        _bc7_refresh(
            config,
            config.account_b,
            config.refresh_b_export or config.account_b_export,
            observed_at=config.refresh_observed_at,
            indexed_at=config.refresh_indexed_at,
        )
    )

    search_stage, search, search_latency = _bc4_search(config)
    stages.append(search_stage)
    query_stage, advisor, supervisor, access = _knowledge_queries(config)
    stages.append(query_stage)
    stages.append(_provenance_stage(config))

    record_count, source_type_counts = _store_counts(config.store_path)
    latencies = {
        "search_seconds": search_latency,
        "total_seconds": round(sum(item.metrics.get("elapsed_seconds", 0.0) for item in stages), 6),
    }
    return IntegrationResult(
        stages=tuple(stages),
        store_path=str(config.store_path),
        record_count=record_count,
        source_type_counts=source_type_counts,
        search=search,
        advisor=advisor,
        supervisor=supervisor,
        access=access,
        latencies=latencies,
        bb_context=dict(config.bb_context),
    )
