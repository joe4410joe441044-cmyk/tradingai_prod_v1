"""Offline policy range and current-capital regression; no runtime or orders."""
from dataclasses import replace
from decimal import Decimal as D

import pytest

from backend.money_management.loss_application_registration import build_default_money_management_config
from backend.money_management.loss_http_api import MoneyManagementApiBoundaryException
from backend.money_management.order_sizing import OrderSizingAuthority, SizingRejected
from tests.test_money_management_api import ready_boundary


@pytest.mark.parametrize('risk,exposure', [('0.5', '20'), ('1', '100'), ('2.1', '180'), ('5', '500')])
def test_explicit_policy_round_trip(risk, exposure):
    boundary, *_ = ready_boundary()
    boundary.update_configuration({'riskPerTradePercent': risk, 'totalExposurePercent': exposure,
                                   'singleSymbolExposurePercent': exposure, 'expectedRevision': 1})
    config = boundary.get_configuration().to_dict()
    assert D(config['riskPerTradePercent']) == D(risk)
    assert D(config['totalExposurePercent']) == D(exposure)
    assert D(config['singleSymbolExposurePercent']) == D(exposure)
    assert D(config['maximumPositionNotional']) == 100
    assert D(config['maximumLeverage']) == 5


@pytest.mark.parametrize('field', ['riskPerTradePercent', 'totalExposurePercent', 'singleSymbolExposurePercent'])
@pytest.mark.parametrize('value', ['0', '-1', 'NaN', 'Infinity', '', True, 2.1])
def test_invalid_ranges_are_atomic(field, value):
    boundary, *_ = ready_boundary()
    before = boundary.get_configuration()
    with pytest.raises(MoneyManagementApiBoundaryException):
        boundary.update_configuration({field: value})
    assert boundary.get_configuration() == before


@pytest.mark.parametrize('patch', [
    {'riskPerTradePercent': '5.0001'}, {'totalExposurePercent': '500.0001'},
    {'singleSymbolExposurePercent': '500.0001'},
    {'singleSymbolExposurePercent': '181', 'totalExposurePercent': '180'},
    {'maximumDrawdownPercent': '101'},
])
def test_caps_and_cross_field_order_are_atomic(patch):
    boundary, *_ = ready_boundary()
    before = boundary.get_configuration()
    with pytest.raises(MoneyManagementApiBoundaryException):
        boundary.update_configuration(patch)
    assert boundary.get_configuration() == before


@pytest.mark.parametrize('field,value', [('risk_per_trade_pct', '5.01'),
    ('total_exposure_pct', '500.01'), ('single_symbol_exposure_pct', '500.01'),
    ('maximum_leverage', '5.01')])
def test_model_cannot_bypass_absolute_limits(field, value):
    with pytest.raises(ValueError):
        replace(build_default_money_management_config(), **{field: D(value)})


def test_current_capital_elevated_one_contract_default_rejected():
    default = build_default_money_management_config()
    assert (default.risk_per_trade_pct, default.single_symbol_exposure_pct,
            default.total_exposure_pct, default.maximum_position_notional,
            default.maximum_leverage) == (D('0.5'), D('10'), D('20'), D('100'), D('5'))
    elevated = replace(default, risk_per_trade_pct=D('2.1'),
                       single_symbol_exposure_pct=D('180'), total_exposure_pct=D('180'))
    equity = D('7.91836966')
    def sizing(config):
        return OrderSizingAuthority(symbol='XRPUSDTM', price=D('1.39938'), equity=equity,
            available=equity, risk_percent=config.risk_per_trade_pct, sl_percent=D('1'),
            leverage=config.maximum_leverage, fixed_notional=D('0'),
            position_cap=config.maximum_position_notional,
            symbol_capacity=equity * config.single_symbol_exposure_pct / 100,
            total_capacity=equity * config.total_exposure_pct / 100,
            multiplier=D('10'), minimum=D('1'), step=D('1'), maximum=D('1000000'))
    result = sizing(elevated).size()
    assert result['contracts'] == '1'
    assert result['qty'] == 10
    assert result['position_size'] == 13.9938
    assert result['required_margin'] == 2.79876
    assert sizing(elevated).risk_budget == D('0.16628576286')
    with pytest.raises(SizingRejected, match='NO_VALID_QUANTITY_FOR_RISK_POLICY'):
        sizing(default).size()
    # Neither risk alone nor exposure alone may override the other constraint.
    for config in (replace(default, risk_per_trade_pct=D('2.1')),
                   replace(default, single_symbol_exposure_pct=D('180'), total_exposure_pct=D('180'))):
        with pytest.raises(SizingRejected):
            sizing(config).size()


def test_simulation_accepts_explicit_futures_configuration():
    from tests.test_money_management_simulation import simulation_input
    from backend.money_management.simulation import run_simulation
    value = simulation_input(risk_per_trade_percent=D('2.1'),
                             total_exposure_percent=D('180'), single_symbol_exposure_percent=D('180'))
    assert run_simulation(value) == run_simulation(value)
