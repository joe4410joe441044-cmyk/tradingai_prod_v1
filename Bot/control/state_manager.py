# Bot/control/state_manager.py

from Bot.control.bot_state import BotState


class StateManager:
    def __init__(self, exchange, state: BotState):
        self.exchange = exchange
        self.state = state

    def sync_on_startup(self):
        """
        起動時に必ず呼ぶ
        exchangeとlocal stateを同期
        """
        print("[StateManager] Sync start...")

        # 🔥 exchange安全取得
        try:
            exchange_positions = self.exchange.get_open_positions()
        except Exception as e:
            print("[ERROR] exchange.get_open_positions failed:", e)
            exchange_positions = []

        # 🔥 stateはdictとして扱う（save()ベース）
        local_state = self.state.save()
        if local_state is None:
            local_state = {}

        self._rebuild_state(exchange_positions, local_state)
        self._resolve_inconsistencies(exchange_positions, local_state)

        print("[StateManager] Sync completed")

    def _rebuild_state(self, exchange_positions, local_state):
        """
        exchangeにあるがlocalにないものを補完
        """
        for pos in exchange_positions:
            pos_id = pos.get("id")

            if not pos_id:
                continue

            if pos_id not in local_state:
                # stateへ反映（BotStateはdict管理ではないのでログ用途）
                print(f"[SYNC] missing local position -> {pos_id}")

    def _resolve_inconsistencies(self, exchange_positions, local_state):
        """
        localとexchangeの不整合チェック（ログのみ）
        """
        exchange_ids = {p.get("id") for p in exchange_positions if p.get("id")}

        for local_id in list(local_state.keys()):
            if local_id not in exchange_ids:
                print(f"[SYNC WARNING] local-only position detected: {local_id}")

    def _convert(self, position):
        """
        変換ユーティリティ（将来用）
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