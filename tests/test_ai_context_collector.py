"""Offline tests for the read-only context collector and sharing views.

These tests inject projections or call pure readers. They do not start the
bot, submit orders, or contact an exchange.
"""

from __future__ import annotations

import ast
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import socket

import pytest

from backend.context import (
    SCHEMA_VERSION,
    Availability,
    CanonicalContext,
    FieldObservation,
    Freshness,
    SafetyContext,
    ValueState,
    build_canonical_context,
    collect_runtime_context,
    collect_tradingai_context,
    compose_tradingai_context,
    to_canonical_json,
    view_to_json,
    view_to_markdown,
)
from backend.context.collector_contract import READER_FAILED, READER_NOT_INJECTED
from backend.context.context_views import (
    PUBLIC_CONTEXT,
    build_operator_context_view,
    build_public_context_view,
    scrub_context_tree,
)
from backend.context import runtime_truth
from backend.context.source_truth import read_source_truth
from backend.runtime.current_position_view import current_position
from backend.runtime.cycle_diagnostics import build_trading_cycle_diagnostics
from tests.test_ai_context_support import FIXED_NOW, make_supervisor_snapshot

REPO = Path(__file__).resolve().parents[1]
SECRET = "supersecretvalue-bb4a"
BALANCE = 424242.5


def _fields(section) -> dict[str, object]:
    return {item.name: item for item in section.fields}


def _paper_account(now: float):
    return {
        "available": True,
        "lastUpdate": now,
        "positionState": "OPEN",
        "unrealizedPnl": 1.25,
        "positions": [
            {
                "symbol": "XRPUSDTM",
                "side": "LONG",
                "qty": 1,
                "entry_price": 0.5,
                "entry_time": now - 30,
                "entry_authority": "MANUAL",
                "coin_qty": 10,
            }
        ],
    }


def _diagnostics(**overrides):
    decision = {"timestamp": "2026-10-25T00:00:00Z"}
    decision.update(overrides)
    return build_trading_cycle_diagnostics(
        decision,
        context={"status": "RUNNING", "timestamp": decision["timestamp"]},
        evaluated_at=decision["timestamp"],
    )


def _account_projection():
    return {
        "selectedMode": "PAPER",
        "paperAccount": {
            "balance": BALANCE,
            "equity": 100,
            "availableBalance": 80,
            "source": "PAPER",
            "lastUpdate": "2026-10-25T00:00:00Z",
            "freshness": "FRESH",
        },
        "realAccount": {
            "balance": 9,
            "source": "LIVE",
            "lastSync": "2026-10-25T00:00:00Z",
            "freshness": "FRESH",
        },
    }


def _bot_status():
    return {
        "selectedMode": "PAPER",
        "tradeMode": "PAPER",
        "realOrderAllowed": False,
        "botState": "STOPPED",
        "loopState": "IDLE",
        "currentPosition": {
            "status": "FLAT",
            "mode": "PAPER",
            "freshness": "UNKNOWN",
            "source": "RUNTIME_POSITION_READER",
        },
        "accountRuntime": {
            "mode": "PAPER",
            "balance": 3,
            "source": "PAPER",
        },
        "availableCapital": "10",
        "tradingCycleDiagnostics": {"provenance": "UNKNOWN", "steps": []},
    }


def test_01_schema_compatibility():
    collected = collect_runtime_context(generated_at=FIXED_NOW)
    assert collected.context.schemaVersion == SCHEMA_VERSION == "tradingai-context/v1"
    assert collected.context.safety == SafetyContext()
    assert collected.production_runtime_connected is False
    revalidated = CanonicalContext.model_validate(collected.context.model_dump())
    assert revalidated == collected.context
    assert collect_tradingai_context is collect_runtime_context


def test_02_composer_compatibility():
    status = _bot_status()
    direct = compose_tradingai_context(generated_at=FIXED_NOW, bot_status=status)
    collected = collect_runtime_context(generated_at=FIXED_NOW, bot_status=status)
    assert to_canonical_json(collected.context) == to_canonical_json(direct)


def test_03_supervisor_reader_injection():
    snapshot = make_supervisor_snapshot()
    calls = {"count": 0}

    def reader():
        calls["count"] += 1
        return snapshot

    collected = collect_runtime_context(
        generated_at=FIXED_NOW, supervisor_snapshot_reader=reader
    )
    assert calls["count"] == 1
    assert "supervisor_snapshot" in collected.connected_sources
    names = _fields(collected.context.runtime)
    assert "selectedMode" in names
    assert collected.context.runtime.meta.availability is not Availability.UNAVAILABLE


