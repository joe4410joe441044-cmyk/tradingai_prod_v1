import pytest

from backend.strategy.MicrostructureEdgeStrategy import MicrostructureEdgeStrategy


def state(**overrides):
    value = {
        "imbalanceStrength": 1.0,
        "momentumPersistence": 1.0,
        "spreadQuality": 1.0,
        "liquidityQuality": 1.0,
        "spread": 0.0001,
        "spreadVolatility": 0.1,
        "buyPressure": 0.8,
        "sellPressure": 0.2,
        "absorptionDetected": False,
        "stagnantHeavyFlow": False,
        "fakePressureDetected": False,
        "liquidityInstabilityDebug": {"totalVolume": 100000},
    }
    value.update(overrides)
    return value


def readiness(**overrides):
    result = MicrostructureEdgeStrategy().process_microstructure_strategy(state(**overrides))
    assert result["valid"] is True
    return result["strategy"]["entryReadiness"]


def conditions(contract):
    return {condition["code"]: condition for condition in contract["conditions"]}


@pytest.mark.parametrize(
    ("overrides", "reason", "blocker"),
    [
        ({"spread": 0.0006}, "ABNORMAL_SPREAD", "SPREAD"),
        ({"spreadVolatility": 0.66}, "SPREAD_VOLATILITY", "SPREAD_VOLATILITY"),
        ({"liquidityQuality": 0.34}, "LIQUIDITY_DETERIORATION", "LIQUIDITY_QUALITY"),
        ({"absorptionDetected": True}, "LIQUIDITY_INSTABILITY", "LIQUIDITY_SAFETY"),
        ({"momentumPersistence": 0.49}, "CONFLICTING_MOMENTUM", "MOMENTUM"),
        ({"imbalanceStrength": 0.0, "momentumPersistence": 0.5, "spreadQuality": 0.0, "liquidityQuality": 0.35}, "WEAK_EDGE", "EDGE"),
        ({"imbalanceStrength": 0.65, "momentumPersistence": 0.5, "spreadQuality": 1.0, "liquidityQuality": 0.35}, "LOW_CONFIDENCE", "CONFIDENCE"),
    ],
)
def test_suppression_priority_is_published_without_changing_strategy(overrides, reason, blocker):
    contract = readiness(**overrides)
    assert contract["suppressionReason"] == reason
    assert contract["blockingCondition"] == blocker
    assert contract["strategyDecision"] == "HOLD"


def test_buy_sell_and_all_pass_readiness():
    buy = readiness()
    sell = readiness(buyPressure=0.2, sellPressure=0.8)
    assert buy["candidateDirection"] == buy["strategyDecision"] == "BUY"
    assert sell["candidateDirection"] == sell["strategyDecision"] == "SELL"
    assert all(item["status"] == "PASS" for item in buy["conditions"])


def test_candidate_sell_remains_separate_from_final_hold():
    contract = readiness(buyPressure=0.2, sellPressure=0.8, liquidityQuality=0.0936)
    assert contract["candidateDirection"] == "SELL"
    assert contract["strategyDecision"] == "HOLD"
    assert contract["executionAllowed"] is False


def test_delta_and_source_status_rules():
    contract = readiness(liquidityQuality=0.2, momentumPersistence=0.4)
    by_code = conditions(contract)
    assert by_code["LIQUIDITY_QUALITY"]["delta"] == 0.15
    assert by_code["MOMENTUM"]["delta"] == 0.1
    assert by_code["EDGE"]["delta"] is None
    assert by_code["CONFIDENCE"]["delta"] is None
    assert by_code["ABSORPTION"]["delta"] is None
    assert by_code["LIQUIDITY_SAFETY"]["delta"] is None
    assert by_code["LIQUIDITY_SAFETY"]["sourceStatus"] == "DERIVED"
    assert by_code["PRESSURE_ALIGNMENT"]["sourceStatus"] == "DERIVED"
    assert by_code["LIQUIDITY_VOLUME"]["sourceStatus"] == "DERIVED"


def test_missing_defaults_are_not_reported_as_measured():
    missing = state()
    del missing["momentumPersistence"]
    del missing["absorptionDetected"]
    result = MicrostructureEdgeStrategy().process_microstructure_strategy(missing)
    by_code = conditions(result["strategy"]["entryReadiness"])
    assert by_code["MOMENTUM"]["currentValue"] == 0.0
    assert by_code["MOMENTUM"]["sourceStatus"] == "DEFAULTED"
    assert by_code["ABSORPTION"]["sourceStatus"] == "DEFAULTED"


def test_liquidity_safety_summary_is_computed_by_backend():
    passed = conditions(readiness())
    failed = conditions(readiness(fakePressureDetected=True))
    assert passed["LIQUIDITY_SAFETY"]["status"] == "PASS"
    assert failed["LIQUIDITY_SAFETY"]["status"] == "FAIL"


def test_primary_suppression_order_wins_when_multiple_conditions_fail():
    contract = readiness(spread=0.001, liquidityQuality=0.1, absorptionDetected=True, momentumPersistence=0.0)
    assert contract["suppressionReason"] == "ABNORMAL_SPREAD"
    assert contract["blockingCondition"] == "SPREAD"


def test_conflicting_momentum_identifies_the_condition_that_failed():
    low_momentum = readiness(momentumPersistence=0.49)
    low_alignment = readiness(buyPressure=0.57, sellPressure=0.43)

    assert low_momentum["suppressionReason"] == "CONFLICTING_MOMENTUM"
    assert low_momentum["blockingCondition"] == "MOMENTUM"
    assert low_alignment["suppressionReason"] == "CONFLICTING_MOMENTUM"
    assert low_alignment["blockingCondition"] == "PRESSURE_ALIGNMENT"
