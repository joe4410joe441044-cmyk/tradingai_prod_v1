"""Offline risk/MM/exchange sizing regression; network is forbidden."""
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import Mock
import time
import pytest
from backend.money_management.order_sizing import OrderSizingAuthority, SizingRejected, floor_contracts
from backend.money_management.loss_application_registration import build_default_money_management_config
from backend.money_management.live_capital_authority import build_live_capital_eligibility
from backend.portfolio.portfolio_manager import PortfolioManager
from backend.execution.kucoin_trade import KucoinTradeClient
from Bot.engine.execution_engine import ExecutionEngine
from sizing_support import account, contract_rules, install_sizing
from datetime import datetime, timezone


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr('requests.sessions.Session.request', Mock(side_effect=AssertionError('REAL_NETWORK_FORBIDDEN')))


def authority(**kwargs):
    fields=dict(symbol='XRPUSDTM', price='1.5205', equity='1000', available='1000',
                risk_percent='0.5', sl_percent='1', leverage='5', fixed_notional='0',
                position_cap='1000', symbol_capacity='1000', total_capacity='1000',
                multiplier='10', minimum='1', step='1', maximum='1000000')
    fields.update(kwargs)
    return OrderSizingAuthority(**fields)


def test_low_balance_is_expected_fail_closed_pass():
    with pytest.raises(SizingRejected, match='NO_VALID_QUANTITY_FOR_RISK_POLICY'):
        authority(equity='7.91836966', available='7.91836966').size()


def test_stop_distance_and_leverage_are_separate():
    a=authority(price='10', multiplier='1')
    assert a.size()['position_size'] == 500
    assert replace(a, sl_percent=D('2')).size()['position_size'] == 250
    for leverage in (1,3,5):
        result=replace(a, leverage=D(leverage)).size()
        assert result['position_size'] == 500
        assert result['required_margin'] == pytest.approx(500/leverage)


def test_fixed_and_cap_are_independent():
    a=authority(fixed_notional='100')
    assert a.size()['sizing_mode']=='fixed_position_size'
    assert a.size()['position_size']<=100
    assert replace(a,fixed_notional=D('0')).size()['position_size']>100
    with pytest.raises(SizingRejected,match='MM_EXPOSURE'):
        replace(a,position_cap=D('50')).size()


@pytest.mark.parametrize('change,reason', [({'available':'1','fixed_notional':'100'},'AVAILABLE_MARGIN'),
    ({'total_capacity':'10','fixed_notional':'100'},'MM_EXPOSURE'),
    ({'symbol_capacity':'10','fixed_notional':'100'},'MM_EXPOSURE'),
    ({'equity':'10','fixed_notional':'100'},'RISK_POLICY')])
def test_fixed_limit_violations_fail_closed(change,reason):
    with pytest.raises(SizingRejected,match=reason): authority(**change).size()


def test_rounding_cannot_increase_and_minimum_cannot_override():
    for raw in ('0.9','1.5','1.9','2.5','3.99'):
        assert floor_contracts(raw,1)<=D(raw)
    with pytest.raises(SizingRejected): authority(step='100').size()
    with pytest.raises(SizingRejected,match='EXCEEDS_APPROVAL'):
        authority().validate(2,approved_base='15')


def engine_for(mode='paper',equity=1000):
    exchange=Mock() if mode=='live' else None
    engine=ExecutionEngine(exchange=exchange,portfolio=PortfolioManager(equity),
                           price_manager=SimpleNamespace(get_current_price=lambda:1.5205))
    engine.symbol='XRPUSDTM'
    engine.mode=mode
    engine.set_config(dict(mode=mode,position_size=0,risk_percent=.5,sl_percent=1,leverage=5,effective_leverage=5))
    engine.mode=mode
    install_sizing(engine)
    engine.sizing_contract_provider=lambda symbol: contract_rules(symbol,10)
    if exchange is not None:
        exchange.get_account_overview.return_value=account(equity)
        exchange.get_symbol_rules.return_value=contract_rules(engine.symbol,10)
    return engine


def test_live_uses_equity_not_reference_and_paper_uses_paper_capital():
    live=engine_for('live',7.91836966)
    assert live.sizing_policy_provider().initial_reference_equity==1000
    assert live.get_result()['preview']['reason']=='NO_VALID_QUANTITY_FOR_RISK_POLICY'
    paper=engine_for('paper',2000)
    assert paper._order_sizing_authority(price=1.5205).risk_budget==10
    assert live._order_sizing_authority(price=1.5205).risk_budget==D('0.03959184830')


def test_live_capital_eligibility_separates_reference_capital():
    now=datetime.now(timezone.utc)
    snapshot=SimpleNamespace(source_authority='REAL_LIVE_ACCOUNT',authority_fresh=True,
        open_position_state='FLAT',pending_order_state='NONE',available_capital=D('7.91836966'),
        equity=D('7.91836966'),evaluated_at=now)
    config=build_default_money_management_config()
    result=build_live_capital_eligibility(snapshot,config=config,policy_version='test')
    assert result.capital_basis==snapshot.equity
    assert result.risk_budget==D('0.03959184830')
    assert config.initial_reference_equity==1000


