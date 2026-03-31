import streamlit as st
import pandas as pd

def show_positions(positions=None):
    st.markdown("### Current Positions")

    # モックデータ
    if positions is None:
        positions = [
            {"Symbol": "BTCUSDT", "Side": "BUY", "Qty": 0.1, "Entry": 66000, "P/L": 50},
            {"Symbol": "ETHUSDT", "Side": "SELL", "Qty": 1, "Entry": 2200, "P/L": -10},
            {"Symbol": "ADAUSDT", "Side": "BUY", "Qty": 50, "Entry": 0.35, "P/L": 5},
        ]

    df = pd.DataFrame(positions or [])

    # Symbolカラムがない場合に備える
    if 'Symbol' not in df.columns:
        df['Symbol'] = []

    # 重複しないユニーク key を生成
    import uuid
    unique_key = f"positions_filter_{uuid.uuid4()}"

    symbols = df['Symbol'].unique().tolist()
    selected_symbols = st.multiselect(
        "Filter by Symbol",
        options=symbols,
        default=symbols,
        key=unique_key
    )
    df = df[df['Symbol'].isin(selected_symbols)]

    # 色付け関数
    def color_pl(val):
        color = "green" if val > 0 else "red" if val < 0 else "white"
        return f"background-color: {color}; color: black;"

    def color_side(val):
        color = "#d0f0c0" if str(val).upper() == "BUY" else "#f0d0d0"
        return f"background-color: {color}; color: black;"

    # pandas 1.5+ 用 map に修正
    styled_df = df.style.map(color_pl, subset=['P/L']).map(color_side, subset=['Side'])
    st.dataframe(styled_df, height=300)

    total_pl = df['P/L'].sum() if 'P/L' in df.columns else 0
    if total_pl >= 0:
        st.success(f"Total P/L: {total_pl}")
    else:
        st.error(f"Total P/L: {total_pl}")

    st.caption("Columns: Symbol, Side (BUY/SELL), Qty, Entry price, P/L")