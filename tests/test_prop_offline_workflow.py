from __future__ import annotations

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import socket
import threading
import time

import pytest

from backend.prop_trading.offline_server import BODY_READ_TIMEOUT_SECONDS, MAX_BODY_BYTES, create_server
from backend.prop_trading.offline_workflow import OfflinePropSession, OfflineWorkflowError


NOW = datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)


def account_request(**changes):
    data = {"requestId": "account-1", "label": "Synthetic Challenge", "phase": "CHALLENGE", "currency": "USDT"}
    data.update(changes)
    return data


def evaluation_request(account, **observation_changes):
    observation = {
        "balance": "101000.000000000000000001",
        "equity": "100500.000000000000000001",
        "realizedPnl": "1000.000000000000000001",
        "unrealizedPnl": "-500.000000000000000000",
        "observedAt": "2026-11-04T02:00:00Z",
        "receivedAt": "2026-11-04T02:00:01Z",
    }
    observation.update(observation_changes)
    return {
        "requestId": "evaluation-1",
        "accountId": account["identity"]["account_id"],
        "identityRevision": account["identity"]["revision"],
        "rules": {
            "initialBalance": "100000.000000000000000001",
            "maximumLossPct": "6.000000000000000001",
            "dailyLossPct": "4.000000000000000001",
            "profitTargetPct": "10.000000000000000001",
        },
        "baseline": {
            "referenceValue": "100000.000000000000000001",
            "tradingDay": "2026-11-04",
            "timezone": "UTC",
            "dayBoundaryLocalTime": "00:00:00",
        },
        "observation": observation,
        "evaluation": {"evaluatedAt": "2026-11-04T02:00:02Z"},
    }


@pytest.fixture
def session():
    return OfflinePropSession(clock=lambda: NOW)


def test_account_creation_is_existing_contract_synthetic_scope(session):
    account = session.create_account(account_request())["account"]
    identity = account["identity"]
    assert identity["account_id"].startswith("acc_")
    assert identity["account_type"] == "PROP"
    assert identity["execution_mode"] == "EXTERNAL_SIMULATION"
    assert identity["execution_venue"] == "BYBIT_DEMO"
    assert identity["prop_program"] == "HYROTRADER"
    assert account["synthetic"] is True and account["persisted"] is False


def test_revision_preserves_id_and_invalidates_old_revision(session):
    account = session.create_account(account_request())["account"]
    revised = session.revise_account({
        "requestId": "revision-1", "accountId": account["identity"]["account_id"],
        "identityRevision": 1, "label": "Revised", "phase": "VERIFICATION", "currency": "USDT",
    })["account"]
    assert revised["identity"]["account_id"] == account["identity"]["account_id"]
    assert revised["identity"]["revision"] == 2
    with pytest.raises(OfflineWorkflowError, match="revision"):
        session.evaluate(evaluation_request(account))


def test_pass_uses_wrapper_projection_and_preserves_decimal_strings(session):
    account = session.create_account(account_request())["account"]
    response = session.evaluate(evaluation_request(account))
    outcome = response["outcome"]
    assert outcome["calculation"]["overallState"] == "PASS"
    assert outcome["synthetic"] is True
    assert outcome["accountScope"]["currency"] == "USDT"
    assert outcome["calculation"]["ruleResults"][0]["threshold"] is not None
    assert response["authority"] == {
        "executionAuthorityGranted": False, "runtimeReady": False, "tradeReady": False,
    }
    assert outcome["authority"]["executionAuthorityGranted"] is False


def test_block_and_unknown_are_engine_results_not_frontend_calculation(session):
    account = session.create_account(account_request())["account"]
    blocked = session.evaluate(evaluation_request(account, equity="93000"))["outcome"]
    assert blocked["calculation"]["overallState"] == "BLOCK"
    assert "STATIC_MAXIMUM_LOSS" in blocked["calculation"]["blockingRuleCodes"]
    unknown = session.evaluate(evaluation_request(account, balance=None, equity=None))["outcome"]
    assert unknown["calculation"]["overallState"] == "UNKNOWN"
    assert unknown["calculation"]["unknownRuleCodes"]


@pytest.mark.parametrize("bad", ["NaN", "Infinity", " 1", 1, ""])
def test_decimal_parser_rejects_non_finite_ambiguous_or_non_string(session, bad):
    account = session.create_account(account_request())["account"]
    request = evaluation_request(account)
    request["rules"]["initialBalance"] = bad
    with pytest.raises(OfflineWorkflowError) as exc:
        session.evaluate(request)
    assert exc.value.code == "INVALID_INPUT"
    assert "initialBalance" in exc.value.fields


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("1" * 65, "DECIMAL_SIGNIFICANT_DIGITS_EXCEEDED"),
        ("1e129", "DECIMAL_EXPONENT_OUT_OF_RANGE"),
        ("1e-129", "DECIMAL_EXPONENT_OUT_OF_RANGE"),
    ],
)
def test_decimal_parser_enforces_existing_engine_contract_at_boundary(session, value, reason):
    account = session.create_account(account_request())["account"]
    request = evaluation_request(account)
    request["rules"]["initialBalance"] = value
    with pytest.raises(OfflineWorkflowError) as exc:
        session.evaluate(request)
    assert exc.value.fields == {"initialBalance": reason}


def test_currency_scope_and_official_profile_fields_are_not_accepted(session):
    with pytest.raises(OfflineWorkflowError):
        session.create_account(account_request(currency="usdt"))
    account = session.create_account(account_request())["account"]
    request = evaluation_request(account)
    request["rules"]["verificationStatus"] = "VERIFIED_FOR_ACCOUNT"
    with pytest.raises(OfflineWorkflowError) as exc:
        session.evaluate(request)
    assert exc.value.code == "INVALID_INPUT"


