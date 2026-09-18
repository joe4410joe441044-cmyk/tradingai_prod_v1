"""Read-only Parameter Performance service (E-PERF-3).

This service is a thin, read-only projection over the two durable E-PERF-2
stores:

- :class:`~backend.strategy.parameters.revision_archive.ParameterRevisionArchive`
  (immutable promoted parameter revisions), and
- :class:`~backend.runtime.parameter_performance.ParameterPerformanceStore`
  (completed-trade Stage 13 records).

It never writes, never promotes and never changes any trading authority.  Its
only job is to group completed trades by the canonical identity
``(scope, effectiveRevision)`` and expose factual metrics and a parameter diff.

Historical truthfulness: values are only reported when an archive revision or a
completed-trade record actually carries them.  Missing history is reported as
unavailable; it is never reconstructed from the current configuration.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any, Mapping, Optional

from backend.runtime.parameter_performance import (
    DYNAMIC_AUTHORITY_PARAMETERS,
    ENTRY_SNAPSHOT_PARAMETERS,
    ParameterPerformanceStore,
    default_parameter_performance_store,
)
from backend.strategy.parameters.model import format_timestamp
from backend.strategy.parameters.registry import StrategyParameterRegistry
from backend.strategy.parameters.revision_archive import (
    ParameterRevisionArchive,
)

SUPPORTED_SCOPES = ("PAPER", "LIVE")

PARAMETER_SEMANTICS = {
    "entrySnapshotParameters": list(ENTRY_SNAPSHOT_PARAMETERS),
    "dynamicAuthorityParameters": list(DYNAMIC_AUTHORITY_PARAMETERS),
    "note": (
        "parameterValues is the parameter authority resolved at the entry "
        "decision boundary. entrySnapshotParameters were consumed as an "
        "immutable entry snapshot by the exit evaluator; "
        "dynamicAuthorityParameters were read from the current runtime "
        "authority during the trade and were NOT frozen at entry."
    ),
}


def _coerce_scope(scope: Any) -> Optional[str]:
    if scope is None:
        return None
    if isinstance(scope, str):
        value = scope.strip().upper()
        if value in SUPPORTED_SCOPES:
            return value
    raise ValueError("scope must be PAPER or LIVE")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compute_metrics(records: list) -> dict:
    """Deterministic factual metrics for a set of completed-trade records.

    Win/loss semantics are explicit: realized PnL > 0 is a win, < 0 is a loss
    and == 0 is breakeven.  Records without a numeric realized PnL are excluded
    from win/loss/win-rate and from PnL statistics (they remain in tradeCount).
    """

    pnl_records = [
        record
        for record in records
        if _is_number(record.get("realizedPnl"))
    ]
    pnls = [float(record["realizedPnl"]) for record in pnl_records]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    breakeven = [value for value in pnls if value == 0]

    holding = [
        float(record["holdingMs"])
        for record in records
        if _is_number(record.get("holdingMs"))
    ]

    exit_reasons = Counter(
        str(record.get("exitReason"))
        for record in records
        if record.get("exitReason")
    )

    return {
        "tradeCount": len(records),
        "pnlRecordCount": len(pnl_records),
        "winCount": len(wins),
        "lossCount": len(losses),
        "breakevenCount": len(breakeven),
        "winRate": (len(wins) / len(pnl_records)) if pnl_records else None,
        "realizedPnl": sum(pnls) if pnls else None,
        "averagePnl": mean(pnls) if pnls else None,
        "medianPnl": median(pnls) if pnls else None,
        "averageHoldingMs": mean(holding) if holding else None,
        "realizedPnlAuthoritative": bool(pnl_records) and all(
            record.get("realizedPnlAuthoritative") is True
            for record in pnl_records
        ),
        "exitReasons": [
            {"reason": reason, "count": count}
            for reason, count in sorted(
                exit_reasons.items(), key=lambda item: (-item[1], item[0])
            )
        ],
    }


class ParameterPerformanceReadService:
    """Read-only projection over the durable revision/performance stores."""

    def __init__(
        self,
        *,
        store: Optional[ParameterPerformanceStore] = None,
        archive: Optional[ParameterRevisionArchive] = None,
        base_directory=None,
    ):
        if base_directory is not None:
            base = Path(base_directory)
            if store is None:
                store = ParameterPerformanceStore(
                    base / "parameter_performance.jsonl"
                )
            if archive is None:
                archive = ParameterRevisionArchive(base_directory=base)
        self._store = store
        self._archive = archive

    @property
    def store(self) -> ParameterPerformanceStore:
        if self._store is None:
            self._store = default_parameter_performance_store()
        return self._store

    @property
    def archive(self) -> ParameterRevisionArchive:
        if self._archive is None:
            self._archive = ParameterRevisionArchive()
        return self._archive

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _records(
        self,
        *,
        scope: Optional[str],
        revision: Optional[int],
        symbol: Optional[str],
        mode: Optional[str],
    ) -> list:
        return self.store.history(
            scope=scope,
            revision=revision,
            symbol=symbol,
            mode=mode,
        )

    def _revision_summaries(
        self,
        records: list,
        *,
        scope: Optional[str],
    ) -> list:
        summaries: dict = {}

        archive_scopes = [scope] if scope else list(SUPPORTED_SCOPES)
        for candidate in archive_scopes:
            for parameter_set in self.archive.revisions(candidate):
                key = (candidate, parameter_set.effectiveRevision)
                summaries[key] = {
                    "scope": candidate,
                    "effectiveRevision": parameter_set.effectiveRevision,
                    "configuredRevision": parameter_set.configuredRevision,
                    "parameterSetId": parameter_set.parameterSetId,
                    "source": parameter_set.source.value,
                    "featureContract": None,
                    "capturedAt": (
                        format_timestamp(parameter_set.effectiveFrom)
                        if parameter_set.effectiveFrom is not None
                        else None
                    ),
                    "createdAt": format_timestamp(parameter_set.createdAt),
                    "parameterValues": {
                        name: parameter_set.parameters[name]
                        for name in sorted(parameter_set.parameters)
                    },
                    "valueSource": "REVISION_ARCHIVE",
                    "records": [],
                }

        for record in records:
            record_scope = record.get("scope")
            effective_revision = record.get("effectiveRevision")
            if record_scope not in SUPPORTED_SCOPES:
                continue
            key = (record_scope, effective_revision)
            entry = summaries.get(key)
            if entry is None:
                values = record.get("parameterSnapshot")
                entry = {
                    "scope": record_scope,
                    "effectiveRevision": effective_revision,
                    "configuredRevision": record.get("configuredRevision"),
                    "parameterSetId": record.get("parameterSetId"),
                    "source": None,
                    "featureContract": record.get("featureContract"),
                    "capturedAt": None,
                    "createdAt": None,
                    "parameterValues": (
                        dict(values) if isinstance(values, Mapping) else None
                    ),
                    "valueSource": (
                        "TRADE_RECORD"
                        if isinstance(values, Mapping) and values
                        else "UNAVAILABLE"
                    ),
                    "records": [],
                }
                summaries[key] = entry
            if entry.get("featureContract") is None and record.get(
                "featureContract"
            ):
                entry["featureContract"] = record.get("featureContract")
            entry["records"].append(record)

        result = []
        for key in sorted(
            summaries,
            key=lambda item: (
                str(item[0]),
                item[1] if isinstance(item[1], int) else -1,
            ),
        ):
            entry = summaries[key]
            result.append({
                "scope": entry["scope"],
                "effectiveRevision": entry["effectiveRevision"],
                "configuredRevision": entry["configuredRevision"],
                "parameterSetId": entry["parameterSetId"],
                "source": entry["source"],
                "featureContract": entry["featureContract"],
                "capturedAt": entry["capturedAt"],
                "createdAt": entry["createdAt"],
                "parameterValues": entry["parameterValues"],
                "valueSource": entry["valueSource"],
                "observedTradeCount": len(entry["records"]),
                "metrics": compute_metrics(entry["records"]),
            })
        return result

    def _find_summary(self, summaries: list, revision: int) -> Optional[dict]:
        for summary in summaries:
            if summary["effectiveRevision"] == revision:
                return summary
        return None

    # ------------------------------------------------------------------
    # public reads
    # ------------------------------------------------------------------

    def performance(
        self,
        *,
        scope: Optional[str] = None,
        revision: Optional[int] = None,
        symbol: Optional[str] = None,
        mode: Optional[str] = None,
        limit: int = 200,
    ) -> dict:
        normalized_scope = _coerce_scope(scope)
        try:
            normalized_limit = max(1, min(int(limit), 1000))
        except (TypeError, ValueError):
            normalized_limit = 200

        records = self._records(
            scope=normalized_scope,
            revision=revision,
            symbol=symbol,
            mode=mode,
        )
        summaries = self._revision_summaries(
            records, scope=normalized_scope
        )
        return {
            "available": bool(records) or bool(summaries),
            "scope": normalized_scope,
            "revision": revision,
            "symbol": symbol,
            "revisionCount": len(summaries),
            "recordCount": len(records),
            "revisions": summaries,
            "records": records[:normalized_limit],
            "metrics": compute_metrics(records),
            "semantics": PARAMETER_SEMANTICS,
        }

    def compare(
        self,
        *,
        scope: str,
        revision_a: int,
        revision_b: int,
    ) -> dict:
        normalized_scope = _coerce_scope(scope)
        if normalized_scope is None:
            raise ValueError("scope must be PAPER or LIVE")

        records = self._records(
            scope=normalized_scope,
            revision=None,
            symbol=None,
            mode=None,
        )
        summaries = self._revision_summaries(
            records, scope=normalized_scope
        )
        summary_a = self._find_summary(summaries, revision_a)
        summary_b = self._find_summary(summaries, revision_b)

        values_a = summary_a.get("parameterValues") if summary_a else None
        values_b = summary_b.get("parameterValues") if summary_b else None

        parameter_diff = []
        changed_count = 0
        for metadata in StrategyParameterRegistry.PARAMETERS:
            name = metadata.name
            value_a = values_a.get(name) if isinstance(values_a, Mapping) else None
            value_b = values_b.get(name) if isinstance(values_b, Mapping) else None
            changed = (
                _is_number(value_a)
                and _is_number(value_b)
                and float(value_a) != float(value_b)
            )
            delta = (
                float(value_b) - float(value_a)
                if _is_number(value_a) and _is_number(value_b)
                else None
            )
            if changed:
                changed_count += 1
            parameter_diff.append({
                "name": name,
                "labelEn": metadata.label_en,
                "labelJa": metadata.label_ja,
                "unit": metadata.unit,
                "a": value_a,
                "b": value_b,
                "delta": delta,
                "changed": changed,
            })

        return {
            "available": summary_a is not None or summary_b is not None,
            "scope": normalized_scope,
            "revisionA": summary_a,
            "revisionB": summary_b,
            "parameterDiff": parameter_diff,
            "changedCount": changed_count,
            "semantics": PARAMETER_SEMANTICS,
        }


def default_parameter_performance_read_service() -> ParameterPerformanceReadService:
    return ParameterPerformanceReadService()
