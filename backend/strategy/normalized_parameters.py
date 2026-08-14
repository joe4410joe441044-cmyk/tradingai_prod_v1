"""Small, explicit authority for normalized Paper strategy parameters.

The production/default path keeps the legacy values.  The calibrated set is
opt-in and is selected only by a Paper BotManager runtime.
"""

from copy import deepcopy


CALIBRATION_AUTHORITY = "E2E-TRACE-1G/891-observation-offline-calibration"


def _parameter(value, unit, description, authority=CALIBRATION_AUTHORITY):
    return {
        "value": value,
        "unit": unit,
        "authority": authority,
        "description": description,
    }


PAPER_NORMALIZED_CALIBRATION = {
    "schemaVersion": 2,
    "calibrationId": "E2E-TRACE-1G-PAPER-v1",
    "scope": "PAPER_ONLY",
    "authority": CALIBRATION_AUTHORITY,
    "parameters": {
        "strategyFeatureCalibrationId": _parameter(
            "TIME_SYMBOL_NORMALIZED_V1",
            "contract_id",
            "Selects the Paper-only normalized feature and simplified gate contract.",
        ),
        "volumeWindowSize": _parameter(
            100,
            "observations",
            "Maximum causal history used for normalized volume percentiles.",
        ),
        "volumeMinimumHistory": _parameter(
            20,
            "observations",
            "Minimum prior observations; liquidity remains fail-closed before this.",
        ),
        "absorptionVolumePercentile": _parameter(
            0.90,
            "rolling_quantile",
            "Abnormal top-of-book depth relative to the active symbol's own history.",
        ),
        "absorptionMaxPriceDeltaPct": _parameter(
            0.10,
            "percent",
            "Maximum symbol-normalized price movement for absorption.",
        ),
        "stagnantVolumePercentile": _parameter(
            0.90,
            "rolling_quantile",
            "Heavy flow relative to the active symbol's own depth history.",
        ),
        "stagnantMinSpreadPct": _parameter(
            0.50,
            "percent",
            "Minimum symbol-normalized spread for stagnant heavy flow.",
        ),
        "maximumStrategySpreadPct": _parameter(
            0.50,
            "percent",
            "Maximum symbol-normalized spread accepted by the Paper strategy.",
        ),
        "fakePressureDifference": _parameter(
            0.70,
            "ratio",
            "Dimensionless pressure imbalance; unchanged from the legacy detector.",
        ),
        "fakePressureMaxPriceDeltaPct": _parameter(
            0.10,
            "percent",
            "Maximum symbol-normalized price movement for fake pressure.",
        ),
        "minimumStrategyConfidence": _parameter(
            0.23,
            "score_0_to_1",
            "Downstream Paper compatibility floor; diagnostic, not a Strategy hard gate.",
        ),
        "momentumWindowSeconds": _parameter(
            60.0,
            "seconds",
            "Causal Strategy momentum horizon matching the configured one-minute intent.",
        ),
        "momentumSampleCadenceSeconds": _parameter(
            1.0,
            "seconds",
            "Maximum one Strategy price sample per wall-clock bucket.",
        ),
        "momentumMinimumWarmupSeconds": _parameter(
            20.0,
            "seconds",
            "Minimum elapsed causal history before Paper momentum is usable.",
        ),
        "momentumMinimumSamples": _parameter(
            10,
            "time_bucket_samples",
            "Minimum distinct sampled time buckets before Paper momentum is usable.",
        ),
        "momentumActivityExponent": _parameter(
            0.5,
            "exponent",
            "Square-root activity damping used in directionPurity times activityFactor.",
        ),
        "liquidityQualityPercentile": _parameter(
            0.90,
            "rolling_quantile",
            "Prior-volume reference used to make depth quality symbol-relative.",
        ),
        "minimumCompositeScore": _parameter(
            0.34,
            "score_0_to_1",
            "Joint safety-direction replay boundary retaining 39 of 891 Paper decisions.",
        ),
    },
}


def paper_calibration_for_mode(mode):
    """Return an isolated Paper set; Live/default callers receive no override."""

    if str(mode or "").strip().lower() != "paper":
        return None
    return deepcopy(PAPER_NORMALIZED_CALIBRATION)


def parameter_value(parameter_set, name, default):
    """Read a calibrated value only from the explicitly Paper-scoped authority."""

    if not isinstance(parameter_set, dict):
        return default
    if parameter_set.get("scope") != "PAPER_ONLY":
        return default
    parameters = parameter_set.get("parameters")
    if not isinstance(parameters, dict):
        return default
    parameter = parameters.get(name)
    if not isinstance(parameter, dict) or "value" not in parameter:
        return default
    return parameter["value"]