def test_04_position_reader_uses_current_position(monkeypatch):
    seen = {"called": False}
    real = runtime_truth.current_position

    def wrapped(*args, **kwargs):
        seen["called"] = True
        return real(*args, **kwargs)

    monkeypatch.setattr(runtime_truth, "current_position", wrapped)
    account = _paper_account(FIXED_NOW.timestamp())
    collected = collect_runtime_context(
        generated_at=FIXED_NOW,
        position_account=account,
        position_mode="PAPER",
        position_now=FIXED_NOW,
        position_symbol="XRPUSDTM",
    )
    assert seen["called"] is True
    fields = _fields(collected.context.position)
    assert fields["status"].value == "OPEN"
    assert fields["side"].value == "LONG"
    assert fields["mode"].value == "PAPER"
    assert fields["quantity"].value not in (0, None)

    def injected():
        return current_position(
            _paper_account(FIXED_NOW.timestamp()),
            "PAPER",
            now=FIXED_NOW.timestamp(),
            symbol="XRPUSDTM",
        )

    via_reader = collect_runtime_context(
        generated_at=FIXED_NOW, position_reader=injected
    )
    assert _fields(via_reader.context.position)["status"].value == "OPEN"
    assert "position" in via_reader.connected_sources


def test_05_account_reader_injection():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW, account_reader=_account_projection
    )
    fields = _fields(collected.context.account)
    assert fields["paperBalance"].value == BALANCE
    assert fields["liveBalance"].value == 9
    assert fields["currency"].state is ValueState.UNAVAILABLE
    assert "account" in collected.connected_sources


def test_06_mm_reader_injection():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW,
        mm_reader=lambda: {
            "availableCapital": "25",
            "riskBudget": "2",
            "riskPercent": 1,
            "trailing_stop_distance_percent": 0.4,
            "sourceUpdatedAt": "2026-10-25T00:00:00Z",
            "freshness": "FRESH",
        },
    )
    fields = _fields(collected.context.smallAccount)
    assert fields["availableCapital"].value == 25 or fields["availableCapital"].value == "25"
    assert fields["riskBudget"].state is ValueState.PRESENT
    assert fields["takeProfitPercent"].state is ValueState.UNAVAILABLE
    assert fields["timeExitSeconds"].state is ValueState.UNAVAILABLE
    assert fields["trailingPercent"].state is ValueState.UNAVAILABLE


def test_07_trading_cycle_reader_injection():
    diagnostics = _diagnostics()

    collected = collect_runtime_context(
        generated_at=FIXED_NOW, trading_cycle_reader=lambda: diagnostics
    )
    fields = _fields(collected.context.tradingCycle)
    assert fields["stepCount"].value == 15
    assert fields["step.10.status"].value == "UNKNOWN"
    assert fields["step.13.status"].value == "UNKNOWN"
    assert fields["step.10.status"].value != "PASS"


def test_08_execution_reader_injection():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW,
        execution_control_reader=lambda: {
            "selectedMode": "PAPER",
            "tradeMode": "LIVE",
            "controlAuthority": "BOT",
            "entryAuthority": "MANUAL",
            "botState": "RUNNING",
            "loopState": "RUNNING",
            "sourceEvaluatedAt": "2026-10-25T00:00:00Z",
        },
    )
    fields = _fields(collected.context.executionControl)
    assert fields["controlAuthority"].value == "BOT"
    assert fields["entryAuthority"].value == "MANUAL"
    assert fields["modeMismatch"].value == "TRUE"
    assert fields["realOrderAllowed"].value is False
    assert fields["realOrderAllowed"].state is ValueState.UNKNOWN
    assert fields["realOrderAllowedEvidence"].value == "FAIL_CLOSED"


def test_09_all_readers_unavailable():
    collected = collect_runtime_context(generated_at=FIXED_NOW)
    assert collected.connected_sources == ()
    assert collected.production_runtime_connected is False
    assert {item.source for item in collected.failures} == {
        "supervisor_snapshot",
        "position",
        "account",
        "mm",
        "trading_cycle",
        "execution_control",
    }
    assert {item.category for item in collected.failures} == {READER_NOT_INJECTED}
    assert collected.context.position.meta.availability is Availability.UNAVAILABLE
    assert collected.context.account.meta.availability is Availability.UNAVAILABLE


