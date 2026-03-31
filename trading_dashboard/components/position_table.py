import streamlit as st
import pandas as pd
from services.bot_api import _bot_instance
import uuid

def show_positions(positions=None):
    st.markdown("### Current Positions")

    if positions is None:
        positions = _bot_instance.get_positions()

    df = pd.DataFrame(positions or [])

    if df.empty:
        st.info("No open positions")
        return

    # Symbolフィルター用ユニークkey
    unique_key = f"positions_filter_{uuid.uuid4()}"
    symbols = df['Symbol'].unique().tolist()
    selected_symbols = st.multiselect("Filter by Symbol", options=symbols, default=symbols, key=unique_key)
    df = df[df['Symbol'].isin(selected_symbols)]

    # 色付け関数
    def color_pl(val):
        color = "green" if val > 0 else "red" if val < 0 else "white"
        return f"background-color: {color}; color: black;"

    def color_side(val):
        color = "#d0f0c0" if str(val).upper() == "BUY" else "#f0d0d0"
        return f"background-color: {color}; color: black;"

    styled_df = df.style.map(color_pl, subset=['P/L']).map(color_side, subset=['Side'])
    st.dataframe(styled_df, height=300)

    total_pl = df['P/L'].sum() if 'P/L' in df.columns else 0
    if total_pl >= 0:
        st.success(f"Total P/L: {total_pl}")
    else:
        st.error(f"Total P/L: {total_pl}")

    st.caption("Columns: Symbol, Side (BUY/SELL), Qty, Entry price, P/L")