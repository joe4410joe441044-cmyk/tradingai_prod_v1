# trading_dashboard/services/websocket_client.py
import threading
import time
import streamlit as st
from typing import Optional
from datetime import datetime

# 修正版：相対インポート
from .notifier import Notifier
from .bot_api import BotAPI

class WSClient:
    """
    強化版バックグラウンドWebSocketクライアント（モック）
    - BotAPI 状態・ポジション・PnL を定期取得
    - Streamlit UI と連携
    - Notifier と連携
    """

    def __init__(self, bot: BotAPI, notifier: Optional[Notifier] = None, update_interval: float = 2.0):
        self.bot = bot
        self.notifier = notifier or Notifier()
        self.update_interval = update_interval
        self._stop_flag = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            print("[WSClient] Already running")
            return
        self._stop_flag = False
        self._thread = threading.Thread(target=self._ws_loop, daemon=True)
        self._thread.start()
        print("[WSClient] Background WS client started")

    def stop(self):
        self._stop_flag = True
        print("[WSClient] Background WS client stopping...")

    def _ws_loop(self):
        try:
            last_status = None
            while not self._stop_flag:
                # ===== Bot状態取得 =====
                status = self.bot.get_status()
                positions = self.bot.get_positions()
                trade_history = self.bot.get_trade_history()

                # ===== 状態変化通知 =====
                if status != last_status:
                    self.notifier.notify(
                        f"Bot status changed to {status}",
                        level="WARNING" if status == "emergency" else "INFO",
                        streamlit_display=True
                    )
                    last_status = status

                # ===== PnLアラート（例: 累積P/Lが±100を超えたら通知） =====
                total_pnl = sum([pos.get("P/L",0) for pos in trade_history])
                if abs(total_pnl) >= 100:
                    self.notifier.notify(
                        f"Total P/L alert! {total_pnl:.2f}",
                        level="ERROR" if total_pnl < 0 else "SUCCESS",
                        streamlit_display=True
                    )

                # ===== Streamlitセッション反映 =====
                st.session_state["positions"] = positions
                st.session_state["trade_history"] = trade_history
                st.session_state["bot_status"] = status
                st.session_state["last_update"] = datetime.now().strftime("%H:%M:%S")

                time.sleep(self.update_interval)
        except Exception as e:
            self.notifier.notify(f"WSClient encountered error: {e}", level="ERROR")

# websocket_client.py の最後に追加
# =================================
_bot_instance: Optional[WSClient] = None

def start_ws_client(bot_api: BotAPI, notifier: Optional[Notifier] = None, update_interval: float = 2.0):
    """
    グローバル WSClient を開始（Streamlit から呼ぶ用）
    """
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = WSClient(bot=bot_api, notifier=notifier, update_interval=update_interval)
        _bot_instance.start()
    return _bot_instance

