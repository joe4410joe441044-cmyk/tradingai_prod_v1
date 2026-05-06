# components/bot_controls.py
import streamlit as st
from services.bot_api import BotAPI

# BotAPI インスタンスをセッションに保持
if "bot_api" not in st.session_state:
    st.session_state.bot_api = BotAPI()

bot_api = st.session_state.bot_api

def show_bot_controls():
    st.markdown("### Bot Controls")
    
    # Lot数選択（拡張用）
    lot = st.slider("Lot Size", min_value=1, max_value=100, value=1, step=1)
    st.session_state["lot"] = lot

    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("Start Bot"):
            status = bot_api.start_bot()
            st.success(f"Bot started. Status: {status}, Lot={lot}")
    
    with col2:
        if st.button("Stop Bot"):
            status = bot_api.stop_bot()
            st.warning(f"Bot stopped. Status: {status}")
    
    with col3:
        if st.button("Emergency Stop"):
            status = bot_api.emergency_stop()
            st.error(f"Emergency stop executed! Status: {status}")

    # 現在ステータス表示
    st.info(f"**Current Bot Status:** {bot_api.get_status()}")