def test_percentages_and_observation_order_are_strict(session):
    account = session.create_account(account_request())["account"]
    request = evaluation_request(account)
    request["rules"]["maximumLossPct"] = "100.000000000000000001"
    with pytest.raises(OfflineWorkflowError) as exc:
        session.evaluate(request)
    assert exc.value.fields == {"maximumLossPct": "INVALID_PERCENTAGE"}
    request = evaluation_request(account, receivedAt="2026-11-04T01:59:59Z")
    with pytest.raises(OfflineWorkflowError) as exc:
        session.evaluate(request)
    assert exc.value.fields == {"receivedAt": "TEMPORAL_ORDER"}


def test_temporal_validation_failure_has_safe_message_and_no_outcome(session):
    account = session.create_account(account_request())["account"]
    request = evaluation_request(
        account,
        observedAt="2026-11-04T03:00:00Z",
        receivedAt="2026-11-04T03:00:01Z",
    )
    with pytest.raises(OfflineWorkflowError) as exc:
        session.evaluate(request)
    assert exc.value.code == "PRE_EVALUATION_VALIDATION_FAILED"
    assert "03:00" not in exc.value.message


def test_source_has_no_runtime_exchange_credential_or_external_io_imports():
    source = Path("backend/prop_trading/offline_workflow.py").read_text(encoding="utf-8")
    server = Path("backend/prop_trading/offline_server.py").read_text(encoding="utf-8")
    import_lines = "\n".join(
        line for line in (source + "\n" + server).splitlines()
        if line.startswith("import ") or line.startswith("from ")
    ).lower()
    forbidden = ("backend.main", "bot_manager", "requests", "httpx", "websocket", "credential", "exchange_client", "openai")
    for token in forbidden:
        assert token not in import_lines
    assert "open(" not in source
    assert "localStorage" not in source


def test_session_serializes_evaluation_and_revision_mutation():
    entered = threading.Event()
    release = threading.Event()

    class BlockingSession(OfflinePropSession):
        def _evaluate(self, account, data, ref):
            entered.set()
            assert release.wait(timeout=2)
            return super()._evaluate(account, data, ref)

    selected_session = BlockingSession(clock=lambda: NOW)
    account = selected_session.create_account(account_request())["account"]
    revision = {
        "requestId": "revision-concurrent",
        "accountId": account["identity"]["account_id"],
        "identityRevision": 1,
        "label": "Revised",
        "phase": "VERIFICATION",
        "currency": "USDT",
    }
    with ThreadPoolExecutor(max_workers=2) as executor:
        evaluation_future = executor.submit(selected_session.evaluate, evaluation_request(account))
        assert entered.wait(timeout=1)
        revision_future = executor.submit(selected_session.revise_account, revision)
        time.sleep(0.05)
        assert revision_future.done() is False
        release.set()
        assert evaluation_future.result()["identityRevision"] == 1
        assert revision_future.result()["account"]["identity"]["revision"] == 2


def _post(port, path, payload, *, origin="http://127.0.0.1:4187", content_type="application/json"):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request("POST", path, body=body, headers={"Origin": origin, "Content-Type": content_type})
    response = connection.getresponse()
    document = json.loads(response.read())
    connection.close()
    return response.status, dict(response.headers), document


def _method(port, method, path):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request(method, path, headers={"Origin": "http://127.0.0.1:4187"})
    response = connection.getresponse()
    document = json.loads(response.read())
    connection.close()
    return response.status, document


def test_loopback_http_integration_scope_origin_content_type_and_size(session):
    server = create_server(session=session, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        status, headers, created = _post(port, "/offline/accounts", account_request())
        assert status == 200 and created["ok"] is True
        assert headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:4187"
        account = created["account"]
        status, _, evaluated = _post(port, "/offline/evaluate", evaluation_request(account))
        assert status == 200
        assert evaluated["outcome"]["calculation"]["overallState"] == "PASS"
        status, _, rejected = _post(port, "/offline/evaluate", evaluation_request(account), origin="https://evil.example")
        assert status == 403 and rejected["error"]["code"] == "REQUEST_CONTEXT_REJECTED"
        status, _, rejected = _post(port, "/offline/evaluate", b"{}", content_type="text/plain")
        assert status == 415 and rejected["error"]["code"] == "JSON_REQUIRED"
        status, _, rejected = _post(port, "/offline/evaluate", b"x" * (MAX_BODY_BYTES + 1))
        assert status == 413 and rejected["error"]["code"] == "PAYLOAD_TOO_LARGE"
        duplicate = b'{"requestId":"one","requestId":"two","label":"Demo","phase":"CHALLENGE","currency":"USDT"}'
        status, _, rejected = _post(port, "/offline/accounts", duplicate)
        assert status == 400 and rejected["error"]["code"] == "INVALID_JSON"
        status, rejected = _method(port, "GET", "/offline/accounts")
        assert status == 405 and rejected["error"]["code"] == "METHOD_NOT_ALLOWED"

        slow = socket.create_connection(("127.0.0.1", port), timeout=3)
        slow.sendall(
            (
                "POST /offline/accounts HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                "Origin: http://127.0.0.1:4187\r\n"
                "Content-Type: application/json\r\n"
                "Content-Length: 10\r\n\r\n"
                "{}"
            ).encode()
        )
        slow.settimeout(BODY_READ_TIMEOUT_SECONDS + 2)
        response = b""
        while True:
            chunk = slow.recv(4096)
            if not chunk:
                break
            response += chunk
        slow.close()
        assert b"408 Request Timeout" in response
        assert b"BODY_READ_TIMEOUT" in response
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