def test_10_partial_reader_failure():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW,
        position_reader=lambda: {
            "status": "FLAT",
            "mode": "PAPER",
            "freshness": "UNKNOWN",
            "source": "RUNTIME_POSITION_READER",
        },
        account_reader=lambda: (_ for _ in ()).throw(RuntimeError("account down")),
        mm_reader=lambda: {"availableCapital": "5", "freshness": "UNKNOWN"},
    )
    assert _fields(collected.context.position)["status"].value == "FLAT"
    assert "position" in collected.connected_sources
    assert "mm" in collected.connected_sources
    assert "account" not in collected.connected_sources
    account_failure = next(item for item in collected.failures if item.source == "account")
    assert account_failure.category == READER_FAILED
    assert account_failure.observedAt is None
    assert _fields(collected.context.account)["balance"].value in (None,)
    assert _fields(collected.context.account)["balance"].state is not ValueState.PRESENT


def test_11_reader_exception_sanitization():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW,
        account_reader=lambda: (_ for _ in ()).throw(
            RuntimeError(f"API_KEY={SECRET} password={SECRET}")
        ),
    )
    rendered = "\n".join(
        [
            to_canonical_json(collected.context),
            view_to_json(collected.public_view),
            view_to_json(collected.operator_view),
            repr(collected.failures),
        ]
    )
    assert SECRET not in rendered
    assert "API_KEY" not in repr(collected.failures)
    assert "Traceback" not in rendered


def test_12_no_exchange_or_network_call(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("network socket opened")

    monkeypatch.setattr(socket, "socket", boom)
    collect_runtime_context(
        generated_at=FIXED_NOW,
        position_account=_paper_account(FIXED_NOW.timestamp()),
        position_mode="PAPER",
        position_now=FIXED_NOW,
        position_symbol="XRPUSDTM",
    )


def test_13_no_trading_mutation():
    source = (REPO / "backend/context/runtime_collector.py").read_text(encoding="utf-8")
    views = (REPO / "backend/context/context_views.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    banned = ("bot_manager", "requests", "websocket", "aiohttp", "kucoin", "backend.api")
    for name in imported:
        assert not any(part in name for part in banned)
    for token in ("get_bot_manager", "get_status", "get_result", "datetime.now(", "place_order"):
        assert token not in source
        assert token not in views
    status = _bot_status()
    before = deepcopy(status)
    collect_runtime_context(generated_at=FIXED_NOW, bot_status=status)
    assert status == before


def test_14_no_bot_start_or_stop():
    source = (REPO / "backend/context/runtime_collector.py").read_text(encoding="utf-8")
    assert "start_bot" not in source
    assert "stop_bot" not in source
    assert ".start(" not in source
    assert ".stop(" not in source


def test_15_no_emergency_mutation():
    source = (REPO / "backend/context/runtime_collector.py").read_text(encoding="utf-8")
    assert "trigger_emergency" not in source
    assert "clear_emergency" not in source
    assert "set_emergency" not in source


def test_16_paper_live_separation():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW, account_projection=_account_projection()
    )
    fields = _fields(collected.context.account)
    assert fields["paperBalance"].value == BALANCE
    assert fields["liveBalance"].value == 9
    assert fields["paperBalance"].value != fields["liveBalance"].value
    assert fields["mode"].value == "PAPER"


def test_17_bot_manual_separation():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW,
        execution_projection={
            "selectedMode": "LIVE",
            "tradeMode": "LIVE",
            "controlAuthority": "BOT",
            "entryAuthority": "MANUAL",
            "realOrderAllowed": False,
        },
    )
    fields = _fields(collected.context.executionControl)
    assert fields["controlAuthority"].value == "BOT"
    assert fields["entryAuthority"].value == "MANUAL"
    assert fields["selectedMode"].value == "LIVE"


def test_18_real_order_allowed_fail_closed():
    missing = collect_runtime_context(
        generated_at=FIXED_NOW,
        execution_projection={"selectedMode": "LIVE", "tradeMode": "LIVE"},
    )
    fields = _fields(missing.context.executionControl)
    assert fields["realOrderAllowed"].value is False
    assert fields["realOrderAllowed"].state is ValueState.UNKNOWN
    explicit = collect_runtime_context(
        generated_at=FIXED_NOW,
        execution_projection={"realOrderAllowed": True, "selectedMode": "LIVE"},
    )
    allowed = _fields(explicit.context.executionControl)["realOrderAllowed"]
    assert allowed.value is True
    assert allowed.state is ValueState.PRESENT


def test_19_trading_cycle_unknown_is_not_current():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW, trading_cycle_projection=_diagnostics()
    )
    fields = _fields(collected.context.tradingCycle)
    assert fields["diagnosticScope"].value == "UNKNOWN"
    assert fields["diagnosticScope"].value != "CURRENT"
    assert collected.context.tradingCycle.meta.freshness is not Freshness.FRESH


