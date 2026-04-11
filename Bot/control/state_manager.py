# Bot/control/state_manager.py

from Bot.control.bot_state import BotState
from Bot.exchanges.base_exchange import BaseExchange

# 🔥 安全import（exchangesが未構成でも落ちないようにする）
try:
    from Bot.exchanges.base_exchange import BaseExchange
except Exception as e:
    print("[WARN] BaseExchange import failed:", e)
    BaseExchange = object  # ダミー（起動クラッシュ防止）


class StateManager:
    def __init__(self, exchange: BaseExchange, state: BotState):
        self.exchange = exchange
        self.state = state

    def sync_on_startup(self):
        """
        起動時に必ず呼ぶ
        exchangeとlocal stateを同期
        """
        print("[StateManager] Sync start...")

        # 🔥 exchangeが壊れてても落とさない
        try:
            exchange_positions = self.exchange.get_open_positions()
        except Exception as e:
            print("[ERROR] exchange.get_open_positions failed:", e)
            exchange_positions = []

        local_state = self.state.load()

        self._rebuild_state(exchange_positions, local_state)
        self._resolve_inconsistencies(exchange_positions, local_state)

        print("[StateManager] Sync completed")

    def _rebuild_state(self, exchange_positions, local_state):
        for pos in exchange_positions:
            if pos["id"] not in local_state:
                self.state.save(self._convert(pos))

    def _resolve_inconsistencies(self, exchange_positions, local_state):
        exchange_ids = [p["id"] for p in exchange_positions]

        for local_id in list(local_state.keys()):
            if local_id not in exchange_ids:
                self.state.delete(local_id)

    def _convert(self, position):
        return {
            "position_id": position["id"],
            "symbol": position["symbol"],
            "side": position["side"],
            "entry_price": position["entryPrice"],
            "quantity": position["qty"],
            "status": "OPEN",
            "sl": position.get("sl"),
            "tp": position.get("tp"),
            "created_at": position.get("time")
        }