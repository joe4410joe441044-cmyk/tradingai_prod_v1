# -*- coding: utf-8 -*-

import time
from typing import Dict, Any
from backend.utils.log_buffer import logger as app_logger


class RiskManager:
    """
    Production-grade Risk Control System
    ※ %表記に統一（Engineと一致）
    """

    def __init__(
        self,
        max_positions: int = 3,
        max_daily_loss: float = -50.0,
        max_trade_size: float = 0.01,
        cooldown_sec: int = 5,
        max_consecutive_losses: int = 5,
        logger=None
    ):
        self.logger = logger or app_logger

        # =========================
        # CONFIG
        # =========================
        self.max_positions = max_positions
        self.max_daily_loss = max_daily_loss
        self.max_trade_size = max_trade_size
        self.cooldown_sec = cooldown_sec
        self.max_consecutive_losses = max_consecutive_losses

        # 🔥 DD設定（%）
        self.max_drawdown_pct = 10.0

        # =========================
        # STATE
        # =========================
        self.last_trade_time = 0.0
        self.daily_pnl = 0.0
        self.consecutive_losses = 0

        self.trading_disabled = False
        self.kill_reason = ""

        self.initial_equity = None
        self.peak_equity = None

        self.open_positions = 0

        self.start_of_day_balance = None
        self.peak_daily_pnl = 0.0

        self.last_reset_day = self._today()

    # =================================================
    # UTIL
    # =================================================
    def _today(self) -> str:
        return time.strftime("%Y-%m-%d")

    def _reset_if_new_day(self):
        today = self._today()

        if today != self.last_reset_day:
            self.logger.info("[RISK] daily reset triggered")

            self.daily_pnl = 0.0
            self.peak_daily_pnl = 0.0
            self.consecutive_losses = 0
            self.trading_disabled = False

            self.last_reset_day = today
            self.start_of_day_balance = None

    # =================================================
    # DD UPDATE（%ベース）
    # =================================================
    def update_equity(self, equity: float):

        if self.initial_equity is None:
            self.initial_equity = equity
            self.peak_equity = equity
            self.logger.info(f"[RISK] initial equity set: {equity}")
            return

        if equity > self.peak_equity:
            self.peak_equity = equity

        if self.peak_equity == 0:
            return

        drawdown = (equity - self.peak_equity) / self.peak_equity * 100

        self.logger.info(
            f"[RISK] equity={equity:.2f} peak={self.peak_equity:.2f} DD={drawdown:.2f}%"
        )

        if drawdown <= -self.max_drawdown_pct:
            self.trading_disabled = True
            self.kill_reason = "MAX DRAWDOWN"
            self.logger.error("[RISK] KILL SWITCH TRIGGERED (DD)")

    # =================================================
    # RESET
    # =================================================
    def reset(self):
        self.initial_equity = None
        self.peak_equity = None

        self.trading_disabled = False
        self.kill_reason = ""

        self.consecutive_losses = 0
        self.daily_pnl = 0.0

        self.logger.info("[RISK] reset")

    # =================================================
    # ENTRY CHECK（qtyベース）
    # =================================================
    def can_enter(self, signal: Dict[str, Any]) -> bool:

        self._reset_if_new_day()

        if self.trading_disabled:
            self.logger.warning("[RISK] trading disabled (KILL SWITCH)")
            return False

        now = time.time()
        if now - self.last_trade_time < self.cooldown_sec:
            self.logger.warning("[RISK] cooldown active")
            return False

        if self.open_positions >= self.max_positions:
            self.logger.warning("[RISK] max positions reached")
            return False

        qty = float(signal.get("qty", 0.0))
        if qty <= 0:
            self.logger.warning("[RISK] invalid qty")
            return False

        if qty > self.max_trade_size:
            self.logger.warning(
                f"[RISK] trade size too large: {qty} > {self.max_trade_size}"
            )
            return False

        if self.consecutive_losses >= self.max_consecutive_losses:
            self.logger.error("[RISK] consecutive loss limit → KILL SWITCH")
            self.trading_disabled = True
            self.kill_reason = "CONSECUTIVE LOSSES"
            return False

        if self.daily_pnl <= self.max_daily_loss:
            self.logger.error("[RISK] daily loss limit → KILL SWITCH")
            self.trading_disabled = True
            self.kill_reason = "DAILY LOSS"
            return False

        return True

    # =================================================
    # ENTRY REGISTER
    # =================================================
    def on_entry(self, signal: Dict[str, Any] = None):
        self.last_trade_time = time.time()
        self.open_positions += 1
        self.logger.info(f"[RISK] entry | positions={self.open_positions}")

    # =================================================
    # EXIT REGISTER
    # =================================================
    def on_exit(self, pnl: float):

        self.open_positions = max(0, self.open_positions - 1)

        self.daily_pnl += pnl
        self.peak_daily_pnl = max(self.peak_daily_pnl, self.daily_pnl)

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        if self.daily_pnl <= self.max_daily_loss * 0.8:
            self.logger.warning("[RISK] approaching daily loss limit")

        self.logger.info(
            f"[RISK] pnl={pnl:.4f} "
            f"daily_pnl={self.daily_pnl:.4f} "
            f"peak={self.peak_daily_pnl:.4f} "
            f"loss_streak={self.consecutive_losses} "
            f"positions={self.open_positions}"
        )

    # =================================================
    # KILL SWITCH
    # =================================================
    def trigger_kill_switch(self, reason: str = "manual"):
        self.trading_disabled = True
        self.kill_reason = reason
        self.logger.error(f"[RISK] KILL SWITCH: {reason}")

    def enable(self):
        self.trading_disabled = False
        self.kill_reason = ""
        self.logger.info("[RISK] trading enabled")

    # =================================================
    # STATUS
    # =================================================
    def status(self) -> Dict[str, Any]:
        return {
            "trading_disabled": self.trading_disabled,
            "kill_reason": self.kill_reason,
            "daily_pnl": self.daily_pnl,
            "peak_daily_pnl": self.peak_daily_pnl,
            "consecutive_losses": self.consecutive_losses,
            "positions": self.open_positions,
            "last_trade_time": self.last_trade_time,
            "peak_equity": self.peak_equity,
        }
