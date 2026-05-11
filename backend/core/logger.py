import logging

DEBUG_MODE = False

logger = logging.getLogger("TradingAI")

logger.setLevel(
    logging.DEBUG if DEBUG_MODE else logging.INFO
)

formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)s %(message)s"
)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

logger.handlers.clear()
logger.addHandler(stream_handler)