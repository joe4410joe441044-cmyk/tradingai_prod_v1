# trading_dashboard/app.py
import streamlit as st
from components.position_table import show_positions
from components.trade_history import show_trade_history

# 🔥 追加（次で実装するAPI）
try:
    from services.bot_api import send_bot_command
except:
    # まだ未実装でも落ちないようにする
    def send_bot_command(cmd, data=None):
        print(f"[MOCK API] {cmd} -> {data}")

st.set_page_config(page_title="Trading Dashboard", layout="wide")

st.title("🚀 Trading Dashboard")

# -------------------------
# Trading Pair Selection（確定型）
# -------------------------
st.sidebar.markdown("### Trading Pair")

# セッション初期化
if "selected_symbol" not in st.session_state:
    st.session_state.selected_symbol = "BTCUSDT"

if "bot_status" not in st.session_state:
    st.session_state.bot_status = "Stopped"

# プルダウン（仮選択）
pair_list = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

temp_symbol = st.sidebar.selectbox(
    "Select Pair",
    pair_list,
    index=pair_list.index(st.session_state.selected_symbol)
)

# ✅ Apply（ここが本体）
if st.sidebar.button("Apply"):
    st.session_state.selected_symbol = temp_symbol
    st.sidebar.success(f"Applied: {temp_symbol}")

    # 🔥🔥🔥 ここでBotに送信
    send_bot_command("SET_SYMBOL", temp_symbol)

# 現在の有効シンボル
st.sidebar.write("Current Pair:", st.session_state.selected_symbol)

# -------------------------
# Bot Control（状態保持）
# -------------------------
st.sidebar.markdown("### Bot Control")

if st.sidebar.button("Start Bot"):
    st.session_state.bot_status = "Running"
    send_bot_command("START")

if st.sidebar.button("Stop Bot"):
    st.session_state.bot_status = "Stopped"
    send_bot_command("STOP")

if st.sidebar.button("EMERGENCY STOP"):
    st.session_state.bot_status = "EMERGENCY STOPPED"
    send_bot_command("EMERGENCY_STOP")

st.sidebar.markdown(f"**Bot Status:** {st.session_state.bot_status}")

# -------------------------
# Account Info（モック）
# -------------------------
st.sidebar.markdown("### Account Info")
st.sidebar.metric("Balance", "$10,000")
st.sidebar.metric("Unrealized P/L", "$120")

# -------------------------
# Main Dashboard Tabs
# -------------------------
tab1, tab2, tab3 = st.tabs(["Positions", "Trade History", "Bot Logs"])

with tab1:
    show_positions()

with tab2:
    show_trade_history()

with tab3:
    st.markdown("### Bot Logs")
    log_area = st.empty()

    logs = [
        "[INFO] Bot initialized",
        "[INFO] Connected to exchange",
        f"[INFO] Current Symbol: {st.session_state.selected_symbol}",
        f"[INFO] Bot Status: {st.session_state.bot_status}",
    ]

    for log in logs:
        log_area.text(log)