def test_20_trading_cycle_historical():
    diagnostics = _diagnostics()
    diagnostics["diagnosticsGeneratedAt"] = "2026-10-20T00:00:00Z"
    diagnostics["evaluatedAt"] = "2026-10-20T00:00:00Z"
    diagnostics["evaluationProvenance"] = {"provenance": "HISTORICAL"}
    later = FIXED_NOW + timedelta(days=1)
    collected = collect_runtime_context(
        generated_at=later, trading_cycle_projection=diagnostics
    )
    fields = _fields(collected.context.tradingCycle)
    assert fields["diagnosticScope"].value == "HISTORICAL"
    assert fields["diagnosticScope"].value != "CURRENT"
    assert collected.context.tradingCycle.meta.freshness is Freshness.STALE
    assert collected.context.freshness.evaluatedAt == later


def test_21_freshness_provenance():
    diagnostics = _diagnostics()
    diagnostics["diagnosticsGeneratedAt"] = "2026-10-20T00:00:00Z"
    diagnostics["evaluationProvenance"] = {"provenance": "HISTORICAL"}
    later = FIXED_NOW + timedelta(hours=5)
    collected = collect_runtime_context(
        generated_at=later, trading_cycle_projection=diagnostics
    )
    observed = collected.context.tradingCycle.meta.observedAt
    assert observed is not None
    assert observed != later
    assert collected.context.freshness.evaluatedAt == later
    note = collected.operator_view["timeSemantics"]["freshnessEvaluatedAt"]
    assert "not a runtime observation" in note
    assert collected.public_view["timeSemantics"]["freshnessEvaluatedAt"] == note


def test_22_public_excludes_account():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW, account_projection=_account_projection()
    )
    public = view_to_json(collected.public_view)
    assert "424242.5" not in public
    assert "paperBalance" not in public
    assert "liveBalance" not in public
    operator = view_to_json(collected.operator_view)
    assert "424242.5" in operator


def test_23_public_excludes_position():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW,
        position_account=_paper_account(FIXED_NOW.timestamp()),
        position_mode="PAPER",
        position_now=FIXED_NOW,
        position_symbol="XRPUSDTM",
    )
    public = view_to_json(collected.public_view)
    assert "XRPUSDTM" not in public
    assert "avgEntry" not in public
    operator = view_to_json(collected.operator_view)
    assert "XRPUSDTM" in operator


def test_24_public_excludes_internal_paths():
    source = read_source_truth(REPO, observed_at=FIXED_NOW)
    collected = collect_runtime_context(generated_at=FIXED_NOW, source_truth=source)
    raw_path = str(REPO)
    public = view_to_json(collected.public_view)
    operator = view_to_json(collected.operator_view)
    assert raw_path not in public
    assert raw_path not in operator
    assert "/home/" not in public
    assert collected.public_view["source"]["deployedCommitState"] == "UNKNOWN"
    assert "repository" not in collected.public_view["source"]
    assert "worktrees" not in collected.operator_view["source"]


def test_25_public_excludes_authority():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW,
        execution_projection={
            "selectedMode": "LIVE",
            "controlAuthority": "BOT",
            "entryAuthority": "MANUAL",
            "emergencyState": "ARMED",
            "realOrderAllowed": False,
        },
    )
    public = view_to_json(collected.public_view)
    for token in ("controlAuthority", "entryAuthority", "realOrderAllowed"):
        assert token not in public
    assert '"emergencyState"' not in public
    operator = view_to_json(collected.operator_view)
    assert "controlAuthority" in operator
    assert "BOT" in operator


def test_26_operator_includes_allowed_runtime():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW,
        account_projection=_account_projection(),
        execution_projection={"botState": "RUNNING", "loopState": "RUNNING"},
    )
    sections = collected.operator_view["sections"]
    account_names = {item["name"] for item in sections["account"]["fields"]}
    execution_names = {item["name"] for item in sections["executionControl"]["fields"]}
    assert "paperBalance" in account_names
    assert "botState" in execution_names
    assert collected.operator_view["authentication"] == "NOT_ASSERTED"
    assert collected.public_view["authentication"] == "NOT_ASSERTED"
    assert collected.public_view["view"] == PUBLIC_CONTEXT


def test_27_operator_excludes_credentials():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW,
        account_reader=lambda: {
            "mode": "PAPER",
            "balance": 12,
            "apiKey": SECRET,
            "password": SECRET,
            "source": "PAPER",
        },
    )
    rendered = view_to_json(collected.operator_view) + view_to_json(collected.public_view)
    assert SECRET not in rendered
    assert "apiKey" not in rendered


