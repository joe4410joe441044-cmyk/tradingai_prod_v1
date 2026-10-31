"""Read-only runtime evidence from an already copied owner snapshot.

PAPER position data and a stored trading-cycle result stay on the operator
view. A runtime domain is projected only from a fragment the owner stored.
``publishedAt`` is not a producer time. This module does not compute a
replacement or call an exchange. The money-management domain is never
``CURRENT`` from ``freshnessPolicy`` or from ``producerObservedAt``.
Other domains keep their existing freshness labels.
"""

from __future__ import annotations

from typing import Any, Mapping

from backend.context.runtime_projection import parse_producer_time

_DOMAINS = (
    ("moneyManagement", "money_management"),
    ("executionAuthority", "execution_control"),
    ("liveAccount", "real_account"),
    ("supervisorRuntime", "supervisor"),
    ("marketSelection", "market_selection"),
    ("marketIntelligence", "market_intelligence"),
)
_META = {"producerObservedAt", "freshness", "freshnessPolicy", "orderEffect"}


def collect_runtime_evidence(document: Mapping[str, Any] | None) -> dict[str, Any]:
    """Project one copied owner document into bounded runtime evidence."""

    if not isinstance(document, Mapping) or document.get("schemaVersion") != (
        "tradingai-owner-snapshot/v1"
    ):
        return _evidence(_domains("OWNER_UNAVAILABLE"))
    unavailable = document.get("unavailable")
    blocked = set(unavailable) if isinstance(unavailable, list) else set()
    payload = document.get("payload")
    stored = payload if isinstance(payload, Mapping) else {}
    domains = {}
    for name, key in _DOMAINS:
        fragment = stored.get(key)
        if key in blocked or not isinstance(fragment, Mapping):
            reason = "NOT_PUBLISHED" if key in blocked else "NOT_IN_OWNER_SNAPSHOT"
            domains[name] = _domain(name, reason)
            continue
        domains[name] = _published(name, fragment)
    return _evidence(domains)


def _domains(reason: str) -> dict[str, dict[str, Any]]:
    return {name: _domain(name, reason) for name, _key in _DOMAINS}


def _published(name: str, fragment: Mapping[str, Any]) -> dict[str, Any]:
    status, freshness, timestamp = _judge(name, fragment)
    values = {
        key: value
        for key, value in fragment.items()
        if key not in _META
    }
    body = _domain(name, "OWNER_PUBLISHED")
    body["runtimeTimestamp"] = timestamp
    body["runtimeFreshness"] = freshness
    body["runtimeStatus"] = status
    body["runtimeValues"] = values or None
    if fragment.get("orderEffect") == "NONE":
        body["runtimeProvenance"]["orderEffect"] = "NONE"
    return body


def _judge(name: str, fragment: Mapping[str, Any]) -> tuple[str, str, str]:
    parsed = parse_producer_time(fragment.get("producerObservedAt"))
    if parsed is None:
        return "UNKNOWN", "UNKNOWN", "UNKNOWN"
    stamp = parsed.isoformat().replace("+00:00", "Z")
    label = fragment.get("freshness")
    if label == "STALE":
        return "STALE", "STALE", stamp
    if label == "HISTORICAL":
        return "HISTORICAL", "HISTORICAL", stamp
    if name == "moneyManagement":
        # A copied freshnessPolicy ages producerObservedAt. That clock is
        # not observation completion, so it cannot make this domain CURRENT
        # or age it into STALE. An explicit freshness label above is unchanged.
        return "UNKNOWN", "UNKNOWN", stamp
    return "UNKNOWN", "UNKNOWN", stamp


def _domain(name: str, reason: str) -> dict[str, Any]:
    return {
        "runtimeDomain": name,
        "runtimeSource": "bot_manager_publication",
        "runtimeOwner": "BotManager",
        "runtimeTimestamp": "UNKNOWN",
        "runtimeFreshness": "UNKNOWN",
        "runtimeProvenance": {
            "reader": "copied_owner_export",
            "reason": reason,
        },
        "runtimeStatus": "UNAVAILABLE",
        "runtimeValues": None,
    }


def _evidence(domains: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "classification": "READ_ONLY_RUNTIME_EVIDENCE",
        "boundaryStart": "BEGIN_UNTRUSTED_RUNTIME_EVIDENCE",
        "boundaryEnd": "END_UNTRUSTED_RUNTIME_EVIDENCE",
        "truthKind": "RUNTIME_TRUTH",
        "authority": "NONE",
        "tradingControl": "FORBIDDEN",
        "instructionBoundary": "DATA_ONLY",
        "productionRuntimeConnected": False,
        "separatedFrom": [
            "sourceEvidence",
            "projectEvidence",
            "decisionEvidence",
            "operatorView",
        ],
        "domains": domains,
    }
