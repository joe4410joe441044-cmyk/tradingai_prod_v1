# -*- coding: utf-8 -*-
import time
import logging
from typing import Dict, Any


class RiskManager:
    """
    Production-grade Risk Control System
    """

    def __init__(
        self,
        max_positions: int = 3,
        max_daily_loss: float = -50.0,
        max_trade_size: float = 0.01,
        cooldown_sec: int = 5,
        max_consecutive_losses: int = 5,
        logger=None  # 🔥 追加（ここが今回の核心）
    ):
        # 🔥 外部logger優先
        self.logger = logger or logging.getLogger(__name__)

        # =========================
        # CONFIG
        # =========================
        self.max_positions = max_positions
        self.max_daily_loss = max_daily_loss
        self.max_trade_size = max_trade_size
        self.cooldown_sec = cooldown_sec
        self.max_consecutive_losses = max_consecutive_losses

        # =========================
        # STATE
        # =========================
        self.last_trade_time = 0.0
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.trading_disabled = False

        # 🔥 ExecutionEngine互換
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
    # ENTRY CHECK
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
            return False

        if self.daily_pnl <= self.max_daily_loss:
            self.logger.error("[RISK] daily loss limit → KILL SWITCH")
            self.trading_disabled = True
            return False

        return True

    # =================================================
    # ENTRY REGISTER
    # =================================================
    def on_entry(self, signal: Dict[str, Any] = None):
        self.last_trade_time = time.time()
        self.open_positions += 1

        self.logger.info(
            f"[RISK] entry | positions={self.open_positions}"
        )

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
    def kill_switch(self, reason: str = "manual"):
        self.trading_disabled = True
        self.logger.error(f"[RISK] KILL SWITCH: {reason}")

    def enable(self):
        self.trading_disabled = False
        self.logger.info("[RISK] trading enabled")

    # =================================================
    # STATUS
    # =================================================
    def status(self) -> Dict[str, Any]:
        return {
            "trading_disabled": self.trading_disabled,
            "daily_pnl": self.daily_pnl,
            "peak_daily_pnl": self.peak_daily_pnl,
            "consecutive_losses": self.consecutive_losses,
            "positions": self.open_positions,
            "last_trade_time": self.last_trade_time,
        }