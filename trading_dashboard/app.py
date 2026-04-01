import sys
import os
import streamlit as st
from streamlit_autorefresh import st_autorefresh
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
# 右側用 placeholder（左側は空）
# -------------------------
_, right_col = st.columns([1, 2])

if "metric_placeholders_right" not in st.session_state:
    st.session_state.metric_placeholders_right = {
        "balance": right_col.empty(),
        "pnl": right_col.empty(),
        "price": right_col.empty()
    }
    st.session_state.metric_placeholders_right["balance"].metric("Balance", "$0.00")
    st.session_state.metric_placeholders_right["pnl"].metric("Unrealized P/L", "$0.00")
    st.session_state.metric_placeholders_right["price"].metric("Current Price", "$0.00", delta="0.00")

# -------------------------
# metrics 更新
# -------------------------
def update_metrics():
    placeholders = st.session_state.metric_placeholders_right
    bot_instance = st.session_state.bot_instances[st.session_state.exchange]
    state = bot_instance.get_all_state()

    price = state.get("price", 0.0)
    balance = state.get("balance", 0.0)
    positions = state.get("positions", [])

    unrealized_pnl = sum(
        (price - pos.get("Entry", 0.0)) * pos.get("Qty", 0.0) *
        (1 if pos.get("Side", "BUY") == "BUY" else -1)
        for pos in positions
    ) if positions else 0.0

    last_price = st.session_state.get("last_price", price)
    delta = price - last_price
    st.session_state["last_price"] = price

    # カード風に更新
    placeholders["balance"].metric("Balance", f"${balance:,.2f}")
    placeholders["pnl"].metric("Unrealized P/L", f"${unrealized_pnl:,.2f}")
    delta_display = f"⬆ {delta:+.2f}" if delta > 0 else f"⬇ {delta:+.2f}" if delta < 0 else f"{delta:+.2f}"
    placeholders["price"].metric("Current Price", f"${price:,.2f}", delta=delta_display)

# -------------------------
# 自動接続
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

auto_connect()

# -------------------------
# 右側 UI：Exchange / Pair / Settings / Bot Control / Metrics
# -------------------------
with right_col:
    st.markdown("## Exchange / Pair Selection")
    safe_index = EXCHANGES.index(st.session_state.exchange) if st.session_state.exchange in EXCHANGES else 0
    exchange_input = st.selectbox("Select Exchange", EXCHANGES, index=safe_index)
    if exchange_input != st.session_state.exchange:
        st.session_state.exchange = exchange_input
        auto_connect()
        update_metrics()

    bot_instance = st.session_state.bot_instances[st.session_state.exchange]
    safe_index_pair = DEFAULT_PAIRS.index(bot_instance.symbol) if bot_instance.symbol in DEFAULT_PAIRS else 0
    symbol_input = st.selectbox("Pair", DEFAULT_PAIRS, index=safe_index_pair)
    if symbol_input != bot_instance.symbol:
        bot_instance.set_symbol(symbol_input)
        if not getattr(bot_instance, "ws_running", False):
            bot_instance.start_ws()
    st.markdown(f"Current Pair: **{bot_instance.symbol}**")

    st.markdown("## Lot / Risk / SL / Strategy")
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

    if st.button("Apply Settings"):
        bot_instance.set_symbol(symbol_input)
        for key, cfg in settings_config.items():
            setattr(bot_instance, cfg["attr"], settings_values[key])
        st.session_state.settings_applied = True
        update_metrics()

    st.markdown("## Bot Control")
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
# 自動更新（10秒間隔）
# -------------------------
st_autorefresh(interval=10000, key="metrics_refresh")
update_metrics()