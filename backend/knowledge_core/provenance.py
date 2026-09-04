"""Knowledge Provenance: where each Knowledge Core record's truth came from.

D-1 deals primarily with ``CANONICAL_SPECIFICATION`` and
``CURRENT_SOURCE_RUNTIME``.  There is deliberately no autonomous promotion to
``VALIDATED_KNOWLEDGE`` yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .authority import SourceCategory, TruthLevel


@dataclass(frozen=True)
class ProvenanceRecord:
    """Provenance for a single Knowledge Core record.

    ``source_reference`` is an explicit, stable reference such as a module
    path (``backend/bot_manager/bot_manager.py:BOT_manager``), a symbol, or a
    canonical document path.  Unknown aspects remain ``None`` / empty; nothing
    is guessed.
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

    def summarize(self) -> str:
        return self.source_reference
