"""TradingAI domains for the System Map.

Domains are derived from the actual repository architecture.  A domain is a
classification, not an authority.  Where the repository demonstrates a
different decomposition (for example MARKET_INTELLIGENCE exists only as a
UI/analytics layer over MARKET + TRADING_TRACE rather than a backend runtime)
that finding is recorded explicitly rather than invented.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Domain(str, Enum):
    MARKET = "MARKET"
    MARKET_INTELLIGENCE = "MARKET_INTELLIGENCE"
    TRADING_DECISION = "TRADING_DECISION"
    MONEY_MANAGEMENT = "MONEY_MANAGEMENT"
    GOVERNANCE = "GOVERNANCE"
    EMERGENCY = "EMERGENCY"
    EXECUTION = "EXECUTION"
    BOT = "BOT"
    LOOP = "LOOP"
    AUTO_TRADE = "AUTO_TRADE"
    POSITION = "POSITION"
    ORDERS = "ORDERS"
    RUNTIME_HEALTH = "RUNTIME_HEALTH"
    TRADING_TRACE = "TRADING_TRACE"
    AI_ADVISOR = "AI_ADVISOR"
    SUPERVISOR = "SUPERVISOR"


@dataclass(frozen=True)
class DomainRecord:
    domain: Domain
    display_name: str
    purpose: str
    notes: str = ""


DOMAIN_RECORDS = (
    DomainRecord(Domain.MARKET, "Market", "Market data feed and universe; supplies price/book state. Data authority only.", "No execution authority. Data quality varies."),
    DomainRecord(Domain.MARKET_INTELLIGENCE, "Market Intelligence",
                 "Read-only replay / decision-railway presentation layer. Consumes MARKET + TRADING_TRACE.",
                 "Finding: no backend.knowledge_core-affiliated runtime behind this domain; it is a UI/analytics layer."),
    DomainRecord(Domain.TRADING_DECISION, "Trading Decision",
                 "Strategy produces a direction / hold / suppress decision from features. It does not execute.", "decision authority only; execution is separate."),
    DomainRecord(Domain.MONEY_MANAGEMENT, "Money Management",
                 "Risk state, capital eligibility and entry gating; can approve, size-reduce, block.", "Holds MM authority; may block execution entry."),
    DomainRecord(Domain.GOVERNANCE, "Governance",
                 "Operator-controlled execution master switch, mode and risk profile.", "Holds governance authority."),
    DomainRecord(Domain.EMERGENCY, "Emergency",
                 "Emergency-stop latch and transition state machine held by governance runtime.", "Holds emergency authority."),
    DomainRecord(Domain.EXECUTION, "Execution",
                 "Translates an allowed decision into a simulated or real order attempt.", "Holds execution authority (only when gated)."),
    DomainRecord(Domain.BOT, "Bot",
                 "Bot manager: lifecycle, status aggregation and the runtime envelope.", "Holds runtime authority for lifecycle."),
    DomainRecord(Domain.LOOP, "Loop",
                 "Periodic decision loop start/stop and running state.", "Holds loop authority."),
    DomainRecord(Domain.AUTO_TRADE, "Auto Trade",
                 "Auto Market Selection: candidate scan, ranking, safe switch, live readiness.", "Constrained runtime authority; never bypasses gates."),
    DomainRecord(Domain.POSITION, "Position",
                 "Position sizing / risk and open-position state.", "Holds position sizing authority."),
    DomainRecord(Domain.ORDERS, "Orders",
                 "Concrete order entries / markers and live order state.", "Holds order authority only when permitted."),
    DomainRecord(Domain.RUNTIME_HEALTH, "Runtime Health",
                 "Read-only health / blocking-stage snapshot of the runtime pipeline.", "Read-only descriptor."),
    DomainRecord(Domain.TRADING_TRACE, "Trading Trace",
                 "Decision-scoped E2E trace recording; diagnostic only.", "Read-only diagnostic recorder. Never affects trading."),
    DomainRecord(Domain.AI_ADVISOR, "AI Advisor",
                 "Research / analysis partner. Read-only; no execution or governance override.", "READ ONLY. Does not trade."),
    DomainRecord(Domain.SUPERVISOR, "Supervisor",
                 "Oversight layer (Master + MM). Initially SHADOW; explains, never controls.", "SHADOW / READ-ONLY."),
)
