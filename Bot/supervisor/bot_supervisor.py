# -*- coding: utf-8 -*-
import subprocess
import time
import datetime
import os


class BotSupervisor:

    def __init__(self):

        # BOTE
        self.bot_command = ["python", "-m", "Bot.main"]

        # EE
        self.restart_delay = 5

        # 
        self.log_file = "logs/supervisor.log"

        os.makedirs("logs", exist_ok=True)

    # =========================================
    # 
    # =========================================

    def log(self, message):

        t = datetime.datetime.now()

        line = f"{t} | {message}"

        print(line)

        with open(self.log_file, "a") as f:
            f.write(line + "\n")

    # =========================================
    # BOTE
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