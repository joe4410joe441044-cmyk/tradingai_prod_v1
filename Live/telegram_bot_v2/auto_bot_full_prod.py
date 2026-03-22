import logging
from threading import Thread
from telegram.ext import ApplicationBuilder
from telegram.request import HTTPXRequest
from dotenv import load_dotenv
import os

from Live.telegram_bot_v2.bot_core import periodic_check
from Live.telegram_bot_v2.bot_ui import register_handlers

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

def main():
    Thread(target=periodic_check, daemon=True).start()

    if not TELEGRAM_TOKEN:
        logging.error("TELEGRAM_TOKEN ñ¢ê›íË")
        return

    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .request(request)
        .build()
    )

    register_handlers(app)

    logging.info("?? Bot ãNìÆÅitelegram_bot_v2Åj")

    app.run_polling()

if __name__ == "__main__":
    main()
