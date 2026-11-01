"""Static feasibility assessment for ChatGPT history synchronization.

This module is a report, not a transport. It performs no request and opens no
connection. An unverified item is never promoted to ``SUPPORTED``. The export
refresh workflow implemented by this package is a manual, user-authorized file
transfer. It is not evidence that real-time synchronization exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


RESEARCH_DATE = "2026-11-01"

SUPPORTED = "SUPPORTED"
SUPPORTED_WITH_USER_ACTION = "SUPPORTED_WITH_USER_ACTION"
NOT_SUPPORTED = "NOT_SUPPORTED"
UNKNOWN = "UNKNOWN"
REQUIRES_FUTURE_VERIFICATION = "REQUIRES_FUTURE_VERIFICATION"

NETWORK_AVAILABLE = "NETWORK_AVAILABLE"
NETWORK_NOT_AVAILABLE = "NETWORK_NOT_AVAILABLE"
NETWORK_AVAILABLE_OFFICIAL_DOCS_BLOCKED = "NETWORK_AVAILABLE_OFFICIAL_DOCS_BLOCKED"

_SOURCE_DOCUMENTATION: tuple[tuple[str, str], ...] = (
    ("https://help.openai.com/en/articles/7260999-how-do-i-export-my-chatgpt-history-and-data", "HTTP_403_BLOCKED"),
    ("https://help.openai.com/en/", "HTTP_403_BLOCKED"),
    ("https://platform.openai.com/docs/api-reference", "HTTP_301_REDIRECT_ONLY"),
)


@dataclass(frozen=True)
class FeasibilityAssessment:
    research_date: str
    network_verification_status: str
    official_export_support: str
    official_programmatic_sync: str
    realtime_sync_feasibility: str
    manual_refresh_feasibility: str
    user_authorized_connector_feasibility: str
    source_documentation: tuple[tuple[str, str], ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "research_date": self.research_date,
            "network_verification_status": self.network_verification_status,
            "official_export_support": self.official_export_support,
            "official_programmatic_sync": self.official_programmatic_sync,
            "realtime_sync_feasibility": self.realtime_sync_feasibility,
            "manual_refresh_feasibility": self.manual_refresh_feasibility,
            "user_authorized_connector_feasibility": self.user_authorized_connector_feasibility,
            "source_documentation": [
                {"url": url, "result": result} for url, result in self.source_documentation
            ],
            "notes": list(self.notes),
        }


def assess(
    *,
    network_status: str = NETWORK_AVAILABLE_OFFICIAL_DOCS_BLOCKED,
) -> FeasibilityAssessment:
    return FeasibilityAssessment(
        research_date=RESEARCH_DATE,
        network_verification_status=network_status,
        official_export_support=REQUIRES_FUTURE_VERIFICATION,
        official_programmatic_sync=UNKNOWN,
        realtime_sync_feasibility=UNKNOWN,
        manual_refresh_feasibility=SUPPORTED_WITH_USER_ACTION,
        user_authorized_connector_feasibility=UNKNOWN,
        source_documentation=_SOURCE_DOCUMENTATION,
        notes=(
            "The official help-center and platform documentation pages were not readable from this environment.",
            "The manual export refresh workflow is implemented and tested only with synthetic archives.",
            "The OpenAI API platform is not treated as evidence of ChatGPT consumer conversation-history access.",
            "No non-official endpoint, session cookie, browser profile, or scraping path was used.",
            "Real-time synchronization is not claimed; it stays unverified until official documentation is available.",
        ),
    )


def render_markdown(assessment: FeasibilityAssessment | None = None) -> str:
    result = assessment or assess()
    lines = [
        "# ChatGPT History Sync Feasibility",
        "",
        f"- RESEARCH_DATE: {result.research_date}",
        f"- NETWORK_VERIFICATION_STATUS: {result.network_verification_status}",
        f"- OFFICIAL_EXPORT_SUPPORT: {result.official_export_support}",
        f"- OFFICIAL_PROGRAMMATIC_SYNC: {result.official_programmatic_sync}",
        f"- REALTIME_SYNC_FEASIBILITY: {result.realtime_sync_feasibility}",
        f"- MANUAL_REFRESH_FEASIBILITY: {result.manual_refresh_feasibility}",
        f"- USER_AUTHORIZED_CONNECTOR_FEASIBILITY: {result.user_authorized_connector_feasibility}",
        "",
        "## Source documentation",
        "",
    ]
    for url, status in result.source_documentation:
        lines.append(f"- {url} -> {status}")
    lines.extend(["", "## Notes", ""])
    for note in result.notes:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"
