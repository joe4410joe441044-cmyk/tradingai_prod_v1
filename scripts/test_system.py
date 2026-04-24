# -*- coding: utf-8 -*-

import time

from backend.cluster.cluster_monitor import ClusterMonitor
from backend.portfolio.portfolio_manager import PortfolioManager
from backend.protection.capital_protection_ai import CapitalProtectionAI
from backend.ai.trade_brain import TradeBrain
from backend.ai.lstm_model import LSTMModel
from backend.ai.llm_engine import LLMEngine


# =====================================================
# INIT COMPONENTS
# =====================================================
cluster = ClusterMonitor()
portfolio = PortfolioManager()
protection = CapitalProtectionAI()

lstm = LSTMModel()
llm = LLMEngine()
brain = TradeBrain(lstm, llm)


# =====================================================
# TEST 1: CLUSTER
# =====================================================
print("=== CLUSTER TEST ===")
cluster.update("vps_a", True)
cluster.update("vps_b", True)
cluster.update("execution", True)

print("HEALTH:", cluster.health())


# =====================================================
# TEST 2: AI DECISION
# =====================================================
print("\n=== AI BRAIN TEST ===")

market = {
    "features": [0.1, 0.2, 0.3, 0.5],
    "trend": "up",
    "volatility": 0.3
}

print("DECISION:", brain.decide(market))


# =====================================================
# TEST 3: PORTFOLIO
# =====================================================
print("\n=== PORTFOLIO TEST ===")

can_open = portfolio.can_open("BTCUSDT", 0.1)
print("CAN OPEN:", can_open)

portfolio.add({
    "id": "1",
    "symbol": "BTCUSDT",
    "qty": 0.1
})

print("SUMMARY:", portfolio.summary())


# =====================================================
# TEST 4: PROTECTION AI
# =====================================================
print("\n=== PROTECTION TEST ===")

for pnl in [-10, -20, -5, -1, -2]:
    protection.update(pnl)
    print("ALLOW:", protection.allow_trade(), "LOSS STREAK:", protection.loss_streak)


# =====================================================
# RESULT
# =====================================================
print("\n=== SYSTEM TEST COMPLETE ===")