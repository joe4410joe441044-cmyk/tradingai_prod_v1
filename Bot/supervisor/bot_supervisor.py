import subprocess
import time
import datetime
import os


class BotSupervisor:

    def __init__(self):

        # BOT起動コマンド
        self.bot_command = ["python", "-m", "Bot.main"]

        # 再起動待機時間
        self.restart_delay = 5

        # ログ
        self.log_file = "logs/supervisor.log"

        os.makedirs("logs", exist_ok=True)

    # =========================================
    # ログ
    # =========================================

    def log(self, message):

        t = datetime.datetime.now()

        line = f"{t} | {message}"

        print(line)

        with open(self.log_file, "a") as f:
            f.write(line + "\n")

    # =========================================
    # BOT実行
    # =========================================

    def run(self):

        self.log("Supervisor started")

        while True:

            try:

                self.log("Starting BOT")

                process = subprocess.Popen(self.bot_command)

                process.wait()

                self.log("BOT stopped")

            except Exception as e:

                self.log(f"BOT crashed: {e}")

            self.log(f"Restarting in {self.restart_delay} sec")

            time.sleep(self.restart_delay)


if __name__ == "__main__":

    supervisor = BotSupervisor()

    supervisor.run()