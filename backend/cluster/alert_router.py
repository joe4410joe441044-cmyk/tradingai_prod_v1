from backend.utils.log_buffer import logger


class AlertRouter:

    def route(self, alert):

        logger.warning("ALERT: %s", alert)
