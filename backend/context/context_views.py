"""Allowlisted PUBLIC and OPERATOR views of a canonical Context Pack.

Both views are pure projections. Neither view authenticates a caller, opens
a network connection, or copies unknown fields. Secrets and absolute
filesystem paths are removed structurally, not only by string matching.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Mapping

from .builder import REDACTED, _SENSITIVE_NAME, _redact
from .schema import SCHEMA_VERSION, CanonicalContext
from .serializer import context_to_dict

PUBLIC_CONTEXT = "PUBLIC_CONTEXT"
OPERATOR_CONTEXT = "OPERATOR_CONTEXT"

DEFAULT_VIEW_MAX_BYTES = 262144
DEFAULT_MAX_STRING = 4000
DEFAULT_MAX_LIST = 512

_PATH_REDACTED = "[REDACTED:PATH]"
_SAFE_DOC = re.compile(r"^docs/ai/[A-Za-z0-9_./-]+$")
_EXTRA_SECRET_NAME = re.compile(
    r"(?i)(?:^|[._-])(?:env|dotenv|credential|passwd|secret)(?:$|[._-])|\.env"
)
_DOTENV_VALUE = re.compile(r"(?i)\.env\b")
_ABS_PATH = re.compile(
    r"(?:^|[\s\"'=])(?:~[/\\]|/(?:home|tmp|usr|var|opt|etc|root|Users)/)|"
    r"^[A-Za-z]:\\"
)

_GUIDANCE = {
    "role": "READ_ONLY",
    "orders": False,
    "botControl": False,
    "emergencyControl": False,
    "authorityChange": False,
    "diagnosticScopeUnknownIsNotCurrent": True,
    "freshnessEvaluatedAtIsPackTime": True,
}
_TIME_NOTE = {
    "contextGeneratedAt": "CanonicalContext.generatedAt",
    "freshnessEvaluatedAt": "context pack aggregation time, not a runtime observation",
    "sectionObservedAt": "producer timestamp on section meta when one was proven",
}

_DOMAIN_FIELDS = frozenset(
    {
        "status",
        "state",
        "enabled",
        "selectedMode",
        "dryRun",
        "autoTradeEnabled",
        "realOrderAllowed",
        "mode",
        "executionEnabled",
        "riskProfile",
        "locked",
        "authoritativeRuntimeState",
        "synchronizationState",
        "pendingOrderState",
        "activeSymbol",
        "marketReady",
        "marketStale",
        "lastUpdate",
        "selectionMode",
        "selectionSource",
        "amsRuntimeState",
        "selectionCycleId",
        "safeSwitchState",
        "suitabilityEvidenceState",
        "backendStatus",
        "runtimeHealthy",
    }
)
_MM_SNAPSHOT_FIELDS = frozenset(
    {
        "capitalAuthority",
        "capitalSource",
        "equity",
        "availableCapital",
        "mmMode",
        "mmRegime",
        "riskBudget",
        "remainingExposure",
        "remainingPositionCapacity",
        "ruinGuardStatus",
        "compoundingEnabled",
        "executionEntryAllowed",
        "policyVersion",
        "authorityFresh",
        "drawdown",
        "currentExposure",
        "openPositionState",
        "reasonCodes",
    }
)
_POSITION_FIELDS = frozenset(
    {
        "status",
        "reportedStatus",
        "symbol",
        "mode",
        "side",
        "quantity",
        "contractQuantity",
        "coinQuantity",
        "avgEntry",
        "avgExit",
        "entryTime",
        "exitTime",
        "pnlUsdt",
        "pnlPercent",
        "durationSeconds",
        "leverage",
        "riskPercent",
        "stopLossPercent",
        "takeProfitPercent",
        "trailingPercent",
        "timeExitSeconds",
        "ambiguity",
        "positionCount",
        "observationScope",
    }
)
_SMALL_ACCOUNT_FIELDS = frozenset(
    {
        "availableCapital",
        "riskBudget",
        "riskPercent",
        "leverage",
        "stopLossPercent",
        "takeProfitPercent",
        "trailingPercent",
        "timeExitSeconds",
        "marginMode",
        "parameterRevision",
        "mmStatus",
        "blockers",
        "sourceUpdatedAt",
    }
)
_EXECUTION_FIELDS = frozenset(
    {
        "selectedMode",
        "tradeMode",
        "executionMode",
        "controlAuthority",
        "entryAuthority",
        "realOrderAllowed",
        "realOrderAllowedEvidence",
        "botState",
        "loopState",
        "emergencyState",
        "modeMismatch",
        "supervisorSelectedMode",
        "supervisorTradeMode",
        "supervisorRealOrderAllowed",
        "authoritativeRuntimeState",
        "synchronizationState",
        "pendingOrderState",
        "dryRun",
        "autoTradeEnabled",
    }
)
_STEP_SUFFIXES = (
    "index",
    "name",
    "status",
    "current",
    "required",
    "blocker",
    "blockerType",
    "userActionRequired",
    "evaluatedAt",
    "provenance",
    "freshness",
)


def _account_fields() -> frozenset[str]:
    names = {"mode", "modeSourceConflict", "observationScope"}
    bases = (
        "balance",
        "equity",
        "available",
        "unrealizedPnl",
        "realizedPnl",
        "marginUsed",
        "currency",
    )
    for prefix in ("", "paper", "live"):
        for base in bases:
            names.add(base if not prefix else prefix + base[:1].upper() + base[1:])
    return frozenset(names)


def _cycle_fields() -> frozenset[str]:
    names = {
        "diagnosticScope",
        "cycleState",
        "rootBlocker",
        "rootBlockerStep",
        "diagnosticsGeneratedAt",
        "sourceUpdatedAt",
        "stepCount",
    }
    names.update(_DOMAIN_FIELDS)
    for index in range(15):
        for suffix in _STEP_SUFFIXES:
            names.add(f"step.{index}.{suffix}")
    return frozenset(names)


_SECTION_FIELDS = {
    "runtime": _DOMAIN_FIELDS,
    "marketSelection": frozenset(
        {
            "activeSymbol",
            "selectionMode",
            "selectionSource",
            "amsRuntimeState",
            "selectionCycleId",
            "safeSwitchState",
            "suitabilityEvidenceState",
        }
    ),
    "executionControl": _EXECUTION_FIELDS,
    "market": _DOMAIN_FIELDS,
    "moneyManagement": _MM_SNAPSHOT_FIELDS,
    "governance": _DOMAIN_FIELDS,
    "tradingCycle": _cycle_fields(),
    "position": _POSITION_FIELDS,
    "orders": frozenset({"pendingOrderState"}),
    "smallAccount": _SMALL_ACCOUNT_FIELDS,
    "account": _account_fields(),
    "emergency": _DOMAIN_FIELDS,
    "health": _DOMAIN_FIELDS,
}

_SAFETY_FIELDS = (
    "contextRead",
    "sourceWrite",
    "runtimeWrite",
    "orderWrite",
    "liveOrder",
    "productionDeploy",
    "secretsIncluded",
    "paperLiveAuthorityUnchanged",
    "botManualAuthorityUnchanged",
    "emergencyStateUnchanged",
)
_FRESHNESS_FIELDS = (
    "overall",
    "availability",
    "evaluatedAt",
    "staleSections",
    "unknownSections",
    "unavailableSections",
    "sectionCount",
)


def _secret_name(name: object) -> bool:
    text = str(name)
    return _SENSITIVE_NAME.search(text) is not None or _EXTRA_SECRET_NAME.search(text) is not None


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _bounded_string(value: str, max_string: int) -> str | dict[str, object]:
    redacted = _redact(value)
    if _DOTENV_VALUE.search(redacted):
        return REDACTED
    if redacted.startswith("/") or redacted.startswith("~/") or _ABS_PATH.search(redacted):
        return _PATH_REDACTED
    if len(redacted) > max_string:
        return {
            "state": "UNAVAILABLE",
            "reason": "STRING_LIMIT_EXCEEDED",
            "length": len(redacted),
        }
    return redacted


def scrub_context_tree(
    value: Any,
    *,
    max_string: int = DEFAULT_MAX_STRING,
    max_list: int = DEFAULT_MAX_LIST,
) -> Any:
    """Drop secret keys at every depth and bound strings and lists.

    An oversized list or string is replaced. It is not truncated, because a
    prefix can still carry a secret or an internal path.
    """

    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key in value:
            if _secret_name(key):
                continue
            cleaned[str(key)] = scrub_context_tree(
                value[key], max_string=max_string, max_list=max_list
            )
        return cleaned
    if isinstance(value, (list, tuple)):
        if len(value) > max_list:
            return {
                "state": "UNAVAILABLE",
                "reason": "LIST_LIMIT_EXCEEDED",
                "length": len(value),
            }
        return [
            scrub_context_tree(item, max_string=max_string, max_list=max_list)
            for item in value
        ]
    if isinstance(value, str):
        return _bounded_string(value, max_string)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _bounded_string(str(value), max_string)


def _safe_docs(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    kept: list[str] = []
    for item in values:
        if isinstance(item, str) and _SAFE_DOC.fullmatch(item) and ".." not in item:
            kept.append(item)
    return kept


def _safety(payload: Mapping[str, Any]) -> dict[str, object]:
    safety = payload.get("safety")
    if not isinstance(safety, Mapping):
        safety = {}
    return {name: safety.get(name) for name in _SAFETY_FIELDS}


def _freshness(payload: Mapping[str, Any]) -> dict[str, object]:
    freshness = payload.get("freshness")
    if not isinstance(freshness, Mapping):
        freshness = {}
    return {name: freshness.get(name) for name in _FRESHNESS_FIELDS}


def _project_public(payload: Mapping[str, Any]) -> dict[str, object]:
    workstreams = payload.get("workstreams")
    contracts = payload.get("contracts")
    items = workstreams.get("items") if isinstance(workstreams, Mapping) else ()
    contract_items = contracts.get("items") if isinstance(contracts, Mapping) else ()
    public_workstreams = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, Mapping):
                continue
            public_workstreams.append(
                {
                    "workstreamId": item.get("workstreamId"),
                    "status": item.get("status"),
                    "verification": item.get("verification"),
                }
            )
    references: list[str] = []
    public_contracts = []
    if isinstance(contract_items, list):
        for item in contract_items:
            if not isinstance(item, Mapping):
                continue
            public_contracts.append(
                {
                    "contractId": item.get("contractId"),
                    "title": item.get("title"),
                    "status": item.get("status"),
                }
            )
            references.extend(_safe_docs([item.get("documentPath")]))
            references.extend(_safe_docs(item.get("references")))
    return {
        "workstreams": public_workstreams,
        "contracts": public_contracts,
        "documentationReferences": sorted(set(references)),
    }


def _source_public(payload: Mapping[str, Any]) -> dict[str, object]:
    source = payload.get("source") if isinstance(payload.get("source"), Mapping) else {}
    meta = source.get("meta") if isinstance(source.get("meta"), Mapping) else {}
    return {
        "availability": meta.get("availability"),
        "freshness": meta.get("freshness"),
        "deployedCommitState": source.get("deployedCommitState"),
    }


def _envelope(view_name: str, body: Mapping[str, Any]) -> dict[str, object]:
    return {
        "view": view_name,
        "schemaVersion": SCHEMA_VERSION,
        "authentication": "NOT_ASSERTED",
        "consumerGuidance": dict(_GUIDANCE),
        "timeSemantics": dict(_TIME_NOTE),
        **body,
    }


def _limit_or_body(
    view: dict[str, object],
    *,
    max_bytes: int,
) -> dict[str, object]:
    encoded = view_to_json(view).encode("utf-8")
    if len(encoded) <= max_bytes:
        return view
    return {
        "view": view["view"],
        "schemaVersion": SCHEMA_VERSION,
        "authentication": "NOT_ASSERTED",
        "consumerGuidance": dict(_GUIDANCE),
        "availability": "UNAVAILABLE",
        "reason": "PAYLOAD_LIMIT_EXCEEDED",
        "limitBytes": max_bytes,
        "actualBytes": len(encoded),
    }


def _finish(
    view: dict[str, object],
    *,
    max_bytes: int,
    max_string: int,
    max_list: int,
) -> dict[str, object]:
    scrubbed = scrub_context_tree(view, max_string=max_string, max_list=max_list)
    if not isinstance(scrubbed, dict):
        scrubbed = {"view": view.get("view"), "schemaVersion": SCHEMA_VERSION}
    return _limit_or_body(scrubbed, max_bytes=max_bytes)


def build_public_context_view(
    context: CanonicalContext,
    *,
    max_bytes: int = DEFAULT_VIEW_MAX_BYTES,
    max_string: int = DEFAULT_MAX_STRING,
    max_list: int = DEFAULT_MAX_LIST,
) -> dict[str, object]:
    """Project the minimum public allowlist.

    Account, position, authority, emergency state, Git paths, and credentials
    are not copied. A field that is not named above cannot become public.
    """

    if not isinstance(context, CanonicalContext):
        raise TypeError("CanonicalContext required")
    payload = context_to_dict(context)
    body = _envelope(
        PUBLIC_CONTEXT,
        {
            "generatedAt": payload.get("generatedAt"),
            "safety": _safety(payload),
            "freshness": _freshness(payload),
            "project": _project_public(payload),
            "source": _source_public(payload),
        },
    )
    return _finish(body, max_bytes=max_bytes, max_string=max_string, max_list=max_list)


def _field_view(item: Mapping[str, Any]) -> dict[str, object]:
    return {
        "name": item.get("name"),
        "state": item.get("state"),
        "value": item.get("value"),
        "source": item.get("source"),
        "observedAt": item.get("observedAt"),
        "freshness": item.get("freshness"),
    }


def _section_view(section: Any, allowed: frozenset[str]) -> dict[str, object]:
    if not isinstance(section, Mapping):
        return {"meta": {}, "fields": []}
    meta = section.get("meta") if isinstance(section.get("meta"), Mapping) else {}
    raw_fields = section.get("fields") if isinstance(section.get("fields"), list) else []
    fields = []
    for item in raw_fields:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if not isinstance(name, str) or name not in allowed or _secret_name(name):
            continue
        fields.append(_field_view(item))
    return {
        "meta": {
            "source": meta.get("source"),
            "observedAt": meta.get("observedAt"),
            "freshness": meta.get("freshness"),
            "availability": meta.get("availability"),
        },
        "fields": fields,
    }


def _source_operator(payload: Mapping[str, Any]) -> dict[str, object]:
    source = payload.get("source") if isinstance(payload.get("source"), Mapping) else {}
    meta = source.get("meta") if isinstance(source.get("meta"), Mapping) else {}
    return {
        "branch": source.get("branch"),
        "head": source.get("head"),
        "originMain": source.get("originMain"),
        "ahead": source.get("ahead"),
        "behind": source.get("behind"),
        "dirty": source.get("dirty"),
        "deployedCommit": source.get("deployedCommit"),
        "deployedCommitState": source.get("deployedCommitState"),
        "availability": meta.get("availability"),
        "freshness": meta.get("freshness"),
    }


def _string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, str)]


def _project_operator(payload: Mapping[str, Any]) -> dict[str, object]:
    workstreams = payload.get("workstreams")
    contracts = payload.get("contracts")
    issues = payload.get("knownIssues")
    tests = payload.get("acceptedTests")
    items = workstreams.get("items") if isinstance(workstreams, Mapping) else ()
    projected = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, Mapping):
                continue
            projected.append(
                {
                    "workstreamId": item.get("workstreamId"),
                    "name": item.get("name"),
                    "owner": item.get("owner"),
                    "branch": item.get("branch"),
                    "status": item.get("status"),
                    "verification": item.get("verification"),
                    "evidenceReferences": _safe_docs(item.get("evidenceReferences"))
                    + [
                        ref
                        for ref in _string_list(item.get("evidenceReferences"))
                        if ref.startswith("git:branch:") and ".." not in ref
                    ],
                }
            )
    contract_items = contracts.get("items") if isinstance(contracts, Mapping) else ()
    projected_contracts = []
    if isinstance(contract_items, list):
        for item in contract_items:
            if not isinstance(item, Mapping):
                continue
            projected_contracts.append(
                {
                    "contractId": item.get("contractId"),
                    "title": item.get("title"),
                    "owner": item.get("owner"),
                    "status": item.get("status"),
                    "verified": item.get("verified"),
                    "documentPath": next(iter(_safe_docs([item.get("documentPath")])), None),
                }
            )
    issue_items = issues.get("items") if isinstance(issues, Mapping) else ()
    projected_issues = []
    if isinstance(issue_items, list):
        for item in issue_items:
            if not isinstance(item, Mapping):
                continue
            projected_issues.append(
                {
                    "issueId": item.get("issueId"),
                    "title": item.get("title"),
                    "workstream": item.get("workstream"),
                    "status": item.get("status"),
                }
            )
    test_items = tests.get("items") if isinstance(tests, Mapping) else ()
    projected_tests = []
    if isinstance(test_items, list):
        for item in test_items:
            if not isinstance(item, Mapping):
                continue
            projected_tests.append(
                {
                    "testId": item.get("testId"),
                    "status": item.get("status"),
                }
            )
    return {
        "workstreams": projected,
        "contracts": projected_contracts,
        "knownIssues": projected_issues,
        "acceptedTests": projected_tests,
    }


def _provenance(payload: Mapping[str, Any]) -> list[dict[str, object]]:
    summary = payload.get("provenance")
    entries = summary.get("entries") if isinstance(summary, Mapping) else ()
    projected = []
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, Mapping):
                continue
            projected.append(
                {
                    "source": item.get("source"),
                    "reader": item.get("reader"),
                    "observedAt": item.get("observedAt"),
                }
            )
    return projected


def _failure_view(failures: tuple[Any, ...] | list[Any]) -> list[dict[str, object]]:
    projected = []
    for item in failures:
        source = getattr(item, "source", None)
        category = getattr(item, "category", None)
        if source not in {
            "supervisor_snapshot",
            "position",
            "account",
            "mm",
            "trading_cycle",
            "execution_control",
            "bot_status",
        }:
            continue
        if category not in {
            "READER_NOT_INJECTED",
            "READER_UNAVAILABLE",
            "READER_REJECTED",
            "READER_FAILED",
        }:
            continue
        projected.append(
            {
                "source": source,
                "category": category,
                "availability": "UNAVAILABLE",
                "observedAt": None,
                "freshness": "UNKNOWN",
            }
        )
    return projected


def build_operator_context_view(
    context: CanonicalContext,
    *,
    reader_failures: tuple[Any, ...] | list[Any] = (),
    max_bytes: int = DEFAULT_VIEW_MAX_BYTES,
    max_string: int = DEFAULT_MAX_STRING,
    max_list: int = DEFAULT_MAX_LIST,
) -> dict[str, object]:
    """Project runtime facts for an operator-facing consumer.

    Calling this function does not establish that the caller is authenticated.
    Credentials, raw exceptions, and absolute filesystem paths are excluded.
    """

    if not isinstance(context, CanonicalContext):
        raise TypeError("CanonicalContext required")
    payload = context_to_dict(context)
    sections = {
        name: _section_view(payload.get(name), allowed)
        for name, allowed in _SECTION_FIELDS.items()
    }
    body = _envelope(
        OPERATOR_CONTEXT,
        {
            "generatedAt": payload.get("generatedAt"),
            "safety": _safety(payload),
            "freshness": _freshness(payload),
            "source": _source_operator(payload),
            "project": _project_operator(payload),
            "provenance": _provenance(payload),
            "readerFailures": _failure_view(reader_failures),
            "sections": sections,
        },
    )
    return _finish(body, max_bytes=max_bytes, max_string=max_string, max_list=max_list)


def view_to_json(view: Mapping[str, Any]) -> str:
    """Serialize a view deterministically. This does not publish it."""

    return json.dumps(
        view,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    )


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return _stamp(value)
    raise TypeError("view value is not JSON serializable")


def view_to_markdown(view: Mapping[str, Any]) -> str:
    """Render the same view leaves that ``view_to_json`` emits."""

    lines = ["# TradingAI Context View", ""]
    lines.extend(_markdown_lines(dict(view), prefix=""))
    return "\n".join(lines) + "\n"


def _markdown_scalar(value: Any) -> str:
    if value is None:
        return "`null`"
    if isinstance(value, bool):
        return "`true`" if value else "`false`"
    if isinstance(value, (int, float)):
        return f"`{value}`"
    text = str(value).replace("\n", " ").replace("|", "\\|")
    return text


def _markdown_lines(value: Any, *, prefix: str) -> list[str]:
    lines: list[str] = []
    if isinstance(value, Mapping):
        for key in sorted(value):
            path = f"{prefix}.{key}" if prefix else str(key)
            child = value[key]
            if isinstance(child, (Mapping, list)):
                lines.append(f"- {path}")
                lines.extend(_markdown_lines(child, prefix=path))
            else:
                lines.append(f"- {path}: {_markdown_scalar(child)}")
        return lines
    if isinstance(value, list):
        for index, child in enumerate(value):
            path = f"{prefix}[{index}]"
            if isinstance(child, (Mapping, list)):
                lines.append(f"- {path}")
                lines.extend(_markdown_lines(child, prefix=path))
            else:
                lines.append(f"- {path}: {_markdown_scalar(child)}")
        return lines
    lines.append(f"- {prefix}: {_markdown_scalar(value)}")
    return lines
