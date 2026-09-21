"""Read-only Trade History contracts, isolated from production persistence."""
from datetime import datetime, timezone
import hashlib
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.api.trade_history import router
from backend.runtime.parameter_performance import ParameterPerformanceStore, normalize_control_source
from backend.runtime.parameter_performance_read import ParameterPerformanceReadService
from backend.runtime.trade_history_read import TradeHistoryService, classify_result

NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc).timestamp()


def record(i=1, **values):
    return dict({
        "schemaVersion": 1, "recordId": f"record-{i}", "tradeId": f"trade-{i}",
        "origin": "PRODUCTION", "scope": "PAPER", "mode": "paper", "symbol": "XRPUSDT",
        "side": "BUY", "effectiveRevision": 3, "controlSource": "BOT",
        "entryTimestamp": NOW - 10000000, "exitTimestamp": NOW - 60,
        "holdingMs": 1000, "realizedPnl": 1, "exitReason": "MANUAL_CLOSE",
        "entryPrice": 1, "exitPrice": 2, "quantity": 1,
    }, **values)


@pytest.fixture
def service(tmp_path):
    return TradeHistoryService(base_directory=tmp_path, now=lambda: NOW)


def seed(service, *rows):
    for row in rows:
        assert service.store.append(row)


def ids(payload):
    return {r["tradeId"] for r in payload["records"]}


def test_provenance_modes_unknown_revision_and_exact_identity(service, tmp_path):
    seed(service, record(1, tradeId="test-looking-name"), record(2, scope="LIVE", mode="live"),
         record(3, origin="NON_PRODUCTION"), record(4, origin=None, effectiveRevision=None),
         record(5, effectiveRevision=None), record(6, origin="NON_PRODUCTION", tradeId="production-looking"))
    assert ids(service.history()) == {"test-looking-name", "trade-2", "trade-5"}
    pp = ParameterPerformanceReadService(base_directory=tmp_path)
    assert ids(service.history(scope="PAPER", revision=3)) == ids(pp.performance(scope="PAPER", revision=3)) == {"test-looking-name"}
    assert service.history(scope="PAPER", revision=4)["records"] == []
    assert pp.performance(scope="PAPER", revision=4)["records"] == []
    assert service.detail("record-3") is None


@pytest.mark.parametrize("pnl,result", [(1,"WIN"),(-1,"LOSS"),(0,"BREAKEVEN"),(None,"UNKNOWN"),(True,"UNKNOWN"),(float('nan'),"UNKNOWN")])
def test_result_only_uses_pnl(pnl, result):
    assert classify_result(pnl) == result


@pytest.mark.parametrize("source,expected", [("BOT","BOT"),("MANUAL","MANUAL"),("UNKNOWN","UNKNOWN"),(None,"UNKNOWN")])
def test_control_source(service, source, expected):
    seed(service, record(controlSource=source))
    assert service.history(control_source=expected)["records"][0]["controlSource"] == expected
    assert normalize_control_source({"entry_authority": source}) == expected


@pytest.mark.parametrize("period,days", [("today",0.5),("7d",7),("30d",30),("90d",90)])
def test_period_uses_exit_time(service, period, days):
    seed(service, record(1, exitTimestamp=NOW-60), record(2, exitTimestamp=NOW-days*86400-1), record(3, exitTimestamp=NOW+1))
    assert ids(service.history(period=period)) == {"trade-1"}
    assert service.history(period=period)["periodTimeAuthority"] == "EXIT_TIME"


def test_all_custom_periods(service):
    seed(service, record(1, exitTimestamp=10), record(2, exitTimestamp=20))
    assert len(service.history(period="all")["records"]) == 2
    assert ids(service.history(period="custom",from_timestamp=10,to_timestamp=10)) == {"trade-1"}
    with pytest.raises(ValueError): service.history(period="custom",from_timestamp=20,to_timestamp=10)
    with pytest.raises(ValueError): service.history(period="custom")


