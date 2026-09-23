"""WORK AA: LIVE baseline persistence without invented values."""
from pathlib import Path

from backend.strategy.parameters.baselines import LIVE_CLASS_CONSTANT_BASELINE
from backend.strategy.parameters.settings_service import ParameterSettingsService


def test_persist_live_baseline_exact_values(tmp_path: Path):
    service = ParameterSettingsService(base_directory=tmp_path)
    first = service.persist_baseline_if_missing("LIVE")
    assert first["outcome"] == "PERSISTED"
    assert first["persisted"] is True
    assert first["storeStatus"] == "VALID"
    assert first["authorityStatus"] == "PERSISTED"
    assert first["spreadUnitProvenance"] == "LEGACY_UNIT_REPRESENTATION"
    assert first["source"] == "MIGRATED_CLASS_CONSTANT"

    cfg = service.configuration("LIVE")
    assert cfg["storeStatus"] == "VALID"
    assert cfg["authorityStatus"] == "PERSISTED"
    assert cfg["unitProvenance"]["maximumStrategySpreadPct"]["classification"] == (
        "LEGACY_UNIT_REPRESENTATION"
    )
    # Exact baseline values — including imperfect spread constant 0.0005.
    for name, value in LIVE_CLASS_CONSTANT_BASELINE.values.items():
        assert cfg["parameters"][name] == value

    second = service.persist_baseline_if_missing("LIVE")
    assert second["outcome"] == "ALREADY_PERSISTED"
    assert second["persisted"] is False


def test_persist_does_not_copy_paper_spread(tmp_path: Path):
    service = ParameterSettingsService(base_directory=tmp_path)
    service.persist_baseline_if_missing("LIVE")
    live = service.configuration("LIVE")["parameters"]["maximumStrategySpreadPct"]
    assert live == 0.0005
    assert live != 0.50
