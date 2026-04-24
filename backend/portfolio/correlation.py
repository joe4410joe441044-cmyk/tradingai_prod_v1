class CorrelationModel:

    def is_high_correlation(self, symbol_a, symbol_b):

        return symbol_a[:3] == symbol_b[:3]