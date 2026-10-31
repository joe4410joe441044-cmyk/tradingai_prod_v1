"""Deterministic serializers for canonical Context Packs.

Only in-process rendering is implemented.  No HTTP endpoint, file write, or
external publish is performed in Phase 1.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import json
from typing import Any

from pydantic import BaseModel

from .schema import CanonicalContext


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return {
            name: _jsonable(getattr(value, name))
            for name in type(value).model_fields
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def context_to_dict(context: CanonicalContext) -> dict[str, Any]:
    """Return a plain, JSON-compatible dictionary."""

    if not isinstance(context, CanonicalContext):
        raise TypeError("CanonicalContext required")
    return _jsonable(context)


def to_canonical_json(context: CanonicalContext) -> str:
    """Serialize deterministically: sorted keys, compact separators, UTF-8."""

    return json.dumps(
        context_to_dict(context),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _render_value(value: Any) -> str:
    if value is None:
        return "`null`"
    if isinstance(value, bool):
        return "`true`" if value else "`false`"
    if isinstance(value, (int, float)):
        return f"`{value}`"
    text = str(value).replace("\n", " ").replace("|", "\\|")
    return text


def _render_observation(title: str, observation: Any) -> list[str]:
    meta = observation.meta
    lines = [
        f"## {title}",
        "",
        f"- source: {meta.source}",
        f"- availability: {meta.availability.value}",
        f"- freshness: {meta.freshness.value}",
        f"- observedAt: {meta.observedAt.isoformat().replace('+00:00', 'Z') if meta.observedAt else 'UNKNOWN'}",
    ]
    if meta.detail:
        lines.append(f"- detail: {meta.detail}")
    if observation.fields:
        lines.append("")
        lines.append("| field | state | value |")
        lines.append("| --- | --- | --- |")
        for item in observation.fields:
            lines.append(
                f"| {item.name} | {item.state.value} | {_render_value(item.value)} |"
            )
    lines.append("")
    return lines


def to_markdown(context: CanonicalContext) -> str:
    """Render a deterministic, read-only Markdown view of the Context Pack."""

    if not isinstance(context, CanonicalContext):
        raise TypeError("CanonicalContext required")
    source = context.source
    lines = [
        "# TradingAI Canonical AI Context",
        "",
        f"- schemaVersion: {context.schemaVersion}",
        f"- generatedAt: {context.generatedAt.isoformat().replace('+00:00', 'Z')}",
        f"- generator: {context.generator.name} {context.generator.version}",
        "",
        "## SOURCE TRUTH",
        "",
        f"- repository: {_render_value(source.repository)}",
        f"- branch: {_render_value(source.branch)}",
        f"- head: {_render_value(source.head)}",
        f"- origin/main: {_render_value(source.originMain)}",
        f"- ahead: {_render_value(source.ahead)}",
        f"- behind: {_render_value(source.behind)}",
        f"- dirty: {_render_value(source.dirty)}",
        f"- deployedCommit: {_render_value(source.deployedCommit)}",
        f"- deployedCommitState: {source.deployedCommitState.value}",
        "",
        f"- worktrees ({len(source.worktrees)}):",
    ]
    for worktree in source.worktrees:
        lines.append(
            f"  - {worktree.path} ({worktree.branch or 'detached'}) @ {worktree.head or 'UNKNOWN'}"
        )
    lines.append("")
    for name in (
        "runtime",
        "marketSelection",
        "executionControl",
        "market",
        "moneyManagement",
        "governance",
        "tradingCycle",
        "position",
        "orders",
        "smallAccount",
        "account",
        "emergency",
        "health",
    ):
        lines.extend(_render_observation(name, getattr(context, name)))
    lines.extend(
        [
            "## PROJECT TRUTH",
            "",
            f"- workstreams: {len(context.workstreams.items)}",
            f"- contracts: {len(context.contracts.items)}",
            f"- knownIssues: {len(context.knownIssues.items)}",
            f"- acceptedTests: {len(context.acceptedTests.items)}",
            "",
            "| workstream | status | verification | branch |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in context.workstreams.items:
        lines.append(
            f"| {item.workstreamId} | {item.status.value} | "
            f"{item.verification.value} | {item.branch or 'UNKNOWN'} |"
        )
    lines.extend(
        [
            "",
            "## SAFETY",
            "",
            f"- contextRead: {_render_value(context.safety.contextRead)}",
            f"- sourceWrite: {_render_value(context.safety.sourceWrite)}",
            f"- runtimeWrite: {_render_value(context.safety.runtimeWrite)}",
            f"- orderWrite: {_render_value(context.safety.orderWrite)}",
            f"- liveOrder: {_render_value(context.safety.liveOrder)}",
            f"- productionDeploy: {_render_value(context.safety.productionDeploy)}",
            f"- secretsIncluded: {_render_value(context.safety.secretsIncluded)}",
            "",
            "## FRESHNESS",
            "",
            f"- overall: {context.freshness.overall.value}",
            f"- availability: {context.freshness.availability.value}",
            f"- staleSections: {', '.join(context.freshness.staleSections) or 'none'}",
            f"- unknownSections: {', '.join(context.freshness.unknownSections) or 'none'}",
            f"- unavailableSections: {', '.join(context.freshness.unavailableSections) or 'none'}",
            "",
        ]
    )
    return "\n".join(lines)
