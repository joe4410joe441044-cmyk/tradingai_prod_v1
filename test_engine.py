# test_engine.py

import time
import sys
import os

# 🔴 ルートパス追加（確実にimport通す）
sys.path.append("C:/trading/tradingai_prod_v1")

# 🔴 修正済みimport
from Bot.engine.execution_engine import ExecutionEngine


# =========================
# ダミーPortfolio
# =========================
class DummyPortfolio:
    def __init__(self):
        self.equity = 1000

    def get_equity(self):
        return self.equity

    def add(self, pos):
        pass

    def remove(self, pid, pnl):
        self.equity += pnl

    def update_unrealized_pnl(self, pnl):
        pass


# =========================
# テスト開始
# =========================
def run_test():

    print("\n===== TEST START =====\n")

    portfolio = DummyPortfolio()

    engine = ExecutionEngine(
        portfolio=portfolio
    )

    engine.set_config({
        "balance": 1000,
        "riskPercent": 1,
        "leverage": 1,
        "stopLossPercent": 1,
        "takeProfitPercent": 1
    })

    engine.start()

    # =========================
    # ① エントリー確認
    # =========================
    print("\n--- ENTRY TEST ---")
    engine.on_price(100)

    print("positions:", engine.get_result()["positions"])

    # =========================
    # ② 利確テスト（勝ち）
    # =========================
    print("\n--- TAKE PROFIT TEST ---")

    engine.on_price(102)  # TP

    result = engine.get_result()

    print("balance:", result["balance"])
    print("realized_pnl:", result["realized_pnl"])

    # =========================
    # ③ 連敗テスト
    # =========================
    print("\n--- LOSS STREAK TEST ---")

    for i in range(5):
        print(f"\nLOSS ROUND {i+1}")

        engine.on_price(100)
        engine.on_price(98)

        res = engine.get_result()

        print("balance:", res["balance"])
        print("kill_switch:", engine.risk.kill_switch.active)

        if not engine.active:
            print("⛔ BOT STOPPED (EXPECTED)")
            break

    # =========================
    # ④ DDテスト
    # =========================
    print("\n--- DRAWDOWN TEST ---")

    # 🔴 念のため再起動（kill_switch後の安全対策）
    engine = ExecutionEngine(portfolio=portfolio)
    engine.set_config({
        "balance": portfolio.get_equity(),
        "riskPercent": 5,
        "leverage": 1,
        "stopLossPercent": 2,
        "takeProfitPercent": 1
    })
    engine.start()

    for i in range(20):
        engine.on_price(100)
        engine.on_price(95)

        if engine.risk.kill_switch.active:
            print("⛔ DD KILL SWITCH TRIGGERED")
            break

    # =========================
    # ⑤ STOPテスト
    # =========================
    print("\n--- STOP TEST ---")

    engine.on_price(100)
    engine.stop()

    final = engine.get_result()

    print("\nFINAL RESULT")
    print("balance:", final["balance"])
    print("equity:", final["equity"])
    print("positions:", final["positions"])

    print("\n===== TEST END =====\n")


if __name__ == "__main__":
    run_test()