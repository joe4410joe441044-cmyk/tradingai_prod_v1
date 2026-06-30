from .base import BaseClient
from backend.utils.log_buffer import logger

class OkxClient(BaseClient):
    def __init__(self):
        pass

    def get_balance(self):
        return 1000.0

    def get_positions(self):
        return []

    def place_order(self, symbol, side, qty):
        logger.info("OKX ORDER side=%s qty=%s symbol=%s", side, qty, symbol)
