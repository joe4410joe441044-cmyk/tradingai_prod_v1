"""Test-session isolation for the durable Stage 13 Parameter Performance store.

The production runtime resolves the Parameter Performance store from the
CWD-relative default ``logs/runtime/parameter_performance.jsonl``.  Any test
that drives the real ExecutionEngine close path would therefore append into the
Production store when pytest is executed from the repository root.

This conftest makes the persistence destination explicit and isolated for the
whole test session, BEFORE any test module is imported:

* ``PARAMETER_PERFORMANCE_PATH`` points at a temporary file that is never the
  Production path;
* ``PARAMETER_PERFORMANCE_ORIGIN`` marks any record written through the default
  writer as ``origin=NON_PRODUCTION``.

The fixture changes ONLY the Parameter Performance persistence destination and
provenance.  It deliberately does NOT set the generic ``TEST_MODE`` flag, so no
unrelated application/test semantics are altered.

Persistence is not disabled: the real writer/store is still exercised, just
against isolated storage.  Tests that construct ``ParameterPerformanceStore``
with ``tmp_path`` remain independently isolated.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

_TEST_STORE_DIR = Path(tempfile.gettempdir()) / "tradingai-pp-test"
_TEST_STORE_DIR.mkdir(parents=True, exist_ok=True)
_TEST_STORE_PATH = _TEST_STORE_DIR / "parameter_performance.jsonl"

os.environ["PARAMETER_PERFORMANCE_PATH"] = str(_TEST_STORE_PATH)
os.environ["PARAMETER_PERFORMANCE_ORIGIN"] = "NON_PRODUCTION"

# D-LIVE-2: isolate the canonical saved-mode authority so no test can read or
# write the Production destination file.
_TEST_SAVED_MODE_DIR = Path(tempfile.gettempdir()) / "tradingai-saved-mode-test"
_TEST_SAVED_MODE_DIR.mkdir(parents=True, exist_ok=True)
_TEST_SAVED_MODE_PATH = _TEST_SAVED_MODE_DIR / "saved_mode_authority.json"

os.environ["TRADINGAI_SAVED_MODE_PATH"] = str(_TEST_SAVED_MODE_PATH)

# D-LIVE-4F-1: isolate the durable configured-symbol authority so no test can
# read or write the Production destination file.
_TEST_CONFIGURED_SYMBOL_DIR = (
    Path(tempfile.gettempdir()) / "tradingai-configured-symbol-test"
)
_TEST_CONFIGURED_SYMBOL_DIR.mkdir(parents=True, exist_ok=True)
_TEST_CONFIGURED_SYMBOL_PATH = (
    _TEST_CONFIGURED_SYMBOL_DIR / "configured_symbol_authority.json"
)

os.environ["TRADINGAI_CONFIGURED_SYMBOL_PATH"] = str(
    _TEST_CONFIGURED_SYMBOL_PATH
)


# D-LIVE-11A: isolate the durable Money Management configuration so no test can
# read or write the Production logs/runtime destination file.
_TEST_MM_CONFIG_DIR = Path(tempfile.gettempdir()) / "tradingai-mm-config-test"
_TEST_MM_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
_TEST_MM_CONFIG_PATH = _TEST_MM_CONFIG_DIR / "money_management_config.json"

os.environ["TRADINGAI_MONEY_MANAGEMENT_CONFIG_PATH"] = str(_TEST_MM_CONFIG_PATH)


# WORK AA: isolate the durable live-order intent store so a test can never
# resolve the Production store through the environment. ``backend.execution.
# kucoin_trade`` calls ``load_dotenv()`` at import time; because that happens
# after this conftest, the variable is BLANKED (not unset) so dotenv cannot
# re-inject the Production value. Blank also keeps the documented fail-closed
# contract: no configured path means ``STORE_PATH_MISSING``.
_TEST_INTENT_DIR = Path(tempfile.gettempdir()) / "tradingai-live-order-intent-test"
_TEST_INTENT_DIR.mkdir(parents=True, exist_ok=True)
_TEST_INTENT_PATH = _TEST_INTENT_DIR / "live_order_intents.json"

_PROTECTED_INTENT_PATHS = []


def _register_protected_intent_path(value):
    if not value:
        return
    try:
        text = os.fspath(value)
    except TypeError:
        return
    if text and text not in _PROTECTED_INTENT_PATHS:
        _PROTECTED_INTENT_PATHS.append(text)


# Capture any inherited path and the value that ``load_dotenv()`` would later
# load, so the store guard can reject those exact paths (and their aliases).
_register_protected_intent_path(os.environ.get("TRADINGAI_LIVE_ORDER_INTENT_PATH"))
try:
    from dotenv import dotenv_values, find_dotenv

    _dotenv_path = find_dotenv()
    if _dotenv_path:
        _register_protected_intent_path(
            dotenv_values(_dotenv_path).get("TRADINGAI_LIVE_ORDER_INTENT_PATH")
        )
except Exception:
    pass

os.environ["TRADINGAI_LIVE_ORDER_INTENT_PROTECTED_PATHS"] = json.dumps(
    _PROTECTED_INTENT_PATHS
)
os.environ["TRADINGAI_LIVE_ORDER_INTENT_PATH"] = ""


def _test_store_path() -> Path:
    return Path(os.environ["PARAMETER_PERFORMANCE_PATH"])


def _test_saved_mode_path() -> Path:
    return Path(os.environ["TRADINGAI_SAVED_MODE_PATH"])


def _test_configured_symbol_path() -> Path:
    return Path(os.environ["TRADINGAI_CONFIGURED_SYMBOL_PATH"])


def _test_mm_config_path() -> Path:
    return Path(os.environ["TRADINGAI_MONEY_MANAGEMENT_CONFIG_PATH"])


@pytest.fixture(autouse=True)
def _isolated_parameter_performance_store():
    """Start every test with an empty isolated store."""

    path = _test_store_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    yield path
    try:
        path.unlink()
    except FileNotFoundError:
        pass


@pytest.fixture(autouse=True)
def _isolated_saved_mode_authority():
    """Start every test with no committed saved-mode destination."""

    path = _test_saved_mode_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    yield path
    try:
        path.unlink()
    except FileNotFoundError:
        pass


@pytest.fixture(autouse=True)
def _isolated_configured_symbol_authority():
    """Start every test with no committed configured MANUAL symbol."""

    path = _test_configured_symbol_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    yield path
    try:
        path.unlink()
    except FileNotFoundError:
        pass


@pytest.fixture(autouse=True)
def _isolated_supervisor_held_evaluation_cache():
    """Keep completed-evaluation memory inside the test that created it."""

    import sys

    module = sys.modules.get("backend.supervisor.held_evaluation_cache")
    if module is not None:
        module.reset_holder()
    yield
    module = sys.modules.get("backend.supervisor.held_evaluation_cache")
    if module is not None:
        module.reset_holder()


@pytest.fixture(autouse=True)
def _isolated_money_management_configuration():
    """Start every test with no committed Production MM configuration."""

    path = _test_mm_config_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    yield path
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _remove_live_order_intent_files():
    for suffix in ("", ".lock", ".tmp"):
        try:
            Path(str(_TEST_INTENT_PATH) + suffix).unlink()
        except FileNotFoundError:
            pass


@pytest.fixture(autouse=True)
def _isolated_live_order_intent_store():
    """Fail closed when the live-order intent store is not test-isolated.

    The session-level conftest blanks the inherited Production path, so any
    non-empty value here means a test (or a leaked environment) re-enabled an
    unisolated destination. Refuse to run rather than risk a Production write.
    """

    current = os.environ.get("TRADINGAI_LIVE_ORDER_INTENT_PATH", "")
    if current:
        raise RuntimeError("LIVE_ORDER_INTENT_STORE_NOT_ISOLATED")
    _remove_live_order_intent_files()
    yield _TEST_INTENT_PATH
    _remove_live_order_intent_files()