@pytest.mark.parametrize('field,value', [('lastSync',0),('availableBalance',None),('positionMargin',1),('orderMargin',1),('source','PAPER')])
def test_live_account_constraints_fail_closed(field,value):
    engine=engine_for('live')
    engine.exchange.get_account_overview.return_value[field]=value
    assert engine.get_result()['preview']['valid'] is False


def test_final_quantity_rechecks_fresh_capital_policy_and_mm():
    engine=engine_for('live')
    engine._evaluate_execution_entry_guard=Mock(return_value=(True,None))
    values=dict(symbol='XRPUSDTM',contracts=1,price=1.5205,rules=contract_rules('XRPUSDTM',10),
                leverage=5,approved_base=10,side='BUY',trace_id='test')
    assert engine._validate_final_entry_quantity(**values) is True
    engine.exchange.get_account_overview.return_value=account(7.91836966)
    with pytest.raises(SizingRejected):engine._validate_final_entry_quantity(**values)
    engine.exchange.get_account_overview.return_value=account()
    engine._evaluate_execution_entry_guard.return_value=(False,None)
    with pytest.raises(SizingRejected,match='MM_REJECTED'):engine._validate_final_entry_quantity(**values)


def test_adapter_exact_wire_quantity_and_missing_validator():
    client=KucoinTradeClient(api_key='fake',api_secret='fake',passphrase='fake')
    client.set_live_order_gate(True,[])
    client.get_symbol_rules=lambda symbol:contract_rules(symbol,10)
    client.get_price=lambda symbol:1.5205
    client.session.post=Mock(return_value=SimpleNamespace(json=lambda:{'code':'200000','data':{'orderId':'mock'}}))
    assert client.create_order('XRPUSDTM','BUY',19,leverage=5)['success'] is False
    client.session.post.assert_not_called()
    observed=[]
    def validate(**kwargs):
        observed.append(kwargs['contracts'])
        authority().validate(kwargs['contracts'],approved_base=19)
        return True
    assert client.create_order('XRPUSDTM','BUY',19,leverage=5,sizing_validator=validate)['success'] is True
    import json
    assert observed==[1]
    assert json.loads(client.session.post.call_args.kwargs['data'])['size']=='1'
    client.session.post.reset_mock()
    assert client.create_order('XRPUSDTM','BUY',9.9,leverage=5,sizing_validator=validate)['success'] is False
    client.session.post.assert_not_called()


@pytest.mark.parametrize('change', [dict(symbol='ETHUSDTM'),dict(leverage=3),
    dict(contracts=2),dict(price=100),dict(rules={**contract_rules('XRPUSDTM',10),'status':'Closed'})])
def test_final_context_changes_are_rejected(change):
    engine=engine_for('live')
    engine._evaluate_execution_entry_guard=Mock(return_value=(True,None))
    values=dict(symbol='XRPUSDTM',contracts=1,price=1.5205,rules=contract_rules('XRPUSDTM',10),
                leverage=5,approved_base=10,side='BUY',trace_id='test')
    values.update(change)
    with pytest.raises(SizingRejected):engine._validate_final_entry_quantity(**values)


def test_missing_mm_and_paper_contract_authority_fail_closed():
    engine=engine_for()
    engine.sizing_policy_provider=None
    assert engine.get_result()['preview']['reason']=='SIZING_MM_POLICY_UNAVAILABLE'
    engine.sizing_policy_provider=build_default_money_management_config
    engine.sizing_contract_provider=None
    assert engine.get_result()['preview']['valid'] is False


def test_minimum_is_not_raised_even_when_margin_is_sufficient():
    a=authority(equity='7.91836966',available='7.91836966')
    assert a.minimum*a.multiplier*a.price/a.leverage < a.available*D('.8')
    with pytest.raises(SizingRejected,match='RISK_POLICY'):a.size()


def test_actual_manual_engine_to_adapter_revalidates_wire_quantity(monkeypatch):
    from test_manual_trade_live_contract import _build_live_manager, _trade
    from backend import config
    from backend.runtime.governance_runtime import governance_state, EMERGENCY_READY
    from unittest.mock import patch
    client=KucoinTradeClient(api_key='fake',api_secret='fake',passphrase='fake')
    client.get_price=lambda symbol:100
    client.get_balance=lambda:1000
    client.get_positions=lambda symbol:dict(symbol='XRPUSDTM',qty=1000,side='BUY',entry_price=100)
    captured=[]
    def post(url,**kwargs):
        import json
        captured.append(json.loads(kwargs['data']))
        return SimpleNamespace(json=lambda:{'code':'200000','data':{'orderId':'mock'}})
    client.session.post=post
    with patch.dict(governance_state,dict(execution_enabled=False,emergency_stop=False,
                                         emergency_state=EMERGENCY_READY,control_authority='BOT',control_revision=0)), \
         patch.object(config,'ALLOW_LIVE',True),patch.object(config,'TRADE_MODE','live'):
        manager,engine,_,recorder=_build_live_manager(client)
        result=_trade(manager,'BUY','sizing-wire')
        assert result['success'] is True
        assert len(captured)==1
        assert captured[0]['size']=='1000'
        assert len(recorder.intents)==2  # admission and final normalized quantity
        assert all(intent.requested_quantity==D('1') for intent in recorder.intents)
