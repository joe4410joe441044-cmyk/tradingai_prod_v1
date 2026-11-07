"""Deployment handoff document generation. Planning text only.

This module never deploys, never registers a scheduler, never imports a real
ChatGPT export, and never modifies a production path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .integration_models import (
    CanonicalReconciliation,
    DeploymentReadiness,
    HashMismatchClassification,
)


def render_handoff(
    *,
    task_id: str,
    readiness: DeploymentReadiness,
    reconciliation: CanonicalReconciliation | None,
    hash_classification: HashMismatchClassification | None,
    integration_summary: Mapping[str, Any] | None = None,
) -> str:
    summary = dict(integration_summary or {})
    lines: list[str] = [
        f"# BC-8 Deployment Handoff — {task_id}",
        "",
        "This document is a plan only. No production change was performed.",
        "",
        "## Verdict",
        "",
        f"- DEPLOYMENT_READINESS: {readiness.verdict}",
    ]
    for blocker in readiness.blockers:
        lines.append(f"- BLOCKER: {blocker}")
    for note in readiness.notes:
        lines.append(f"- NOTE: {note}")

    lines.extend(
        [
            "",
            "## Production Integration Plan",
            "",
            "1. Obtain explicit approval for BC-9 production integration.",
            "2. Merge the BC branch into canonical main only after approval.",
            "3. Deploy only the additive `backend/knowledge_hub/` package; no existing runtime path is modified.",
            "4. Do not restart the backend as part of the code-only step.",
            "5. Verify the import boundary with a read-only smoke check before any scheduler work.",
            "",
            "## Required Code Changes",
            "",
            "- None beyond the additive Knowledge Hub package already on the BC branch.",
            "- Advisor, Supervisor, production routers, frontend, and BB schema remain unchanged.",
            "",
            "## Required Config Changes",
            "",
            "- Choose an explicit database path outside the repository or inside an operator-only directory.",
            "- Choose an explicit report root allowlist.",
            "- No secrets, credentials, or ChatGPT login material are stored in configuration.",
            "",
            "## Database Initialization Plan",
            "",
            "- Create the SQLite store explicitly with the Knowledge Store schema.",
            "- Run `PRAGMA integrity_check` and confirm `user_version=1`.",
            "- Do not create the store automatically on service startup.",
            "",
            "## Database Permission Plan",
            "",
            "- Owner: the service account only.",
            "- Mode: `0600` for the database file; parent directory `0700`.",
            "- Advisor/Supervisor reader access must use a read-only SQLite URI.",
            "",
            "## Operator Access Plan",
            "",
            "- Operator scope is required for ChatGPT history and development reports.",
            "- Public scope must never receive OPERATOR records.",
            "- Privilege escalation from PUBLIC must return ACCESS_DENIED.",
            "",
            "## Advisor/Supervisor Connection Plan",
            "",
            "- Connect through `backend/knowledge_hub/knowledge_access.py` only.",
            "- Keep `authority=NONE`, `trading_control=FORBIDDEN`, and untrusted fences.",
            "- Do not make knowledge text a system instruction or a command source.",
            "- A missing or corrupt store must degrade to KNOWLEDGE_NOT_AVAILABLE.",
            "",
            "## Scheduler Enablement Plan",
            "",
            "- Not approved in BC-8. No cron, systemd timer, or production scheduler was registered.",
            "- A future approval must bound runtime, resources, and source allowlists.",
            "",
            "## Rollback Plan",
            "",
            "- Remove the additive Knowledge Hub package and any database created under the approved path.",
            "- No existing runtime configuration is changed by the code-only deployment.",
            "- No production database migration is applied by this task.",
            "",
            "## Post-deploy Acceptance Plan",
            "",
            "- Run the isolated integration suite with synthetic data.",
            "- Confirm operator/public boundaries and provenance fields.",
            "- Confirm no advisor/supervisor command execution and no trading authority change.",
            "- Confirm production service state is unchanged unless a separate restart is approved.",
            "",
            "## Known Blockers",
            "",
        ]
    )
    if readiness.blockers:
        for blocker in readiness.blockers:
            lines.append(f"- {blocker}")
    else:
        lines.append("- None for the additive code integration.")

    if reconciliation is not None:
        lines.extend(
            [
                "",
                "## Canonical Reconciliation",
                "",
                f"- canonical_head: {reconciliation.canonical_head}",
                f"- worktree_head: {reconciliation.worktree_head}",
                f"- counts: {reconciliation.counts()}",
                f"- blocked: {len(reconciliation.blocked)}",
            ]
        )
    if hash_classification is not None:
        lines.extend(
            [
                "",
                "## Advisor Hash Mismatch",
                "",
                f"- overall: {hash_classification.overall}",
                f"- matched: {len(hash_classification.matched)}",
                f"- mismatched: {len(hash_classification.mismatched)}",
            ]
        )
        for entry in hash_classification.mismatched:
            lines.append(
                f"- {entry.source_id}: {entry.status} / {entry.classification}"
            )
    if summary:
        lines.extend(["", "## Isolated Integration Summary", ""])
        for key, value in sorted(summary.items()):
            lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def write_handoff(path: str | Path, text: str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target
