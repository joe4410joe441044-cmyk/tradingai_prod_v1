import csv
import os
import datetime


class BotLogger:

    def __init__(self, log_dir="logs"):

        self.log_dir = log_dir

        os.makedirs(log_dir, exist_ok=True)

        self.trade_file = os.path.join(log_dir, "trade_log.csv")
        self.signal_file = os.path.join(log_dir, "signal_log.csv")
        self.equity_file = os.path.join(log_dir, "equity_curve.csv")

        self._init_files()

    # =========================================
    # 初期化
    # =========================================

    def _init_files(self):

        if not os.path.exists(self.trade_file):

            with open(self.trade_file, "w", newline="") as f:

                writer = csv.writer(f)

                writer.writerow([
                    "time",
                    "strategy",
                    "type",
                    "entry",
                    "sl",
                    "tp"
                ])

        if not os.path.exists(self.signal_file):

            with open(self.signal_file, "w", newline="") as f:

                writer = csv.writer(f)

                writer.writerow([
                    "time",
                    "strategy",
                    "reason",
                    "price"
                ])

        if not os.path.exists(self.equity_file):

            with open(self.equity_file, "w", newline="") as f:

                writer = csv.writer(f)

                writer.writerow([
                    "time",
                    "equity"
                ])

    # =========================================
    # トレードログ
    # =========================================

    def log_trade(self, strategy, trade_type, entry, sl, tp):

        with open(self.trade_file, "a", newline="") as f:

            writer = csv.writer(f)

            writer.writerow([
                datetime.datetime.now(),
                strategy,
                trade_type,
                entry,
                sl,
                tp
            ])

    # =========================================
    # シグナルログ
    # =========================================

    def log_signal(self, strategy, reason, price):

        with open(self.signal_file, "a", newline="") as f:

            writer = csv.writer(f)

            writer.writerow([
                datetime.datetime.now(),
                strategy,
                reason,
                price
            ])

    # =========================================
    # Equityログ
    # =========================================

    def log_equity(self, equity):

        with open(self.equity_file, "a", newline="") as f:

            writer = csv.writer(f)

            writer.writerow([
                datetime.datetime.now(),
                equity
            ])