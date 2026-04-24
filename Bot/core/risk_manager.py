# -*- coding: utf-8 -*-

import time
import logging
from typing import Dict, Any


class RiskManager:
    """
    Production Risk Control Layer
    - ポジション制御
    - 損失制限
    - ドローダウン制御
    - エントリー制御
    - kill switch
    - monitoring連携
    """

    def __init__(
        self,
        max_positions: int = 3,
        max_daily_loss: float = -50.0,
        max_drawdown: float = -100.0
    ):

        self.max_positions = max_positions
        self.max_daily_loss = max_daily_loss
        self.max_drawdown = max_drawdown

        self.positions = {}
        self.daily_pnl = 0.0
        self.equity = 0.0

        self.kill_switch = False

        self.monitor = None

        self.logger = logging.getLogger("RiskManager")

    # =====================================================
    # MONITOR CONNECT
    # =====================================================
    def set_monitor(self, monitor):

        self.monitor = monitor

        if self.monitor:
            self.monitor.update_status("risk_manager", True)
            self.monitor.log_event("RISK_MANAGER_CONNECTED", {})

    # =====================================================
    # ENTRY CHECK
    # =====================================================
    def allow_entry(self, context: Dict[str, Any]) -> bool:

        if self.kill_switch:
            self._log_block("KILL_SWITCH")
            return False

        if len(self.positions) >= self.max_positions:
            self._log_block("MAX_POSITIONS")
            return False

        if self.daily_pnl <= self.max_daily_loss:
            self._log_block("DAILY_LOSS_LIMIT")
            return False

        if self.equity <= self.max_drawdown:
            self._log_block("DRAWDOWN_LIMIT")
            return False

        if self.monitor:
            self.monitor.log_event("RISK_ALLOW_ENTRY", context)

        return True

    # =====================================================
    # POSITION REGISTER
    # =====================================================
    def register_position(self, position_id: str, data: Dict[str, Any]):

        self.positions[position_id] = data

        if self.monitor:
            self.monitor.log_event("POSITION_REGISTERED", data)

    # =====================================================
    # POSITION CLOSE
    # =====================================================
    def close_position(self, position_id: str, pnl: float):

        if position_id in self.positions:
            del self.positions[position_id]

        self.daily_pnl += pnl
        self.equity += pnl

        if self.monitor:
            self.monitor.log_event("POSITION_CLOSED", {
                "position_id": position_id,
                "pnl": pnl,
                "daily_pnl": self.daily_pnl,
                "equity": self.equity
            })

    # =====================================================
    # KILL SWITCH
    # =====================================================
    def activate_kill_switch(self, reason: str):

        self.kill_switch = True

        if self.monitor:
            self.monitor.log_error("RISK_KILL_SWITCH", Exception(reason), {
                "reason": reason
            })

    # =====================================================
    # RESET
    # =====================================================
    def reset_daily(self):

        self.daily_pnl = 0.0
        self.positions.clear()

        if self.monitor:
            self.monitor.log_event("RISK_RESET", {})

    # =====================================================
    # INTERNAL LOG
    # =====================================================
    def _log_block(self, reason: str):

        if self.monitor:
            self.monitor.log_event("RISK_BLOCK", {
                "reason": reason,
                "positions": len(self.positions),
                "pnl": self.daily_pnl
            })

        self.logger.warning(f"[RISK BLOCK] {reason}")

    # =====================================================
    # STATUS
    # =====================================================
    def get_status(self):

        return {
            "positions": len(self.positions),
            "daily_pnl": self.daily_pnl,
            "equity": self.equity,
            "kill_switch": self.kill_switch,
            "limits": {
                "max_positions": self.max_positions,
                "max_daily_loss": self.max_daily_loss,
                "max_drawdown": self.max_drawdown
            }
        }