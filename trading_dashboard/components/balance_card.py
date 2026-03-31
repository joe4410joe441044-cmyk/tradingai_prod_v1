import streamlit as st

def show_balance(balance: float = 10000.0, pnl: float = 123.45):
    st.metric(label="Account Balance", value=f"${balance:,.2f}", delta=f"${pnl:,.2f}")