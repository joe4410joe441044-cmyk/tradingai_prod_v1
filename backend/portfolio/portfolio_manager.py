class PortfolioManager:

    def __init__(self):

        self.positions = {}
        self.max_exposure = 0.25

    # =====================================================
    # CHECK
    # =====================================================
    def can_open(self, symbol: str, qty: float):

        current = sum(
            p["qty"] for p in self.positions.values()
            if p["symbol"] == symbol
        )

        return (current + qty) <= self.max_exposure

    # =====================================================
    # ADD
    # =====================================================
    def add(self, position: dict):

        self.positions[position["id"]] = position

    # =====================================================
    # REMOVE
    # =====================================================
    def remove(self, pid: str):

        if pid in self.positions:
            del self.positions[pid]

    # =====================================================
    # RISK SUMMARY
    # =====================================================
    def summary(self):

        return {
            "total": len(self.positions),
            "symbols": list(set(p["symbol"] for p in self.positions.values()))
        }