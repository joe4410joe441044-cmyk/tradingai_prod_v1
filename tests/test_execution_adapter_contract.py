from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.accounts import (
    ACCOUNT_IDENTITY_SCHEMA_VERSION,
    AccountId,
    AccountIdentity,
    AccountLifecycleState,
    AccountType,
    ExecutionMode,
    ExecutionVenue,
    PropPhase,
    PropProgram,
)
from backend.execution.adapter_contracts import (
    AccountReadResult,
    AdapterAccountSnapshot,
    AdapterBinding,
    AdapterCapabilities,
    AdapterErrorCode,
    AdapterFailure,
    AdapterResultStatus,
    BoundCancelRequest,
    BoundCancelResult,
    BoundExecutionRequest,
    BoundExecutionResult,
    CancelIntent,
    CapabilityState,
    ExecutionIntent,
    ExecutionOperation,
    OrderSide,
    OrderType,
    OrderSubmissionResult,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
A1 = AccountId("acc_00000000000040008000000000000001")
A2 = AccountId("acc_00000000000040008000000000000002")


def identity(account_id=A1):
    return AccountIdentity(
        ACCOUNT_IDENTITY_SCHEMA_VERSION, account_id, AccountType.PROP,
        ExecutionMode.EXTERNAL_SIMULATION, ExecutionVenue.BYBIT_DEMO,
        AccountLifecycleState.REGISTERED, 1, NOW, NOW,
        PropProgram.HYROTRADER, PropPhase.CHALLENGE,
    )


def snapshot(account_id=A1):
    return AdapterAccountSnapshot(
        account_id, NOW, "DEMO_READ", "USDT", Decimal("1000.00"),
        Decimal("1000.00"), Decimal("900.00"), 0, 0,
    )


def test_capability_unknown_and_unsupported_never_succeed_silently():
    capabilities = AdapterCapabilities(account_read=CapabilityState.UNSUPPORTED)
    with pytest.raises(RuntimeError, match=AdapterErrorCode.UNSUPPORTED_CAPABILITY.value):
        capabilities.require("account_read")
    with pytest.raises(RuntimeError, match=AdapterErrorCode.CAPABILITY_UNKNOWN.value):
        capabilities.require("order_submit")


def test_binding_is_account_scoped_and_credential_handle_is_not_rendered():
    binding = AdapterBinding(identity(), "opaque-secret-store-ref")
    assert binding.identity.account_id == A1
    assert "opaque-secret-store-ref" not in repr(binding)
    with pytest.raises(ValueError, match="credential"):
        AdapterBinding(identity(), None)


def test_paper_binding_rejects_credentials():
    paper = AccountIdentity(
        ACCOUNT_IDENTITY_SCHEMA_VERSION, A1, AccountType.NORMAL,
        ExecutionMode.PAPER, ExecutionVenue.INTERNAL_PAPER,
        AccountLifecycleState.REGISTERED, 1, NOW, NOW,
    )
    with pytest.raises(ValueError, match="must not"):
        AdapterBinding(paper, "unexpected")
    assert AdapterBinding(paper).credential_ref is None


def test_read_result_rejects_cross_account_snapshot():
    with pytest.raises(ValueError, match="mismatch"):
        AccountReadResult(A1, AdapterResultStatus.SUCCEEDED, snapshot(A2), None)


def test_read_failure_requires_typed_failure_and_no_fake_snapshot():
    failure = AdapterFailure(AdapterErrorCode.CAPABILITY_UNKNOWN)
    result = AccountReadResult(A1, AdapterResultStatus.UNKNOWN, None, failure)
    assert result.status is AdapterResultStatus.UNKNOWN
    with pytest.raises(ValueError):
        AccountReadResult(A1, AdapterResultStatus.SUCCEEDED, None, None)
    with pytest.raises(ValueError):
        AccountReadResult(A1, AdapterResultStatus.UNKNOWN, snapshot(), failure)


def test_execution_intent_has_no_authority_and_enforces_operation_semantics():
    intent = ExecutionIntent(
        A1, "client-order-1", ExecutionOperation.ENTRY, "BTCUSDT",
        OrderSide.BUY, OrderType.LIMIT, Decimal("0.001"), False, NOW,
        Decimal("50000.125"),
    )
    assert not hasattr(intent, "execution_allowed")
    assert intent.quantity == Decimal("0.001")
    with pytest.raises(ValueError, match="cannot be reduce_only"):
        ExecutionIntent(
            A1, "client-order-2", ExecutionOperation.ENTRY, "BTCUSDT",
            OrderSide.BUY, OrderType.MARKET, Decimal("0.001"), True, NOW,
        )
    with pytest.raises(ValueError, match="must be reduce_only"):
        ExecutionIntent(
            A1, "client-order-3", ExecutionOperation.REDUCE_OR_CLOSE, "BTCUSDT",
            OrderSide.SELL, OrderType.MARKET, Decimal("0.001"), False, NOW,
        )


def test_f04_adapter_failure_message_is_fixed_by_typed_code():
    failure = AdapterFailure(AdapterErrorCode.TIMEOUT)
    assert failure.safe_message == "adapter request timed out"
    with pytest.raises(TypeError):
        AdapterFailure(AdapterErrorCode.TIMEOUT, "caller supplied raw venue error")


def test_adapter_module_exposes_contracts_not_implementations():
    import backend.execution.adapter_contracts as contracts

    forbidden = {"KucoinTradeClient", "BybitClient", "BlofinClient", "create_client"}
    assert forbidden.isdisjoint(vars(contracts))


def test_f05_bound_execution_request_and_result_reject_account_or_order_mismatch():
    binding = AdapterBinding(identity(A1), "credential-ref")
    intent = ExecutionIntent(
        A1, "client-order-1", ExecutionOperation.ENTRY, "BTCUSDT",
        OrderSide.BUY, OrderType.MARKET, Decimal("0.001"), False, NOW,
    )
    request = BoundExecutionRequest(binding, intent)
    result = OrderSubmissionResult(
        A1, "client-order-1", AdapterResultStatus.SUCCEEDED, NOW, "venue-order-1"
    )
    assert BoundExecutionResult(request, result).result == result
    with pytest.raises(ValueError, match="mismatch"):
        BoundExecutionRequest(
            binding,
            ExecutionIntent(
                A2, "client-order-2", ExecutionOperation.ENTRY, "BTCUSDT",
                OrderSide.BUY, OrderType.MARKET, Decimal("0.001"), False, NOW,
            ),
        )
    with pytest.raises(ValueError, match="account_id mismatch"):
        BoundExecutionResult(
            request,
            OrderSubmissionResult(
                A2, "client-order-1", AdapterResultStatus.SUCCEEDED, NOW, "venue-order-2"
            ),
        )
    with pytest.raises(ValueError, match="client_order_id mismatch"):
        BoundExecutionResult(
            request,
            OrderSubmissionResult(
                A1, "different", AdapterResultStatus.SUCCEEDED, NOW, "venue-order-3"
            ),
        )


def test_f05_bound_cancel_request_and_result_are_account_scoped():
    binding = AdapterBinding(identity(A1), "credential-ref")
    request = BoundCancelRequest(binding, CancelIntent(A1, "client-order-1", NOW))
    result = OrderSubmissionResult(
        A1, "client-order-1", AdapterResultStatus.SUCCEEDED, NOW, "venue-order-1"
    )
    assert BoundCancelResult(request, result).result == result
    with pytest.raises(ValueError, match="mismatch"):
        BoundCancelRequest(binding, CancelIntent(A2, "client-order-1", NOW))
