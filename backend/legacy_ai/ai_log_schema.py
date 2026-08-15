"""Archived Legacy AI log DTO."""

from dataclasses import dataclass

@dataclass
class AILog:
    timestamp: float
    symbol: str
    ai_score: float
    risk_score: float
    entry_allowed: bool
    position_id: str
    price: float
    reason: str
