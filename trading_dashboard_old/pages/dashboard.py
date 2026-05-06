import streamlit as st

from components.balance_card import show_balance
from components.position_table import show_positions
from components.trade_history import show_trade_history
from components.bot_controls import show_bot_controls

from services.websocket_client import start_ws_client


# =========================================
# PAGE CONFIG
# =========================================

st.set_page_config(
    page_title="TradingAI Dashboard",
    page_icon="🧠",
    layout="wide"
)


# =========================================
# CUSTOM CSS
# =========================================

st.markdown(
    """
    <style>

    /* =========================================
       GLOBAL
    ========================================= */

    .main {
        background-color: #0b0b0b;
        color: white;
    }

    .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
        max-width: 1600px;
    }

    /* =========================================
       TITLE
    ========================================= */

    .dashboard-title {
        font-size: 36px;
        font-weight: 700;
        margin-bottom: 4px;
        color: white;
    }

    .dashboard-subtitle {
        color: #888;
        margin-bottom: 24px;
    }

    /* =========================================
       CARD
    ========================================= */

    .custom-card {
        background: #161616;

        border: 1px solid #2a2a2a;

        border-radius: 14px;

        padding: 18px;

        margin-bottom: 20px;
    }

    /* =========================================
       DEBUG MODE
       二重構造確認用
       必要時だけコメント解除
    ========================================= */

    /*
    * {
        outline: 1px solid red;
    }
    */

    </style>
    """,
    unsafe_allow_html=True
)


# =========================================
# MAIN
# =========================================

def main():

    # =========================================
    # HEADER
    # =========================================

    st.markdown(
        """
        <div class="dashboard-title">
            🧠 TradingAI Dashboard
        </div>

        <div class="dashboard-subtitle">
            Real-time Monitoring / Position / Execution
        </div>
        """,
        unsafe_allow_html=True
    )

    # =========================================
    # WEBSOCKET START
    # =========================================

    if "ws_started" not in st.session_state:

        start_ws_client()

        st.session_state.ws_started = True

    # =========================================
    # TOP STATUS ROW
    # =========================================

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)

        st.metric(
            label="BOT STATUS",
            value="🟢 RUNNING"
        )

        st.markdown('</div>', unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)

        st.metric(
            label="SYMBOL",
            value="BTCUSDT"
        )

        st.markdown('</div>', unsafe_allow_html=True)

    with col3:
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)

        st.metric(
            label="MODE",
            value="LIVE"
        )

        st.markdown('</div>', unsafe_allow_html=True)

    # =========================================
    # MAIN GRID
    # =========================================

    left_col, right_col = st.columns([1.2, 1])

    # =========================================
    # LEFT SIDE
    # =========================================

    with left_col:

        # BALANCE
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)

        st.subheader("💰 Balance")

        show_balance()

        st.markdown('</div>', unsafe_allow_html=True)

        # POSITIONS
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)

        st.subheader("📊 Open Positions")

        show_positions()

        st.markdown('</div>', unsafe_allow_html=True)

    # =========================================
    # RIGHT SIDE
    # =========================================

    with right_col:

        # BOT CONTROL
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)

        st.subheader("🤖 Bot Controls")

        show_bot_controls()

        st.markdown('</div>', unsafe_allow_html=True)

        # TRADE HISTORY
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)

        st.subheader("🧾 Trade History")

        show_trade_history()

        st.markdown('</div>', unsafe_allow_html=True)


# =========================================
# START
# =========================================

if __name__ == "__main__":
    main()