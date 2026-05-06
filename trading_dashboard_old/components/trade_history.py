import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
from services.bot_api import _bot_instance
import uuid

def show_trade_history(history=None):
    st.markdown("### Trade History")

    if history is None:
        history = _bot_instance.get_trade_history()

    if not history:
        st.info("No trade history")
        return

    df = pd.DataFrame(history)
    df['Time'] = pd.to_datetime(df['OpenTime'])

    # 日付スライダー
    min_date = df['Time'].dt.date.min()
    max_date = df['Time'].dt.date.max()
    if min_date == max_date:
        min_date -= timedelta(days=1)
        max_date += timedelta(days=1)

    slider_key = f"trade_history_slider_{uuid.uuid4()}"
    start_date, end_date = st.slider(
        "Select Time Range",
        min_value=min_date,
        max_value=max_date,
        value=(min_date, max_date),
        format="YYYY-MM-DD",
        key=slider_key
    )

    start_datetime = datetime.combine(start_date, time.min)
    end_datetime = datetime.combine(end_date, time.max)
    df = df[(df['Time'] >= start_datetime) & (df['Time'] <= end_datetime)]

    # Symbolフィルター
    symbols = df['Symbol'].unique().tolist()
    multiselect_key = f"trade_history_multiselect_{uuid.uuid4()}"
    selected_symbols = st.multiselect("Filter by Symbol", options=symbols, default=symbols, key=multiselect_key)
    df = df[df['Symbol'].isin(selected_symbols)]

    # 色付け関数
    def color_side(val):
        color = "#d0f0c0" if str(val).upper() == "BUY" else "#f0d0d0"
        return f"background-color: {color}; color: black;"

    def color_pl(val):
        color = "green" if val > 0 else "red" if val < 0 else "white"
        return f"background-color: {color}; color: black;"

    styled_df = df.style.map(color_side, subset=['Side']).map(color_pl, subset=['P/L'])
    st.dataframe(styled_df, height=400)

    # 統計表示
    total_trades = len(df)
    total_qty = df['Qty'].sum() if 'Qty' in df.columns else 0
    total_pl = df['P/L'].sum() if 'P/L' in df.columns else 0
    buy_count = (df['Side'].str.upper() == 'BUY').sum()
    sell_count = (df['Side'].str.upper() == 'SELL').sum()

    st.markdown("#### Trade Statistics")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Trades", total_trades)
    col2.metric("Total Quantity", total_qty)
    col3.metric("Cumulative P/L", total_pl)
    st.write(f"BUY Trades: {buy_count}, SELL Trades: {sell_count}")
    st.caption("Columns: Time, Symbol, Side, Qty, Price, P/L")