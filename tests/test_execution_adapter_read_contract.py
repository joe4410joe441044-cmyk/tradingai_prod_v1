from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.accounts import AccountId, ExecutionVenue
from backend.execution.adapter_contracts import (
    AdapterErrorCode,
    AdapterFailure,
    AdapterResultStatus,
    PropRuleReadResult,
    QuoteSnapshot,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
ACCOUNT_ID = AccountId("acc_00000000000040008000000000000001")


def test_public_quote_is_read_only_data_and_requires_an_observed_price():
    quote = QuoteSnapshot(
        ExecutionVenue.BYBIT_DEMO,
        "BTCUSDT",
        NOW,
        Decimal("50000.1"),
        Decimal("50000.2"),
        None,
    )
    assert quote.bid == Decimal("50000.1")
    with pytest.raises(ValueError, match="at least one"):
        QuoteSnapshot(ExecutionVenue.BYBIT_DEMO, "BTCUSDT", NOW, None, None, None)


def test_rule_read_unsupported_is_typed_and_cannot_be_fake_success():
    failure = AdapterFailure(AdapterErrorCode.UNSUPPORTED_CAPABILITY)
    result = PropRuleReadResult(
        ACCOUNT_ID,
        AdapterResultStatus.REJECTED,
        None,
        failure,
    )
    assert result.failure.code is AdapterErrorCode.UNSUPPORTED_CAPABILITY
    with pytest.raises(ValueError, match="successful"):
        PropRuleReadResult(ACCOUNT_ID, AdapterResultStatus.SUCCEEDED, None, None)