def test_28_nested_secret_exclusion():
    cleaned = scrub_context_tree(
        {
            "status": "OPEN",
            "apiKey": SECRET,
            "child": {
                "token": SECRET,
                "side": "LONG",
                "comment": f"Bearer {SECRET}",
                "nested": {"password": SECRET, "mode": "PAPER"},
            },
        }
    )
    rendered = view_to_json(cleaned)
    assert SECRET not in rendered
    assert "apiKey" not in cleaned
    assert "token" not in cleaned["child"]
    assert "password" not in cleaned["child"]["nested"]
    assert cleaned["child"]["side"] == "LONG"
    assert cleaned["child"]["nested"]["mode"] == "PAPER"
    assert "Bearer" not in rendered


def test_29_unknown_fields_denied():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW,
        position_view={
            "status": "FLAT",
            "mode": "PAPER",
            "freshness": "UNKNOWN",
            "source": "RUNTIME_POSITION_READER",
        },
    )
    extra = FieldObservation(
        name="futureMetric",
        value="998877",
        state=ValueState.PRESENT,
        freshness=Freshness.UNKNOWN,
    )
    secret_field = FieldObservation(
        name="apiKey",
        value=SECRET,
        state=ValueState.PRESENT,
        freshness=Freshness.UNKNOWN,
    )
    position = collected.context.position.model_copy(
        update={"fields": collected.context.position.fields + (extra, secret_field)}
    )
    context = collected.context.model_copy(update={"position": position})
    operator = build_operator_context_view(context)
    public = build_public_context_view(context)
    rendered = view_to_json(operator) + view_to_json(public)
    assert "futureMetric" not in rendered
    assert "998877" not in rendered
    assert SECRET not in rendered
    assert "apiKey" not in rendered


def test_30_deterministic_json_and_markdown():
    kwargs = {
        "generated_at": FIXED_NOW,
        "account_projection": _account_projection(),
        "execution_projection": {"selectedMode": "PAPER", "realOrderAllowed": False},
    }
    first = collect_runtime_context(**kwargs)
    second = collect_runtime_context(**kwargs)
    assert view_to_json(first.public_view) == view_to_json(second.public_view)
    assert view_to_json(first.operator_view) == view_to_json(second.operator_view)
    markdown = view_to_markdown(first.public_view)
    assert markdown == view_to_markdown(second.public_view)
    assert "schemaVersion" in markdown
    assert "PUBLIC_CONTEXT" in markdown
    assert "424242.5" not in markdown
    operator_markdown = view_to_markdown(first.operator_view)
    assert "paperBalance" in operator_markdown
    assert "424242.5" in operator_markdown


def test_31_payload_and_collection_bounds():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW,
        account_projection=_account_projection(),
        max_bytes=96,
    )
    for view in (collected.public_view, collected.operator_view):
        assert view["availability"] == "UNAVAILABLE"
        assert view["reason"] == "PAYLOAD_LIMIT_EXCEEDED"
        assert view["actualBytes"] > view["limitBytes"]
        rendered = view_to_json(view)
        assert "424242.5" not in rendered
        assert "XRPUSDTM" not in rendered
    limited = scrub_context_tree({"note": "x" * 50}, max_string=8)
    assert limited["note"]["reason"] == "STRING_LIMIT_EXCEEDED"
    assert "xxxx" not in view_to_json(limited)
    listed = scrub_context_tree({"items": list(range(30))}, max_list=3)
    assert listed["items"]["reason"] == "LIST_LIMIT_EXCEEDED"
    assert "29" not in view_to_json(listed["items"])


def test_32_bb2_bb3_regression_entry_points():
    snapshot = make_supervisor_snapshot()
    built = build_canonical_context(
        generated_at=FIXED_NOW,
        runtime_truth=None,
    )
    assert built.schemaVersion == SCHEMA_VERSION
    composed = compose_tradingai_context(
        generated_at=FIXED_NOW, supervisor_snapshot=snapshot
    )
    assert composed.safety.orderWrite is False
    assert composed.safety.liveOrder is False
    assert composed.safety.secretsIncluded is False
    collected = collect_runtime_context(
        generated_at=FIXED_NOW, supervisor_snapshot=snapshot
    )
    direct = compose_tradingai_context(
        generated_at=FIXED_NOW, supervisor_snapshot=snapshot
    )
    assert to_canonical_json(collected.context) == to_canonical_json(direct)


def test_reader_is_not_called_when_uninjected(monkeypatch):
    def boom():
        raise AssertionError("reader called")

    monkeypatch.setattr(runtime_truth, "current_position", boom)
    collected = collect_runtime_context(generated_at=FIXED_NOW)
    assert collected.connected_sources == ()
    with pytest.raises(AssertionError):
        boom()
