# -*- coding: utf-8 -*-
"""WORK AA: permanent isolation of the durable live-order intent store.

These tests never use the real Production path. Every "production" store is a
synthetic directory under ``tmp_path`` that has the same layout as the real
store, so the isolation contract can be proven without touching Production.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from backend.execution.kucoin_trade import KucoinTradeClient
from backend.execution.live_order_intent import (
    STORE_PATH_PROTECTED,
    UNKNOWN_COMMIT,
    IntentStore,
    protected_store_conflict,
    store_paths_conflict,
)

PROTECTED_ENV = "TRADINGAI_LIVE_ORDER_INTENT_PROTECTED_PATHS"
PRODUCTION_ENV = "TRADINGAI_LIVE_ORDER_INTENT_PATH"
REPO_ROOT = Path(__file__).resolve().parents[1]


class Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self):
        self.posts = []
        self.gets = []

    def post(self, url, headers=None, data=None, timeout=None):
        self.posts.append(json.loads(data))
        return Response({"code": "200000", "data": {"orderId": "order-1"}})

    def get(self, url, headers=None, timeout=None):
        self.gets.append(url)
        return Response({"code": "200000", "data": {}})


def make_production_store(tmp_path, monkeypatch, *, name="prod-repo"):
    path = Path(tmp_path) / name / "logs" / "runtime" / "live_order_intents.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "intents": {
                    "production-intent": {
                        "intentId": "production-intent",
                        "purpose": "ENTRY",
                        "symbol": "BTCUSDTM",
                        "side": "buy",
                        "size": "1",
                        "state": "FLAT_CONFIRMED",
                        "orderId": "real-order",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(PROTECTED_ENV, json.dumps([str(path)]))
    return path


def make_client():
    trade = KucoinTradeClient(api_key="key", api_secret="secret", passphrase="pass")
    trade.session = FakeSession()
    trade.live_order_allowed = True
    trade.runtime_submission_allowed = True
    trade.permission_contract = {
        "permissionStatus": "VERIFIED",
        "verifiedPermission": "TRADE",
        "verificationSource": "KUCOIN_ACCOUNT_RESPONSE:permission",
        "verifiedAt": time.time(),
        "credentialFingerprint": trade.current_credential_fingerprint(),
        "venue": "KUCOIN_FUTURES",
    }
    return trade


def entry(trade, intent_id="entry-isolation"):
    return trade.submit_bounded_order(
        purpose="ENTRY",
        symbol="XRPUSDTM",
        side="buy",
        size=1,
        intent_id=intent_id,
        body_fields={
            "symbol": "XRPUSDTM",
            "side": "buy",
            "type": "market",
            "size": "1",
            "leverage": "2",
            "marginMode": "ISOLATED",
        },
    )


def exit_order(trade):
    return trade.submit_bounded_order(
        purpose="EXIT",
        symbol="XRPUSDTM",
        side="sell",
        size=1,
        body_fields={
            "symbol": "XRPUSDTM",
            "side": "sell",
            "type": "market",
            "size": "1",
            "reduceOnly": True,
            "marginMode": "ISOLATED",
        },
    )


# 1. Production path inherited by pytest -> isolated
def test_inherited_production_path_is_blanked_for_tests():
    assert os.environ.get(PRODUCTION_ENV) == ""


def test_inherited_production_path_cannot_be_used(tmp_path, monkeypatch):
    production = make_production_store(tmp_path, monkeypatch)
    monkeypatch.setenv(PRODUCTION_ENV, str(production))
    trade = make_client()
    result = trade.configure_live_runtime_intent_store(None)
    assert result == {"ready": False, "reason": STORE_PATH_PROTECTED}


# 2. Missing test path -> explicit failure
def test_missing_test_path_fails_closed():
    trade = make_client()
    assert trade.configure_live_runtime_intent_store(None)["reason"] == "STORE_PATH_MISSING"
    assert entry(trade)["reason"] == "STORE_PATH_MISSING"
    assert trade.session.posts == []


def test_missing_test_path_fallback_is_temporary_and_not_production(tmp_path, monkeypatch):
    production = make_production_store(tmp_path, monkeypatch)
    trade = make_client()
    store = trade._order_intent_store()
    assert store is not None
    assert not store_paths_conflict(store.path, production)
    assert str(store.path).startswith(str(Path(os.path.realpath(store.path)).parent))
    assert "tradingai-live-order-intents-" in Path(store.path).name


# 3. Explicit test path -> allowed
def test_explicit_test_path_is_allowed(tmp_path, monkeypatch):
    monkeypatch.delenv(PROTECTED_ENV, raising=False)
    path = tmp_path / "test-store" / "intents.json"
    path.parent.mkdir()
    trade = make_client()
    assert trade.configure_live_runtime_intent_store(str(path))["ready"] is True
    opened = entry(trade)
    assert opened["submit"] is True
    assert path.exists()
    assert len(trade.session.posts) == 1


# 4. Test path equals Production path -> rejected
def test_explicit_path_equal_to_production_is_rejected(tmp_path, monkeypatch):
    production = make_production_store(tmp_path, monkeypatch)
    before = production.read_bytes()
    trade = make_client()
    assert trade.configure_live_runtime_intent_store(str(production)) == {
        "ready": False,
        "reason": STORE_PATH_PROTECTED,
    }
    blocked = entry(trade)
    assert blocked["submit"] is False
    assert blocked["reason"] == STORE_PATH_PROTECTED
    assert trade.session.posts == []
    assert production.read_bytes() == before


# 5. Test path aliases Production path -> rejected
def test_symlink_file_alias_is_rejected(tmp_path, monkeypatch):
    production = make_production_store(tmp_path, monkeypatch)
    alias = tmp_path / "alias.json"
    alias.symlink_to(production)
    assert store_paths_conflict(alias, production) is True
    assert protected_store_conflict(alias) == STORE_PATH_PROTECTED
    assert IntentStore(str(alias)).load_error == STORE_PATH_PROTECTED


def test_symlinked_directory_alias_is_rejected(tmp_path, monkeypatch):
    production = make_production_store(tmp_path, monkeypatch)
    linked_dir = tmp_path / "linked-runtime"
    linked_dir.symlink_to(production.parent, target_is_directory=True)
    alias = linked_dir / production.name
    assert protected_store_conflict(alias) == STORE_PATH_PROTECTED
    assert IntentStore(str(alias)).load_error == STORE_PATH_PROTECTED


def test_hardlink_alias_is_rejected(tmp_path, monkeypatch):
    production = make_production_store(tmp_path, monkeypatch)
    hardlink = tmp_path / "hardlink.json"
    os.link(production, hardlink)
    assert store_paths_conflict(hardlink, production) is True
    assert protected_store_conflict(hardlink) == STORE_PATH_PROTECTED
    assert IntentStore(str(hardlink)).load_error == STORE_PATH_PROTECTED


# 6. Fake intent persists only in the test store
def test_fake_intent_persists_only_in_test_store(tmp_path, monkeypatch):
    production = make_production_store(tmp_path, monkeypatch)
    before = production.read_bytes()
    test_store = tmp_path / "test-store" / "intents.json"
    test_store.parent.mkdir()
    trade = make_client()
    trade.order_intent_path = str(test_store)
    opened = entry(trade)
    assert opened["submit"] is True
    payload = json.loads(test_store.read_text(encoding="utf-8"))
    assert opened["intentId"] in payload["intents"]
    assert production.read_bytes() == before
    assert "XRPUSDTM" not in production.read_text(encoding="utf-8")


# 7. Production store bytes unchanged
def test_production_store_bytes_unchanged_by_test_activity(tmp_path, monkeypatch):
    production = make_production_store(tmp_path, monkeypatch)
    before_bytes = production.read_bytes()
    before_stat = production.stat()
    trade = make_client()
    trade.order_intent_path = str(tmp_path / "isolated" / "intents.json")
    (tmp_path / "isolated").mkdir()
    entry(trade)
    assert production.read_bytes() == before_bytes
    after_stat = production.stat()
    assert after_stat.st_size == before_stat.st_size
    assert after_stat.st_mtime_ns == before_stat.st_mtime_ns
    assert after_stat.st_ino == before_stat.st_ino


# 8. Production store directory unchanged
def test_production_store_directory_unchanged(tmp_path, monkeypatch):
    production = make_production_store(tmp_path, monkeypatch)
    directory = production.parent
    before = sorted((item.name, item.stat().st_size) for item in directory.iterdir())
    trade = make_client()
    trade.order_intent_path = str(tmp_path / "isolated" / "intents.json")
    (tmp_path / "isolated").mkdir()
    entry(trade)
    after = sorted((item.name, item.stat().st_size) for item in directory.iterdir())
    assert after == before


# 9. Test isolation across cases
def test_test_stores_do_not_share_intents(tmp_path):
    first = IntentStore(str(tmp_path / "a" / "intents.json"))
    (tmp_path / "a").mkdir()
    second = IntentStore(str(tmp_path / "b" / "intents.json"))
    (tmp_path / "b").mkdir()
    first.begin(purpose="ENTRY", symbol="XRPUSDTM", side="buy", size=1, intent_id="only-first")
    assert first.get("only-first") is not None
    assert second.get("only-first") is None


# 10. Test isolation across subprocesses
def test_guard_survives_a_subprocess(tmp_path, monkeypatch):
    production = make_production_store(tmp_path, monkeypatch)
    before = production.read_bytes()
    script = (
        "import json\n"
        "from backend.execution.live_order_intent import IntentStore\n"
        f"store = IntentStore({str(production)!r})\n"
        "result = store.begin(purpose='EXIT', symbol='XRPUSDTM', side='sell', size=1, intent_id='sub')\n"
        "print(json.dumps({'load_error': store.load_error, 'reason': result.get('reason')}))\n"
    )
    env = dict(os.environ)
    env[PROTECTED_ENV] = json.dumps([str(production)])
    env[PRODUCTION_ENV] = ""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    observed = json.loads(completed.stdout.strip().splitlines()[-1])
    assert observed["load_error"] == STORE_PATH_PROTECTED
    assert observed["reason"] == STORE_PATH_PROTECTED
    assert production.read_bytes() == before


# 11. Existing runtime production path remains valid (guard is opt-in)
def test_normal_configured_store_is_accepted_without_guard(tmp_path, monkeypatch):
    monkeypatch.delenv(PROTECTED_ENV, raising=False)
    path = tmp_path / "runtime" / "live_order_intents.json"
    path.parent.mkdir()
    trade = make_client()
    assert trade.configure_live_runtime_intent_store(str(path))["ready"] is True
    assert entry(trade)["submit"] is True
    assert path.exists()


# 12. Existing idempotency behavior preserved
def test_idempotent_begin_preserves_client_oid(tmp_path):
    store = IntentStore(str(tmp_path / "intents.json"))
    first = store.begin(purpose="ENTRY", symbol="XRPUSDTM", side="buy", size=1, intent_id="id-1")
    second = store.begin(purpose="ENTRY", symbol="XRPUSDTM", side="buy", size=1, intent_id="id-1")
    assert first["clientOid"] == second["clientOid"]
    assert second["created"] is False


# 13. UNKNOWN_COMMIT behavior preserved
def test_unknown_commit_state_is_preserved(tmp_path):
    store = IntentStore(str(tmp_path / "intents.json"))
    store.begin(purpose="ENTRY", symbol="XRPUSDTM", side="buy", size=1, intent_id="unknown")
    store.note_not_found("unknown")
    assert store.get("unknown")["state"] == UNKNOWN_COMMIT


# 14. Restart recovery behavior preserved
def test_restart_recovery_reads_the_same_test_store(tmp_path):
    path = tmp_path / "intents.json"
    first = IntentStore(str(path))
    first.begin(purpose="ENTRY", symbol="XRPUSDTM", side="buy", size=1, intent_id="restart")
    restarted = IntentStore(str(path))
    assert restarted.get("restart") is not None
    assert restarted.get("restart")["intentId"] == "restart"


# 15. No exchange write occurs
def test_guarded_exit_never_posts_or_writes_production(tmp_path, monkeypatch):
    production = make_production_store(tmp_path, monkeypatch)
    before = production.read_bytes()
    trade = make_client()
    assert trade.configure_live_runtime_intent_store(str(production))["ready"] is False
    blocked = exit_order(trade)
    assert blocked["submit"] is False
    assert trade.session.posts == []
    assert production.read_bytes() == before
    assert "XRPUSDTM" not in production.read_text(encoding="utf-8")
