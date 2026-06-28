from dataclasses import dataclass, field


@dataclass
class RuntimeState:

    symbol: str = ""

    timestamp: float = 0.0

    directional_bias: float = 0.0

    momentum_score: float = 0.0

    volatility_score: float = 0.0

    liquidity_score: float = 0.0

    confidence_score: float = 0.0

    position_pressure: float = 0.0

    orderflow_delta: float = 0.0

    spread_score: float = 0.0

    imbalance_score: float = 0.0

    custom_features: dict = field(default_factory=dict)