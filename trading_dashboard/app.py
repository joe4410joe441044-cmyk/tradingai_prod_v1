import sys
import os
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from components.position_table import show_positions
from components.trade_history import show_trade_history
from services.bot_api import BotAPI

sys.path.append(os.path.dirname(__file__))

st.set_page_config(page_title="Trading Dashboard", layout="wide")
st.title("🚀 Trading Dashboard")

# -------------------------
# 初期化
# -------------------------
EXCHANGES = ["Binance", "Bybit", "Kucoin", "Bitget"]
DEFAULT_PAIRS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"]

if "bot_instances" not in st.session_state:
    st.session_state.bot_instances = {ex: BotAPI(symbol="BTCUSDT") for ex in EXCHANGES}

if "exchange" not in st.session_state:
    st.session_state.exchange = "Binance"

if "bot_connected" not in st.session_state:
    st.session_state.bot_connected = {ex: False for ex in EXCHANGES}

if "settings_applied" not in st.session_state:
    st.session_state.settings_applied = False

# -------------------------
# 左側 metric placeholder 初期化
# -------------------------
if "metric_values" not in st.session_state:
    st.session_state.metric_values = {"balance": 0.0, "pnl": 0.0, "price": 0.0, "delta": 0.0}

if "metric_placeholders" not in st.session_state:
    st.session_state.metric_placeholders = {
        "balance": st.sidebar.empty(),
        "pnl": st.sidebar.empty(),
        "price": st.sidebar.empty()
    }
    st.session_state.metric_placeholders["balance"].metric("Balance", "$0.00")
    st.session_state.metric_placeholders["pnl"].metric("Unrealized P/L", "$0.00")
    st.session_state.metric_placeholders["price"].metric("Current Price", "$0.00", delta="0.00")

# -------------------------
# 下部 sidebar 固定コンテナ
# -------------------------
if "sidebar_containers" not in st.session_state:
    st.session_state.sidebar_containers = {
        "exchange_pair": st.sidebar.container(),
        "settings": st.sidebar.container(),
        "bot_control": st.sidebar.container()
    }

# -------------------------
# 左側 UI更新（値のみ更新）
# -------------------------
def update_metrics():
    placeholders = st.session_state.get("metric_placeholders", {})
    if not placeholders:
        return

    bot_instance = st.session_state.bot_instances[st.session_state.exchange]
    state = bot_instance.get_all_state()
    price = state.get("price", 0.0)
    balance = state.get("balance", 0.0)
    positions = state.get("positions", [])

    # Unrealized P/L 計算
    unrealized_pnl = sum(
        (price - pos.get("Entry", 0.0)) * pos.get("Qty", 0.0) *
        (1 if pos.get("Side", "BUY") == "BUY" else -1)
        for pos in positions
    )

    last_price = st.session_state.metric_values.get("price", price)
    delta = price - last_price

    st.session_state.metric_values.update({
        "balance": balance,
        "pnl": unrealized_pnl,
        "price": price,
        "delta": delta
    })

    # 左側 metrics 更新
    placeholders["balance"].metric("Balance", f"${balance:,.2f}")
    placeholders["pnl"].metric("Unrealized P/L", f"${unrealized_pnl:,.2f}")
    delta_display = f"⬆ {delta:+.2f}" if delta > 0 else f"⬇ {delta:+.2f}" if delta < 0 else f"{delta:+.2f}"
    placeholders["price"].metric("Current Price", f"${price:,.2f}", delta=delta_display)

# -------------------------
# 右側 UI更新（初回のみ or 手動更新）
# -------------------------
positions_placeholder = st.empty()
history_placeholder = st.empty()
logs_placeholder = st.empty()

def update_ui_right():
    bot_instance = st.session_state.bot_instances[st.session_state.exchange]
    state = bot_instance.get_all_state()
    positions = state.get("positions", [])
    history = state.get("history", [])
    logs = state.get("logs", [])

    try:
        with positions_placeholder.container():
            show_positions(positions)
        with history_placeholder.container():
            show_trade_history(history)
        with logs_placeholder.container():
            st.markdown("### Bot Logs")
            for log in logs[-50:]:  # 最新50件のみ表示
                st.write(log)
    except Exception as e:
        st.error(f"Error rendering right UI: {e}")

