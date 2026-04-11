# Bot/control/state_reconciler.py

import logging
from typing import List, Dict, Any


class StateReconciler:

    def __init__(self, state_manager, exchange_client, trade_core=None):
        self.state_manager = state_manager
        self.exchange = exchange_client
        self.trade_core = trade_core
        self.logger = logging.getLogger("StateReconciler")

    # =================================================
    # 起動時同期
    # =================================================
    def sync_on_startup(self):

        self.logger.info("[RECON] Starting state reconciliation...")

        # ① 取引所ポジション取得
        exchange_positions = self.exchange.get_open_positions()

        # ② ローカル状態取得
        local_positions = self.state_manager.get_open_positions()

        exchange_map = {p["position_id"]: p for p in exchange_positions}
        local_map = {p.id: p for p in local_positions}

        # =================================================
        # 🟡 取引所にあってローカルにない → 追加
        # =================================================
        for pid, ex_pos in exchange_map.items():

            if pid not in local_map:

                self.logger.warning(f"[RECON] Missing local position added: {pid}")

                self.state_manager.add_position(ex_pos)

        # =================================================
        # 🔴 ローカルにあって取引所にない → 削除
        # =================================================
        for pid in list(local_map.keys()):

            if pid not in exchange_map:

                self.logger.warning(f"[RECON] Orphan local position removed: {pid}")

                self.state_manager.remove_position(pid)

        self.logger.info("[RECON] State reconciliation completed")