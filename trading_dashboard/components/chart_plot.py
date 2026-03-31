# trading_dashboard/components/chart_plot.py
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

def plot_trading_chart(df: pd.DataFrame, show_ma: bool = True, ma_period: int = 20):
    """
    df 必須カラム:
        - 'timestamp' : datetime
        - 'open', 'high', 'low', 'close'
        - 'position' : 'long', 'short', or None
        - 'pnl' : float (取引損益)
    """
    st.markdown("### Trading Chart")

    # 日付範囲スライダー
    df = df.sort_values('timestamp')
    min_date, max_date = df['timestamp'].min(), df['timestamp'].max()
    start_date, end_date = st.slider(
        "Select Date Range",
        min_value=min_date,
        max_value=max_date,
        value=(min_date, max_date),
        format="YYYY-MM-DD HH:mm"
    )
    df = df[(df['timestamp'] >= start_date) & (df['timestamp'] <= end_date)]

    fig = go.Figure()

    # ローソク足
    fig.add_trace(go.Candlestick(
        x=df['timestamp'],
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        name='Price'
    ))

    # 移動平均線
    if show_ma:
        df['ma'] = df['close'].rolling(ma_period).mean()
        fig.add_trace(go.Scatter(
            x=df['timestamp'],
            y=df['ma'],
            mode='lines',
            name=f'MA{ma_period}',
            line=dict(color='blue', width=1)
        ))

    # ポジションマーク
    for i, row in df.iterrows():
        if row['position'] == 'long':
            fig.add_trace(go.Scatter(
                x=[row['timestamp']],
                y=[row['close']],
                mode='markers',
                marker=dict(color='green', symbol='triangle-up', size=12),
                name='Long Entry'
            ))
        elif row['position'] == 'short':
            fig.add_trace(go.Scatter(
                x=[row['timestamp']],
                y=[row['close']],
                mode='markers',
                marker=dict(color='red', symbol='triangle-down', size=12),
                name='Short Entry'
            ))

    # PnLグラフ（サブプロット化）
    pnl_fig = go.Figure()
    pnl_fig.add_trace(go.Bar(
        x=df['timestamp'],
        y=df['pnl'],
        name='Trade PnL',
        marker_color=['green' if x >= 0 else 'red' for x in df['pnl']]
    ))
    pnl_fig.update_layout(
        title='PnL per Trade',
        xaxis_title='Time',
        yaxis_title='PnL',
        height=300
    )

    st.plotly_chart(fig, use_container_width=True)
    st.plotly_chart(pnl_fig, use_container_width=True)


# ===== Example usage =====
if __name__ == "__main__":
    # ダミーデータ生成
    dates = pd.date_range(start="2026-03-01", periods=50, freq='H')
    df = pd.DataFrame({
        'timestamp': dates,
        'open': np.random.rand(50)*100+1000,
        'high': np.random.rand(50)*100+1050,
        'low': np.random.rand(50)*100+950,
        'close': np.random.rand(50)*100+1000,
        'position': [None]*50,
        'pnl': np.random.randn(50)*50
    })
    df.loc[5, 'position'] = 'long'
    df.loc[20, 'position'] = 'short'

    st.set_page_config(page_title="Trading Chart", layout="wide")
    plot_trading_chart(df)