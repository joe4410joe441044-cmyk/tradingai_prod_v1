"""Validation tests for canonical strategy parameters (E-PARAM-1)."""

from backend.strategy.parameters import (
    PAPER_MIGRATION_BASELINE,
    ValidationCode,
    validate_parameters,
)


def values(**overrides):
    data = dict(PAPER_MIGRATION_BASELINE.values)
    data.update(overrides)
    return data


def _codes(result):
    return {issue.code for issue in result.errors}


def test_valid_complete_set_has_no_errors():
    result = validate_parameters(values(), require_complete=True)
    assert result.is_valid
    assert result.errors == ()
    assert result.warnings == ()


def test_partial_set_is_allowed_without_require_complete():
    result = validate_parameters({"minimumCompositeScore": 0.5})
    assert result.is_valid


def test_require_complete_flags_missing_parameters():
    result = validate_parameters(
        {"minimumCompositeScore": 0.5}, require_complete=True
    )
    assert not result.is_valid
    assert ValidationCode.MISSING_PARAMETER in _codes(result)


def test_range_rejection_below_and_above():
    assert ValidationCode.BELOW_MINIMUM in _codes(
        validate_parameters(values(maximumHoldMs=99))
    )
    assert ValidationCode.ABOVE_MAXIMUM in _codes(
        validate_parameters(values(maximumHoldMs=60001))
    )
    assert ValidationCode.BELOW_MINIMUM in _codes(
        validate_parameters(values(momentumWindowSeconds=4.9))
    )
    assert ValidationCode.ABOVE_MAXIMUM in _codes(
        validate_parameters(values(momentumWindowSeconds=600.1))
    )
    assert ValidationCode.BELOW_MINIMUM in _codes(
        validate_parameters(values(minimumCompositeScore=-0.1))
    )


def test_exclusive_boundaries():
    assert not validate_parameters(
        values(maximumStrategySpreadPct=0.0)
    ).is_valid
    assert validate_parameters(
        values(maximumStrategySpreadPct=5.0)
    ).is_valid
    assert not validate_parameters(
        values(maximumStrategySpreadPct=5.0001)
    ).is_valid

    assert not validate_parameters(
        values(absorptionVolumePercentile=0.0)
    ).is_valid
    assert validate_parameters(
        values(absorptionVolumePercentile=1.0)
    ).is_valid

    assert validate_parameters(values(minimumHoldMs=0)).is_valid
    assert validate_parameters(values(minimumCompositeScore=0.0)).is_valid
    assert validate_parameters(values(minimumCompositeScore=1.0)).is_valid


def test_type_rejection():
    for bad in ("0.5", True, None, [], {}):
        result = validate_parameters(values(minimumCompositeScore=bad))
        assert not result.is_valid, bad
        assert ValidationCode.INVALID_TYPE in _codes(result), bad


def test_nan_and_infinity_rejection():
    for bad in (float("nan"), float("inf"), float("-inf")):
        result = validate_parameters(values(minimumCompositeScore=bad))
        assert not result.is_valid
        assert ValidationCode.NON_FINITE in _codes(result)


def test_integer_semantics():
    result = validate_parameters(values(maximumHoldMs=500.5))
    assert not result.is_valid
    assert ValidationCode.NOT_INTEGRAL in _codes(result)
    assert validate_parameters(values(maximumHoldMs=501.0)).is_valid


def test_unknown_parameter_rejection():
    result = validate_parameters(values(notAParameter=1.0))
    assert not result.is_valid
    assert ValidationCode.UNKNOWN_PARAMETER in _codes(result)


def test_cross_field_hold_time_order():
    result = validate_parameters(
        values(minimumHoldMs=3000, maximumHoldMs=3000)
    )
    assert not result.is_valid
    assert ValidationCode.HOLD_TIME_ORDER in _codes(result)

    result = validate_parameters(
        values(minimumHoldMs=4000, maximumHoldMs=3000)
    )
    assert ValidationCode.HOLD_TIME_ORDER in _codes(result)


def test_cross_field_momentum_warmup_order():
    result = validate_parameters(
        values(momentumMinimumWarmupSeconds=61.0, momentumWindowSeconds=60.0)
    )
    assert not result.is_valid
    assert ValidationCode.MOMENTUM_WARMUP_ORDER in _codes(result)

    result = validate_parameters(
        values(momentumMinimumWarmupSeconds=60.0, momentumWindowSeconds=60.0)
    )
    assert result.is_valid


def test_warning_confidence_exceeds_composite():
    result = validate_parameters(
        values(minimumStrategyConfidence=0.90, minimumCompositeScore=0.50)
    )
    assert result.is_valid
    assert ValidationCode.CONFIDENCE_EXCEEDS_COMPOSITE in {
        issue.code for issue in result.warnings
    }


def test_warning_exit_momentum_high():
    result = validate_parameters(values(exitMomentumMinimum=0.6))
    assert result.is_valid
    assert ValidationCode.EXIT_MOMENTUM_HIGH in {
        issue.code for issue in result.warnings
    }

    assert validate_parameters(values(exitMomentumMinimum=0.5)).warnings == ()


def test_errors_and_warnings_are_distinct():
    result = validate_parameters(
        values(
            maximumHoldMs=99,
            exitMomentumMinimum=0.9,
        )
    )
    assert not result.is_valid
    assert result.errors
    assert result.warnings
    payload = result.to_dict()
    assert payload["isValid"] is False
    assert payload["errors"]
    assert payload["warnings"]


def test_frontend_serialized_full_draft_contract_passes():
    """The normalized frontend payload (canonical JSON numbers) must validate.

    This mirrors the Parameter Settings save path after type normalization:
    every editable value is a JSON number, not a DOM string.
    """

    normalized_payload = {
        "minimumCompositeScore": 0.34,
        "maximumStrategySpreadPct": 0.5,
        "momentumWindowSeconds": 60,
        "minimumStrategyConfidence": 0.23,
        "maximumHoldMs": 30000,
        "minimumHoldMs": 500,
        "exitMomentumMinimum": 0.4,
        "exitLiquidityQualityMinimum": 0.3,
        "exitSpreadQualityMinimum": 0.3,
        "momentumMinimumWarmupSeconds": 20,
        "absorptionVolumePercentile": 0.9,
        "liquidityQualityPercentile": 0.9,
    }

    result = validate_parameters(normalized_payload, require_complete=True)
    assert result.is_valid, result.to_dict()
    assert result.errors == ()

    # maximumHoldMs=30000 as a canonical JSON number is valid by itself.
    assert validate_parameters(values(maximumHoldMs=30000)).is_valid


def test_dom_string_serialization_is_rejected_as_invalid_type():
    """Regression guard: a raw DOM string must remain rejected by the validator.

    The frontend fix normalizes the payload; the backend must NOT be weakened
    to accept numeric strings.
    """

    result = validate_parameters(
        values(maximumHoldMs="30000"), require_complete=True
    )
    assert not result.is_valid
    assert ValidationCode.INVALID_TYPE in _codes(result)
    assert [issue.parameter for issue in result.errors] == ["maximumHoldMs"]
