"""Knowledge Provenance: where each Knowledge Core record's truth came from.

D-1 deals primarily with ``CANONICAL_SPECIFICATION`` and
``CURRENT_SOURCE_RUNTIME``.  There is deliberately no autonomous promotion to
``VALIDATED_KNOWLEDGE`` yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .authority import SourceCategory, TruthLevel


@dataclass(frozen=True)
class ProvenanceRecord:
    """Provenance for a single Knowledge Core record.

    ``source_reference`` is an explicit, stable reference such as a module
    path (``backend/bot_manager/bot_manager.py:BOT_manager``), a symbol, or a
    canonical document path.  Unknown aspects remain ``None`` / empty; nothing
    is guessed.

    The D-7 fields below are additive and optional.  They let an existing
    provenanced item carry drift-relevant metadata (subsystem/type/identifier,
    observed/loaded/source timestamps, freshness, confidence, warnings) without
    splitting provenance into a second, parallel system.  They default to the
    safest value (``None`` / empty / ``False``), so every existing construction
    is unchanged.
    """

    truth_level: TruthLevel
    source_category: SourceCategory
    source_reference: str
    source_path: Optional[str] = None
    symbol: Optional[str] = None
    version: Optional[str] = None
    content_hash: Optional[str] = None
    verified: bool = False
    notes: str = ""
    # D-7 provenance view fields (optional, non-authoritative, additive).
    source_subsystem: Optional[str] = None
    source_type: Optional[str] = None
    source_identifier: Optional[str] = None
    observed_at: Optional[datetime] = None
    source_timestamp: Optional[datetime] = None
    loaded_at: Optional[datetime] = None
    freshness: Optional[str] = None
    confidence: Optional[float] = None
    warnings: tuple[str, ...] = ()

    def summarize(self) -> str:
        return self.source_reference
