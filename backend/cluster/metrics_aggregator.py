class MetricsAggregator:

    def aggregate(self, logs):

        return {
            "errors": len([l for l in logs if l["type"] == "ERROR"]),
            "orders": len([l for l in logs if l["type"] == "ORDER_EXECUTE"])
        }