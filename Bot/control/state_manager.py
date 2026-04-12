# Bot/control/state_manager.py

from Bot.control.bot_state import BotState


class StateManager:
    def __init__(self, exchange, state: BotState):
        self.exchange = exchange
        self.state = state

    def sync_on_startup(self):
        """
        起動時チェック（監視専用）
        """
        print("[StateManager] Sync start...")

        try:
            exchange_positions = self.exchange.get_open_positions()
        except Exception as e:
            print("[ERROR] exchange.get_open_positions failed:", e)
            exchange_positions = []

        # ログ用（状態修正はしない）
        self._log_exchange_state(exchange_positions)

        print("[StateManager] Sync completed")

    def _log_exchange_state(self, exchange_positions):
        """
        状態不整合の検出のみ
        """

        if not exchange_positions:
            print("[STATE] No open positions on exchange")
            return

        for pos in exchange_positions:
            pos_id = pos.get("id")
            symbol = pos.get("symbol")

            print(f"[STATE] OPEN POSITION: {pos_id} {symbol}")

    def _convert(self, position):
        """
        将来用（未使用だが保持）
        """
        return {
            "position_id": position.get("id"),
            "symbol": position.get("symbol"),
            "side": position.get("side"),
            "entry_price": position.get("entryPrice"),
            "quantity": position.get("qty"),
            "status": "OPEN",
            "sl": position.get("sl"),
            "tp": position.get("tp"),
            "created_at": position.get("time"),
        }