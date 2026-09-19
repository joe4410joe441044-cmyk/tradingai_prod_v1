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

import os
import tempfile
from pathlib import Path

import pytest

_TEST_STORE_DIR = Path(tempfile.gettempdir()) / "tradingai-pp-test"
_TEST_STORE_DIR.mkdir(parents=True, exist_ok=True)
_TEST_STORE_PATH = _TEST_STORE_DIR / "parameter_performance.jsonl"

os.environ["PARAMETER_PERFORMANCE_PATH"] = str(_TEST_STORE_PATH)
os.environ["PARAMETER_PERFORMANCE_ORIGIN"] = "NON_PRODUCTION"


def _test_store_path() -> Path:
    return Path(os.environ["PARAMETER_PERFORMANCE_PATH"])


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
