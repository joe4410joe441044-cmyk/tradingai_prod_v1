import streamlit as st
from components.balance_card import show_balance
from components.position_table import show_positions
from components.trade_history import show_trade_history
from components.bot_controls import show_bot_controls
from services.websocket_client import start_ws_client

def main():
    st.header("Dashboard")

    # 残高カード
    show_balance()

    # 保有ポジション
    show_positions()

    # 過去取引履歴
    show_trade_history()

    # Bot制御ボタン
    show_bot_controls()

    # WebSocketでBot接続（非同期で残高/ポジションを更新）
    if "ws_started" not in st.session_state:
        start_ws_client()
        st.session_state.ws_started = True