# trading_dashboard/utils/ui_logger.py
import streamlit as st
from datetime import datetime
from typing import Literal, List, Dict

def log_ui(
    message: str,
    level: Literal["INFO", "SUCCESS", "WARNING", "ERROR"] = "INFO",
    show_in_ui: bool = True,
    keep_history: bool = True
) -> Dict:
    """
    UIログ関数（Streamlit対応・ログ履歴付き）
    
    Args:
        message: 表示メッセージ
        level: ログレベル (INFO, SUCCESS, WARNING, ERROR)
        show_in_ui: Streamlit に表示するか
        keep_history: 履歴に残すか
    
    Returns:
        dict: ログエントリ
    """
    timestamp = datetime.now()
    log_entry = {
        "timestamp": timestamp,
        "level": level,
        "message": message
    }

    # 履歴保存
    if keep_history:
        if "ui_logs" not in st.session_state:
            st.session_state["ui_logs"] = []
        st.session_state["ui_logs"].append(log_entry)

    # コンソール出力
    print(f"[{timestamp:%H:%M:%S}] [{level}] {message}")

    # Streamlit UI 表示
    if show_in_ui:
        if level == "INFO":
            st.info(f"[{timestamp:%H:%M:%S}] {message}")
        elif level == "SUCCESS":
            st.success(f"[{timestamp:%H:%M:%S}] {message}")
        elif level == "WARNING":
            st.warning(f"[{timestamp:%H:%M:%S}] {message}")
        elif level == "ERROR":
            st.error(f"[{timestamp:%H:%M:%S}] {message}")

    return log_entry

def show_ui_log_history(last_n: int = 20):
    """
    Streamlitで過去ログを表示
    """
    st.markdown("### UI Log History")
    logs: List[Dict] = st.session_state.get("ui_logs", [])
    for entry in logs[-last_n:]:
        ts = entry["timestamp"].strftime("%H:%M:%S")
        lvl = entry["level"]
        msg = entry["message"]
        st.write(f"[{ts}] [{lvl}] {msg}")