# Bot/control/telegram_controller.py

from Bot.control.command_handler import CommandHandler
from Bot.utils.telegram_notifier import TelegramNotifier


class TelegramController:

    def __init__(self, notifier: TelegramNotifier, handler=None):
        self.handler = handler or CommandHandler()
        self.notifier = notifier

    def process(self, text: str):
        response = self.handler.handle(text)
        self.notifier.send(response)

    # =========================
    # 通知系
    # =========================
    def notify_entry(self, trade_type: str, entry_price: float, sl: float, tp: float):
        msg = f"ENTRY {trade_type} @ {entry_price}\nSL: {sl}, TP: {tp}"
        self.notifier.send(msg)

    def notify_take_profit(self, profit: float):
        self.notifier.send(f"TP HIT! Profit: {profit}")

    def notify_stop_loss(self, loss: float):
        self.notifier.send(f"SL HIT! Loss: {loss}")