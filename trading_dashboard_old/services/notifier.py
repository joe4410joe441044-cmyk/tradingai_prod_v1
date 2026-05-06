# trading_dashboard/services/notifier.py
import streamlit as st
from typing import Literal, List, Dict
from datetime import datetime

class Notifier:
    """
    多チャネル通知サービス
    - Streamlit, Telegram, Slack, Emailなど拡張可能
    - 通知履歴保持
    """

    def __init__(self):
        # 送信履歴
        if "notifier_history" not in st.session_state:
            st.session_state["notifier_history"] = []
        self.history: List[Dict] = st.session_state["notifier_history"]

    def notify(
        self,
        message: str,
        level: Literal["INFO", "SUCCESS", "WARNING", "ERROR"] = "INFO",
        title: str = None,
        streamlit_display: bool = True,
        telegram: bool = False,
        slack: bool = False,
        email: bool = False
    ):
        """
        message: 通知本文
        level: INFO / SUCCESS / WARNING / ERROR
        title: 任意タイトル
        streamlit_display: Streamlitに表示するか
        telegram/slack/email: 今後拡張用
        """
        timestamp = datetime.now()
        entry = {
            "timestamp": timestamp,
            "title": title or level,
            "message": message,
            "level": level
        }

        # 履歴に追加
        self.history.append(entry)

        # Streamlit通知表示
        if streamlit_display:
            if level == "INFO":
                st.info(f"[{timestamp:%H:%M:%S}] {title or ''} {message}")
            elif level == "SUCCESS":
                st.success(f"[{timestamp:%H:%M:%S}] {title or ''} {message}")
            elif level == "WARNING":
                st.warning(f"[{timestamp:%H:%M:%S}] {title or ''} {message}")
            elif level == "ERROR":
                st.error(f"[{timestamp:%H:%M:%S}] {title or ''} {message}")

        # 今後の拡張：Telegram / Slack / Email
        if telegram:
            self._send_telegram(message)
        if slack:
            self._send_slack(message)
        if email:
            self._send_email(message)

        return entry

    # ===== 拡張用モック関数 =====
    def _send_telegram(self, message: str):
        print(f"[Notifier] Telegram: {message}")

    def _send_slack(self, message: str):
        print(f"[Notifier] Slack: {message}")

    def _send_email(self, message: str):
        print(f"[Notifier] Email: {message}")

    # ===== 履歴取得 =====
    def get_history(self, last_n: int = 10):
        """直近 last_n 件を返す"""
        return self.history[-last_n:]

    def show_history(self):
        """Streamlit で履歴表示"""
        st.markdown("### Notification History")
        for entry in reversed(self.history):
            ts = entry["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            lvl = entry["level"]
            msg = entry["message"]
            title = entry["title"]
            st.write(f"[{ts}] {lvl} {title}: {msg}")