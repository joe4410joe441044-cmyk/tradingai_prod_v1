import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
import uuid  # ← 追加

def show_trade_history(history=None):
    st.markdown("### Trade History")

    if history is None:
        history = [
            {"Time": "2026-03-29 14:00", "Symbol": "BTCUSDT", "Side": "BUY", "Qty": 0.1, "Price": 66000, "P/L": 50},
            {"Time": "2026-03-29 14:05", "Symbol": "ETHUSDT", "Side": "SELL", "Qty": 1, "Price": 2200, "P/L": -10},
            {"Time": "2026-03-29 14:10", "Symbol": "ADAUSDT", "Side": "BUY", "Qty": 50, "Price": 0.35, "P/L": 5},
        ]

    df = pd.DataFrame(history)
    df['Time'] = pd.to_datetime(df['Time'])

    # 日付スライダー用
    min_date = df['Time'].dt.date.min()
    max_date = df['Time'].dt.date.max()
    if min_date == max_date:
        min_date -= timedelta(days=1)
        max_date += timedelta(days=1)

    # ユニーク key を生成して重複を防ぐ
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

    # 銘柄フィルター
    symbols = df['Symbol'].unique().tolist()
    multiselect_key = f"trade_history_multiselect_{uuid.uuid4()}"  # ← ユニーク key
    selected_symbols = st.multiselect(
        "Filter by Symbol",
        options=symbols,
        default=symbols,
        key=multiselect_key
    )
    df = df[df['Symbol'].isin(selected_symbols)]

    # 色分け関数
    def color_side(val):
        color = "#d0f0c0" if str(val).upper() == "BUY" else "#f0d0d0"
        return f"background-color: {color}; color: black;"

    def color_pl(val):
        color = "green" if val > 0 else "red" if val < 0 else "white"
        return f"background-color: {color}; color: black;"

    styled_df = df.style.map(color_side, subset=['Side']).map(color_pl, subset=['P/L'])
    st.dataframe(styled_df, height=400)

    # 取引統計
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