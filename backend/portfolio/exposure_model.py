class ExposureModel:

    def risk_score(self, positions):

        return sum(p["qty"] for p in positions.values())