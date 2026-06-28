import time


class ExecutionSignalAdapter:

    @staticmethod
    def adapt(execution_event):

        if not execution_event:
            return None

        if not execution_event.get("executed"):
            return None

        direction = execution_event.get(
            "direction"
        )

        if direction == "LONG":
            side = "BUY"

        elif direction == "SHORT":
            side = "SELL"

        else:
            return None

        return {
            "id": int(time.time() * 1000),
            "side": side,
            "timestamp": time.time(),
        }