@pytest.mark.parametrize("query", [dict(mode="live"),dict(symbol="BTCUSDT"),dict(side="SELL"),dict(result="LOSS"),dict(revision=8),dict(exit_reason="STOP_LOSS"),dict(control_source="MANUAL")])
def test_filters(service, query):
    seed(service, record(1), record(2,scope="LIVE",mode="live",symbol="BTCUSDT",side="SELL",realizedPnl=-1,effectiveRevision=8,exitReason="STOP_LOSS",controlSource="MANUAL"))
    assert ids(service.history(**query)) == {"trade-2"}
    assert service.history(**query)["metrics"]["tradeCount"] == 1


@pytest.mark.parametrize("sort", ["entryTimestamp","exitTimestamp","realizedPnl","holdingMs","symbol","effectiveRevision"])
def test_sort_pagination_summary(service, sort):
    a,b=("AAA","BBB") if sort=="symbol" else (1,2)
    seed(service, record(1,**{sort:a}), record(2,**{sort:b}))
    result=service.history(sort=sort,direction="asc",page_size=1)
    assert ids(result)=={"trade-1"}
    assert result["metrics"]["tradeCount"]==2
    assert result["pagination"]["hasNext"] is True
    assert ids(service.history(sort=sort,direction="asc",page_size=1,page=2))=={"trade-2"}
    assert ids(service.history(sort=sort,direction="desc",page_size=1))=={"trade-2"}


def test_api_read_only_contract_and_store_unchanged(service):
    seed(service,record())
    before=hashlib.sha256(service.store.path.read_bytes()).hexdigest()
    app=FastAPI(); app.state.trade_history_service=service; app.include_router(router)
    client=TestClient(app)
    response=client.get('/api/trade-history?scope=PAPER&revision=3&period=all')
    assert response.status_code==200
    body=response.json()
    assert {'symbol','revision','exitReason'} <= body['options'].keys()
    assert body['records'][0]['entryPrice']==1
    assert body['records'][0]['exitPrice']==2
    assert body['records'][0]['quantity']==1
    assert client.get('/api/trade-history/detail?recordId=record-1').json()['tradeId']=='trade-1'
    assert client.get('/api/trade-history/detail?recordId=missing').status_code==404
    assert client.get('/api/trade-history?mode=invalid').status_code==422
    assert client.get('/api/trade-history?period=custom').status_code==422
    assert client.post('/api/trade-history').status_code==405
    assert all(route.methods=={'GET'} for route in router.routes)
    assert hashlib.sha256(service.store.path.read_bytes()).hexdigest()==before


def test_engine_metadata_never_assumes_bot():
    from Bot.engine.execution_engine import ExecutionEngine
    for source in ('BOT','MANUAL',None,'invalid'):
        # This attachment method changes metadata only, and cannot place orders.
        engine=ExecutionEngine.__new__(ExecutionEngine)
        result=engine._attach_position_parameter_context({}, {'entry_authority':source})
        assert result['controlSource']==(source if source in ('BOT','MANUAL') else 'UNKNOWN')


@pytest.mark.parametrize("origin", ["TEST", "UNKNOWN", "", "NON_PRODUCTION", None])
def test_explicit_nonproduction_or_unknown_origin_never_uses_legacy_revision(service, origin):
    seed(service, record(origin=origin))
    assert service.history()["records"] == []
    assert service.detail("record-1") is None


def test_shared_canonical_legacy_r3_rule_is_preserved(service, tmp_path):
    row = record(); row.pop("origin")
    seed(service, row, record(2, origin=None, effectiveRevision=None))
    pp = ParameterPerformanceReadService(base_directory=tmp_path)
    assert ids(service.history(scope="PAPER", revision=3)) == ids(pp.performance(scope="PAPER", revision=3)) == {"trade-1"}


def test_out_of_range_page_is_bounded(service):
    seed(service, record())
    result = service.history(page=999)
    assert result["pagination"]["page"] == 1
    assert ids(result) == {"trade-1"}


def test_nonfinite_pnl_is_unavailable_not_breakeven(service):
    seed(service, record(realizedPnl=float("nan")))
    result = service.history()
    assert result["records"][0]["result"] == "UNKNOWN"
    assert result["records"][0]["realizedPnl"] is None
    assert result["metrics"]["breakevenCount"] == 0
    assert result["metrics"]["realizedPnl"] is None