# -------------------------
# 自動接続（WebSocket二重防止）
# -------------------------
def auto_connect():
    ex = st.session_state.exchange
    bot = st.session_state.bot_instances[ex]
    if not st.session_state.bot_connected.get(ex, False):
        if bot.get_status() != "running":
            bot.start_bot()
        if not getattr(bot, "ws_running", False):
            bot.start_ws()
        st.session_state.bot_connected[ex] = True
        logs_placeholder.write(f"{ex} Bot connected to {bot.symbol}")

auto_connect()

# -------------------------
# Sidebar: 固定描画
# -------------------------
with st.session_state.sidebar_containers["exchange_pair"]:
    st.markdown("### Exchange Selection")
    safe_index = EXCHANGES.index(st.session_state.exchange) if st.session_state.exchange in EXCHANGES else 0
    exchange_input = st.selectbox("Select Exchange", EXCHANGES, index=safe_index)
    if exchange_input != st.session_state.exchange:
        st.session_state.exchange = exchange_input
        auto_connect()
        update_metrics()

    st.markdown("### Trading Pair")
    bot_instance = st.session_state.bot_instances[st.session_state.exchange]
    safe_index_pair = DEFAULT_PAIRS.index(bot_instance.symbol) if bot_instance.symbol in DEFAULT_PAIRS else 0
    symbol_input = st.selectbox("Pair", DEFAULT_PAIRS, index=safe_index_pair)
    if symbol_input != bot_instance.symbol:
        bot_instance.set_symbol(symbol_input)
        if not getattr(bot_instance, "ws_running", False):
            bot_instance.start_ws()
    st.markdown(f"Current Pair: {bot_instance.symbol}")

with st.session_state.sidebar_containers["settings"]:
    st.markdown("### Lot / Risk / SL / Strategy")
    settings_config = {
        "Lot Size": {"attr": "lot", "type": "number", "step": 0.01},
        "Risk %": {"attr": "risk_percent", "type": "number", "step": 0.1},
        "SL Width (pips)": {"attr": "sl_pips", "type": "number", "step": 1},
        "Strategy": {"attr": "strategy", "type": "selectbox", "options": ["FVG", "RSI"]},
    }
    settings_values = {}
    for key, cfg in settings_config.items():
        if cfg["type"] == "number":
            settings_values[key] = st.number_input(
                key, value=getattr(bot_instance, cfg["attr"]), step=cfg["step"], disabled=True
            )
        elif cfg["type"] == "selectbox":
            options = cfg["options"]
            safe_idx = options.index(getattr(bot_instance, cfg["attr"])) if getattr(bot_instance, cfg["attr"]) in options else 0
            settings_values[key] = st.selectbox(key, options, index=safe_idx, disabled=True)

# -------------------------
# Bot Control 固定描画
# -------------------------
with st.session_state.sidebar_containers["bot_control"]:
    if st.session_state.settings_applied:
        st.markdown("### Bot Control")
        col1, col2, col3 = st.columns(3)
        if col1.button("Start"):
            bot_instance.start_bot()
            if not getattr(bot_instance, "ws_running", False):
                bot_instance.start_ws()
            update_metrics()
        if col2.button("Stop"):
            bot_instance.stop_bot()
            update_metrics()
        if col3.button("Emergency Stop"):
            bot_instance.emergency_stop()
            update_metrics()

# -------------------------
# Apply Settings
# -------------------------
if st.sidebar.button("Apply Settings"):
    bot_instance.set_symbol(symbol_input)
    for key, cfg in settings_config.items():
        setattr(bot_instance, cfg["attr"], settings_values[key])
    st.session_state.settings_applied = True
    logs_placeholder.write(f"{st.session_state.exchange} settings applied")
    if not getattr(bot_instance, "ws_running", False):
        bot_instance.start_ws()
    update_metrics()
    update_ui_right()

# -------------------------
# 左側自動更新（st_autorefresh使用：軽量処理のみ）
# -------------------------
st_autorefresh(interval=2000, key="metrics_refresh")  # 2秒間隔で軽量更新
update_metrics()

# -------------------------
# 右側手動更新ボタン（右下）
# -------------------------
if st.button("Update Now"):
    update_metrics()
    update_ui_right()