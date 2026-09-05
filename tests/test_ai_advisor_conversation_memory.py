"""D-4 focused tests: persistent, read-only Advisor conversation memory.

These tests cover the conversation-memory persistence core and its read-only
integration with the AI Advisor browser gateway.  They intentionally do NOT
import ``tests.test_ai_advisor_api`` or any ``openai``-dependent module so
they can be collected and run in the current environment.
"""

import itertools
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.ai_advisor.api_rate_limit import (
    AdvisorConcurrencyLimiter,
    AdvisorRateLimiter,
)
from backend.ai_advisor.browser_gateway import (
    AdvisorBrowserGatewayComposition,
    AdvisorBrowserGatewayConfig,
    AdvisorGatewayPreflightDenyMiddleware,
    assemble_browser_service_input,
    create_browser_gateway_router,
)
from backend.ai_advisor.context_builder import build_advisor_context
from backend.ai_advisor.conversation_models import (
    AdvisorCapability,
    AdvisorConversationMessage,
    AdvisorDataAccessScope,
    AdvisorPermissionContext,
    AdvisorRequest,
    AdvisorRole,
    AdvisorSourceType,
    AuthenticationState,
    AuthorizationState,
)
from backend.ai_advisor.conversation_store import (
    MAX_CONVERSATIONS_PER_OPERATOR,
    MAX_MESSAGES_PER_CONVERSATION,
    MAX_PROMPT_HISTORY_CHARACTERS,
    MAX_PROMPT_HISTORY_MESSAGES,
    MAX_STORED_MESSAGE_CHARACTERS,
    AdvisorConversationStore,
    AdvisorConversationStoreError,
    AdvisorConversationStoreErrorCode,
    AdvisorPersistedMessage,
    ConversationMemoryAuthority,
)
from backend.ai_advisor.models import (
    AdvisorAuthorityStatus,
    AdvisorBotStatus,
    AdvisorExecutionEntryState,
    AdvisorHealthStatus,
    AdvisorMarketStatus,
    AdvisorMoneyManagementStatus,
    AdvisorOperationStatus,
    AdvisorRuntimeMetadata,
    AdvisorRuntimeResponse,
    AdvisorSafetyStatus,
    Freshness,
)
from backend.ai_advisor.prompt_builder import build_advisor_prompt
from backend.ai_advisor.prompt_models import (
    AdvisorPromptPolicy,
    AdvisorPromptSectionType,
)
from backend.ai_advisor.response_models import (
    AdvisorResponseEnvelope,
    AdvisorResponseStatus,
    AdvisorSafetyDisclosure,
)
from backend.ai_advisor.service_models import (
    AdvisorServiceFailure,
    AdvisorServiceFailureCode,
    AdvisorServiceInput,
    AdvisorServiceResult,
    AdvisorServiceStatus,
    service_failure_message,
)

NOW = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)
ORIGIN = "https://advisor.example.test"
FIXED_CLOCK = lambda: time.time()  # noqa: E731

# The authority keywords that conversation memory must NEVER expose.
AUTHORITY_VERBS = (
    "start",
    "stop",
    "enable",
    "disable",
    "submit",
    "cancel_order",
    "replace_order",
    "execute",
    "unlock",
    "approve",
    "set_config",
    "configure",
    "set_risk",
    "change_mode",
    "create_order",
    "open_position",
    "close_position",
)


def _now():
    return NOW


_MESSAGE_COUNTER = itertools.count()

def _next_message_id():
    return f"m{next(_MESSAGE_COUNTER)}"


def _tmp_store():
    directory = tempfile.mkdtemp(prefix="d4-conv-")
    return AdvisorConversationStore(os.path.join(directory, "conv.sqlite3"))


def _record(
    conversation_id,
    operator,
    role,
    content,
    *,
    message_id=None,
    request_id=None,
    response_status=None,
    provider_model=None,
    created_at=None,
):
    return AdvisorPersistedMessage(
        messageId=message_id or _next_message_id(),
        conversationId=conversation_id,
        operatorId=operator,
        role=role,
        content=content,
        createdAt=created_at or _now(),
        requestId=request_id,
        responseStatus=response_status,
        providerModel=provider_model,
    )


def _success_result(service_input):
    return AdvisorServiceResult(
        status=AdvisorServiceStatus.SUCCEEDED,
        response=AdvisorResponseEnvelope(
            responseVersion="1.0",
            requestId=service_input.request.requestId,
            promptVersion="1.0",
            receivedAt=service_input.receivedAt,
            status=AdvisorResponseStatus.VALID,
            summary="Safe answer.",
            facts=(),
            inferences=(),
            unknowns=(),
            warnings=(),
            sourceReferences=(),
            freshnessDisclosures=(),
            safetyDisclosures=(
                AdvisorSafetyDisclosure.READ_ONLY,
                AdvisorSafetyDisclosure.NO_ACTION_EXECUTED,
                AdvisorSafetyDisclosure.NO_STATE_CHANGED,
                AdvisorSafetyDisclosure.NO_TOOL_USED,
            ),
            forbiddenClaims=(),
            validationWarnings=(),
        ),
        failure=None,
    )


def _failed_result(service_input):
    return AdvisorServiceResult(
        status=AdvisorServiceStatus.FAILED,
        failure=AdvisorServiceFailure(
            code=AdvisorServiceFailureCode.ADVISOR_PROVIDER_FAILURE,
            safeMessage=service_failure_message(
                AdvisorServiceFailureCode.ADVISOR_PROVIDER_FAILURE
            ),
            retryAllowed=False,
        ),
    )


class RecordingService:
    def __init__(self, result_factory=_success_result):
        self.last_input = None
        self.calls = 0
        self.result_factory = result_factory

    def generate_response(self, service_input):
        self.calls += 1
        self.last_input = service_input
        return self.result_factory(service_input)


class FailingConversationStore(AdvisorConversationStore):
    def __init__(self):
        self.errored = False

    def resolve_conversation(self, operator, conversation_id=None):
        if self.errored:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
                "conversation store unavailable",
            )
        return "conversation-failing", True

    def read_messages(self, operator, conversation_id):
        if self.errored:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
                "conversation store unavailable",
            )
        return ()

    def append_message(self, operator, conversation_id, message):
        if self.errored:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
                "conversation store unavailable",
            )

    def bounded_history(self, records, **kwargs):
        return records

    def list_conversations(self, operator):
        if self.errored:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
                "conversation store unavailable",
            )
        return ()

    def delete_conversation(self, operator, conversation_id):
        if self.errored:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
                "conversation store unavailable",
            )
        return False


class VariableSessionMiddleware:
    """Inject operator_session identity driven by the ``x-test-operator`` header."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        identity = "operator-1"
        for name, value in scope.get("headers", ()):
            if name.lower() == b"x-test-operator":
                identity = value.decode("latin-1")
                break
        scope["operator_session"] = {"identity": identity, "session_id": "session-1"}
        await self.app(scope, receive, send)


def _gateway_headers(operator="operator-1", *, origin=None, fetch_site=None):
    headers = {"X-TradingAI-Client": "web"}
    if origin is not None:
        headers["Origin"] = origin
    if fetch_site is not None:
        headers["Sec-Fetch-Site"] = fetch_site
    if operator is not None:
        headers["X-Test-Operator"] = operator
    return headers


def build_gateway_app(store, service, *, session=True):
    config = AdvisorBrowserGatewayConfig(
        enabled=True,
        trustedProxyPeers=(),
        allowedOrigins=(ORIGIN,),
        endpointTimeoutSeconds=5,
    )
    composition = AdvisorBrowserGatewayComposition(
        config=config,
        service=service,
        rateLimiter=AdvisorRateLimiter(
            limit=100, window_seconds=60, clock=FIXED_CLOCK
        ),
        concurrencyLimiter=AdvisorConcurrencyLimiter(
            limit=4, acquire_timeout_seconds=0.1
        ),
        clock=lambda: NOW,
        externalStatus="OFFLINE",
        approvedSpecifications=(),
        conversationStore=store,
    )
    app = FastAPI()
    if session:
        app.add_middleware(VariableSessionMiddleware)
    app.include_router(create_browser_gateway_router(composition))
    app.add_middleware(AdvisorGatewayPreflightDenyMiddleware)
    return app


class PersistenceTest(unittest.TestCase):
    def test_create_append_read_reload(self):
        store = _tmp_store()
        conversation_id, created = store.resolve_conversation("operator-1", None)
        self.assertTrue(created)
        store.append_message(
            "operator-1",
            conversation_id,
            _record(
                conversation_id,
                "operator-1",
                AdvisorRole.USER,
                "Explain entry block.",
                message_id="m1",
                request_id="r1",
            ),
        )
        store.append_message(
            "operator-1",
            conversation_id,
            _record(
                conversation_id,
                "operator-1",
                AdvisorRole.ADVISOR,
                "Entry is blocked.",
                message_id="m2",
                request_id="r1",
                response_status="VALID",
                provider_model="test-model",
            ),
        )
        messages = store.read_messages("operator-1", conversation_id)
        self.assertEqual(
            [m.role.value for m in messages], ["USER", "ADVISOR"]
        )
        self.assertEqual([m.content for m in messages], [
            "Explain entry block.", "Entry is blocked.",
        ])
        self.assertEqual(messages[0].requestId, "r1")
        self.assertEqual(messages[1].responseStatus, "VALID")
        self.assertEqual(messages[1].providerModel, "test-model")

    def test_survives_reconstruction(self):
        directory = tempfile.mkdtemp(prefix="d4-reconstruct-")
        path = os.path.join(directory, "conv.sqlite3")
        store = AdvisorConversationStore(path)
        conversation_id, _ = store.resolve_conversation("operator-1", None)
        store.append_message(
            "operator-1",
            conversation_id,
            _record(conversation_id, "operator-1", AdvisorRole.USER, "Q1"),
        )
        store.append_message(
            "operator-1",
            conversation_id,
            _record(conversation_id, "operator-1", AdvisorRole.ADVISOR, "A1"),
        )
        reconstructed = AdvisorConversationStore(path)
        messages = reconstructed.read_messages("operator-1", conversation_id)
        self.assertEqual([m.content for m in messages], ["Q1", "A1"])

    def test_ordering_is_deterministic_by_insertion(self):
        store = _tmp_store()
        conversation_id, _ = store.resolve_conversation("operator-1", None)
        for index, content in enumerate(["first", "second", "third"]):
            store.append_message(
                "operator-1",
                conversation_id,
                _record(
                    conversation_id,
                    "operator-1",
                    AdvisorRole.USER,
                    content,
                    message_id=f"msg-{index}",
                    request_id=f"req-{index}",
                ),
            )
        messages = store.read_messages("operator-1", conversation_id)
        self.assertEqual([m.content for m in messages], ["first", "second", "third"])

    def test_resolve_existing_conversation_is_idempotent(self):
        store = _tmp_store()
        conversation_id, created1 = store.resolve_conversation("operator-1", None)
        same_id, created2 = store.resolve_conversation("operator-1", conversation_id)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(conversation_id, same_id)


class IsolationTest(unittest.TestCase):
    def test_operator_a_cannot_read_operator_b(self):
        store = _tmp_store()
        conversation_id_a, _ = store.resolve_conversation("operator-a", None)
        store.append_message(
            "operator-a",
            conversation_id_a,
            _record(conversation_id_a, "operator-a", AdvisorRole.USER, "secret-a"),
        )
        with self.assertRaises(AdvisorConversationStoreError) as context:
            store.read_messages("operator-b", conversation_id_a)
        self.assertEqual(
            context.exception.code,
            AdvisorConversationStoreErrorCode.CONVERSATION_NOT_FOUND,
        )

    def test_operator_a_cannot_delete_operator_b(self):
        store = _tmp_store()
        conversation_id_a, _ = store.resolve_conversation("operator-a", None)
        store.append_message(
            "operator-a",
            conversation_id_a,
            _record(conversation_id_a, "operator-a", AdvisorRole.USER, "keep"),
        )
        self.assertFalse(store.delete_conversation("operator-b", conversation_id_a))
        self.assertEqual(len(store.read_messages("operator-a", conversation_id_a)), 1)

    def test_operator_a_cannot_append_to_operator_b(self):
        store = _tmp_store()
        conversation_id_a, _ = store.resolve_conversation("operator-a", None)
        with self.assertRaises(AdvisorConversationStoreError) as context:
            store.append_message(
                "operator-b",
                conversation_id_a,
                _record(conversation_id_a, "operator-b", AdvisorRole.USER, "intrude"),
            )
        self.assertEqual(
            context.exception.code,
            AdvisorConversationStoreErrorCode.CONVERSATION_FORBIDDEN,
        )

    def test_resolve_foreign_conversation_fails_closed(self):
        store = _tmp_store()
        conversation_id_a, _ = store.resolve_conversation("operator-a", None)
        with self.assertRaises(AdvisorConversationStoreError) as context:
            store.resolve_conversation("operator-b", conversation_id_a)
        self.assertEqual(
            context.exception.code,
            AdvisorConversationStoreErrorCode.CONVERSATION_FORBIDDEN,
        )

    def test_unknown_conversation_fails_safely(self):
        store = _tmp_store()
        with self.assertRaises(AdvisorConversationStoreError) as context:
            store.read_messages("operator-a", "conversation-does-not-exist")
        self.assertEqual(
            context.exception.code,
            AdvisorConversationStoreErrorCode.CONVERSATION_NOT_FOUND,
        )

    def test_list_conversations_is_scoped_to_operator(self):
        store = _tmp_store()
        conversation_id_a, _ = store.resolve_conversation("operator-a", None)
        store.resolve_conversation("operator-b", None)
        store.append_message(
            "operator-a",
            conversation_id_a,
            _record(conversation_id_a, "operator-a", AdvisorRole.USER, "a-only"),
        )
        summaries_a = store.list_conversations("operator-a")
        summaries_b = store.list_conversations("operator-b")
        self.assertEqual(len(summaries_a), 1)
        self.assertEqual(len(summaries_b), 1)
        self.assertEqual(summaries_a[0].conversationId, conversation_id_a)
        self.assertEqual(summaries_a[0].messageCount, 1)
        self.assertEqual(summaries_b[0].messageCount, 0)


class BoundsTest(unittest.TestCase):
    def test_content_length_limit_is_enforced(self):
        store = AdvisorConversationStore(
            os.path.join(tempfile.mkdtemp(), "conv.sqlite3"),
            max_message_characters=100,
        )
        conversation_id, _ = store.resolve_conversation("operator-a", None)
        oversized = _record(
            conversation_id,
            "operator-a",
            AdvisorRole.USER,
            "x" * 200,
        )
        with self.assertRaises(AdvisorConversationStoreError) as context:
            store.append_message("operator-a", conversation_id, oversized)
        self.assertEqual(
            context.exception.code,
            AdvisorConversationStoreErrorCode.MESSAGE_INVALID,
        )

    def test_message_model_rejects_content_beyond_cap(self):
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            AdvisorPersistedMessage(
                messageId="m1",
                conversationId="c1",
                operatorId="op1",
                role=AdvisorRole.USER,
                content="x" * (MAX_STORED_MESSAGE_CHARACTERS + 1),
                createdAt=_now(),
            )

    def test_message_retention_trims_oldest(self):
        store = _tmp_store()
        conversation_id, _ = store.resolve_conversation("operator-a", None)
        for index in range(MAX_MESSAGES_PER_CONVERSATION + 5):
            store.append_message(
                "operator-a",
                conversation_id,
                _record(
                    conversation_id,
                    "operator-a",
                    AdvisorRole.USER,
                    f"msg-{index}",
                    message_id=f"mid-{index}",
                    request_id=f"rid-{index}",
                ),
            )
        messages = store.read_messages("operator-a", conversation_id)
        self.assertEqual(len(messages), MAX_MESSAGES_PER_CONVERSATION)
        self.assertEqual(messages[0].content, "msg-5")
        self.assertEqual(messages[-1].content, f"msg-{MAX_MESSAGES_PER_CONVERSATION + 4}")

    def test_bounded_history_respects_count(self):
        store = _tmp_store()
        conversation_id, _ = store.resolve_conversation("operator-a", None)
        records = []
        for index in range(MAX_PROMPT_HISTORY_MESSAGES + 10):
            record = _record(
                conversation_id,
                "operator-a",
                AdvisorRole.USER,
                f"m{index}",
                message_id=f"mid-{index}",
                request_id=f"rid-{index}",
            )
            store.append_message("operator-a", conversation_id, record)
            records.append(record)
        bounded = store.bounded_history(store.read_messages("operator-a", conversation_id))
        self.assertEqual(len(bounded), MAX_PROMPT_HISTORY_MESSAGES)
        self.assertEqual(bounded[0].content, "m10")
        # Ordering remains oldest-to-newest within the selected window.
        self.assertEqual(bounded[-1].content, f"m{MAX_PROMPT_HISTORY_MESSAGES + 9}")

    def test_bounded_history_respects_character_budget(self):
        store = _tmp_store()
        conversation_id, _ = store.resolve_conversation("operator-a", None)
        for index in range(20):
            store.append_message(
                "operator-a",
                conversation_id,
                _record(
                    conversation_id,
                    "operator-a",
                    AdvisorRole.USER,
                    "z" * 3_000,
                    message_id=f"mid-{index}",
                    request_id=f"rid-{index}",
                ),
            )
        bounded = store.bounded_history(store.read_messages("operator-a", conversation_id))
        total = sum(len(m.content) for m in bounded)
        self.assertLessEqual(total, MAX_PROMPT_HISTORY_CHARACTERS)
        self.assertLessEqual(len(bounded), MAX_PROMPT_HISTORY_MESSAGES)

    def test_conversation_count_is_bounded(self):
        store = _tmp_store()
        for index in range(MAX_CONVERSATIONS_PER_OPERATOR + 3):
            conversation_id, _ = store.resolve_conversation("operator-a", None)
            store.append_message(
                "operator-a",
                conversation_id,
                _record(conversation_id, "operator-a", AdvisorRole.USER, f"c{index}"),
            )
        summaries = store.list_conversations("operator-a")
        self.assertLessEqual(len(summaries), MAX_CONVERSATIONS_PER_OPERATOR)


class SecurityTest(unittest.TestCase):
    def test_secrets_and_paths_are_not_persisted(self):
        store = _tmp_store()
        conversation_id, _ = store.resolve_conversation("operator-a", None)
        sensitive = (
            "My api_key=sk-ABCDEF1234567890 bearer abc.def.ghi "
            "password=secret /home/operator/secret.csv"
        )
        store.append_message(
            "operator-a",
            conversation_id,
            _record(
                conversation_id,
                "operator-a",
                AdvisorRole.USER,
                sensitive,
            ),
        )
        messages = store.read_messages("operator-a", conversation_id)
        stored = messages[0].content
        self.assertNotIn("sk-ABCDEF1234567890", stored)
        self.assertNotIn("api_key=", stored)
        self.assertNotIn("password=", stored)
        self.assertNotIn("/home/operator/secret.csv", stored)

    def test_only_allowlisted_fields_are_stored(self):
        store = _tmp_store()
        conversation_id, _ = store.resolve_conversation("operator-a", None)
        store.append_message(
            "operator-a",
            conversation_id,
            _record(
                conversation_id,
                "operator-a",
                AdvisorRole.USER,
                "hello",
                request_id="r1",
                response_status="VALID",
                provider_model="model-1",
            ),
        )
        record = store.read_messages("operator-a", conversation_id)[0]
        allowed = {
            "messageId", "conversationId", "operatorId", "role", "content",
            "createdAt", "requestId", "responseStatus", "providerModel",
        }
        self.assertEqual(set(AdvisorPersistedMessage.model_fields.keys()), allowed)

    def test_no_operational_object_is_persisted(self):
        store = _tmp_store()
        conversation_id, _ = store.resolve_conversation("operator-a", None)
        store.append_message(
            "operator-a",
            conversation_id,
            _record(conversation_id, "operator-a", AdvisorRole.USER, "hello"),
        )
        payload = store.read_messages("operator-a", conversation_id)[0].model_dump()
        serialized = str(payload).lower()
        for forbidden in (
            "get_status", "submit_order", "create_order", "cancel_order",
            "set_config", "money_management_boundary", "credential", "token", "cookie",
        ):
            self.assertNotIn(forbidden, serialized)


class FailureIsolationTest(unittest.TestCase):
    def test_corrupt_unwritable_store_raises_safely(self):
        store_path = os.path.join(tempfile.mkdtemp(), "conv.sqlite3")
        store = AdvisorConversationStore(store_path)
        store.resolve_conversation("operator-a", None)
        with open(store_path, "wb") as handle:
            handle.write(b"this is not a sqlite database file")
        with self.assertRaises(AdvisorConversationStoreError) as context:
            store.create_conversation("operator-a")
        self.assertEqual(
            context.exception.code,
            AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
        )

    def test_memory_failure_does_not_invoke_service(self):
        store = FailingConversationStore()
        store.errored = True
        service = RecordingService()
        app = build_gateway_app(store, service)
        client = TestClient(app)
        response = client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Hello"},
            headers=_gateway_headers(origin=ORIGIN),
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["errorCode"], "MEMORY_PERSISTENCE_ERROR")
        self.assertEqual(service.calls, 0)

    def test_gateway_never_exposes_runtime_mutators(self):
        store = FailingConversationStore()
        service = RecordingService()
        app = build_gateway_app(store, service)
        client = TestClient(app)
        response = client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Hello"},
            headers=_gateway_headers(origin=ORIGIN),
        )
        self.assertIsNotNone(response)
        self.assertNotIn("start", response.text)
        self.assertNotIn("submit", response.text)
        self.assertNotIn("cancel", response.text)

    def test_list_history_clear_fail_safely_when_store_unavailable(self):
        store = FailingConversationStore()
        store.errored = True
        service = RecordingService()
        app = build_gateway_app(store, service)
        client = TestClient(app)
        self.assertEqual(
            client.get(
                "/api/ai-advisor/conversation",
                headers=_gateway_headers(fetch_site="same-origin"),
            ).status_code, 503,
        )
        self.assertEqual(
            client.get(
                "/api/ai-advisor/conversation/history",
                params={"conversationId": "c1"},
                headers=_gateway_headers(fetch_site="same-origin"),
            ).status_code, 503,
        )
        self.assertEqual(
            client.post(
                "/api/ai-advisor/conversation/clear",
                json={"conversationId": "c1"},
                headers=_gateway_headers(origin=ORIGIN),
            ).status_code, 503,
        )


class MemoryAuthorityTest(unittest.TestCase):
    def test_store_exposes_no_operational_methods(self):
        store = _tmp_store()
        attrs = {name for name in dir(store)}
        for verb in AUTHORITY_VERBS:
            self.assertNotIn(verb, attrs, verb)

    def test_store_exposes_no_operational_fields(self):
        store = _tmp_store()
        attrs = {name for name in dir(store)}
        self.assertNotIn("submit_order", attrs)
        self.assertNotIn("execute", attrs)
        self.assertNotIn("set_config", attrs)

    def test_record_model_has_no_authority_fields(self):
        field_names = set(AdvisorPersistedMessage.model_fields.keys())
        for verb in AUTHORITY_VERBS:
            self.assertNotIn(verb, field_names, verb)

    def test_conversation_memory_authority_classification(self):
        self.assertFalse(ConversationMemoryAuthority.CARRIES_OPERATIONAL_AUTHORITY)
        self.assertEqual(
            ConversationMemoryAuthority.AUTHORITY_CLASSIFICATION,
            "CONTEXT_PERSISTENCE_ONLY",
        )


class PromptSeparationTest(unittest.TestCase):
    def _permission(self):
        return AdvisorPermissionContext(
            principalId="operator-1",
            authenticationState=AuthenticationState.AUTHENTICATED,
            authorizationState=AuthorizationState.AUTHORIZED,
            role="USER",
            permissionLevel="READ_ONLY",
            allowedCapabilities=[
                AdvisorCapability.RUNTIME_STATUS_EXPLAIN,
                AdvisorCapability.SPECIFICATION_EXPLAIN,
            ],
            dataAccessScope=[
                AdvisorDataAccessScope.SANITIZED_RUNTIME_SUMMARY,
                AdvisorDataAccessScope.APPROVED_LOCAL_SPECIFICATIONS,
            ],
            policyVersion="1.1",
            trustedServerContext=True,
        )

    def test_prompt_distinguishes_canonical_runtime_history_and_request(self):
        spec = SimpleNamespace(
            sourceId="spec-a",
            sourceVersion="1.0",
            title="Canonical Specification A",
            documentPath="docs/ai_advisor/a.md",
            loadedAt=NOW,
            contentHash="sha256:" + "a" * 64,
            approved=True,
            authorityLevel="FEATURE_SPEC",
            topics=("executionEntryAllowed",),
            excerpt=(
                "Canonical meaning of executionEntryAllowed is defined by "
                "specification."
            ),
        )
        history = (
            AdvisorConversationMessage(
                messageId="h1",
                role=AdvisorRole.USER,
                content="What was the earlier question?",
                createdAt=NOW,
                sourceReferences=(),
            ),
            AdvisorConversationMessage(
                messageId="h2",
                role=AdvisorRole.ADVISOR,
                content="Earlier answer.",
                createdAt=NOW,
                sourceReferences=(),
            ),
        )
        current = AdvisorConversationMessage(
            messageId="current-1",
            role=AdvisorRole.USER,
            content="What is the current question?",
            createdAt=NOW,
            sourceReferences=(),
        )
        context = build_advisor_context(
            generated_at=NOW,
            permission_context=self._permission(),
            runtime=AdvisorRuntimeResponse(
                bot=AdvisorBotStatus(
                    state="RUNNING", mode="PAPER", exchange="kucoin",
                    symbol="BTCUSDT",
                ),
                operation=AdvisorOperationStatus(
                    loopEnabled=True, loopState="RUNNING", autoTradeEnabled=True
                ),
                safety=AdvisorSafetyStatus(
                    emergencyLocked=False, emergencyState="READY",
                    dryRun=True, realOrderAllowed=False,
                ),
                market=AdvisorMarketStatus(
                    selectionMode="AUTO", marketReady=True, marketStale=False
                ),
                authority=AdvisorAuthorityStatus(
                    liveOrderEntryState=AdvisorExecutionEntryState.BLOCKED,
                    finalExecutionEntryState=AdvisorExecutionEntryState.ALLOWED,
                    mmExecutionEntryState=AdvisorExecutionEntryState.ALLOWED,
                ),
                moneyManagement=AdvisorMoneyManagementStatus(
                    state="RUNNING", riskState="NORMAL",
                    recommendedAction="CONTINUE",
                    executionEntryState=AdvisorExecutionEntryState.ALLOWED,
                ),
                health=AdvisorHealthStatus(healthState="HEALTHY"),
                runtime=AdvisorRuntimeMetadata(
                    capturedAt=NOW.isoformat(),
                    sourceUpdatedAt=NOW.isoformat(),
                    freshness=Freshness.FRESH,
                ),
                warnings=[],
            ),
            specifications=(spec,),
            conversation_history=history,
            current_message=current,
        )
        prompt = build_advisor_prompt(
            request=AdvisorRequest(
                schemaVersion="1.0",
                requestId="request-1",
                messageId="current-1",
                message="What is the current question?",
                locale="en-US",
                requestedAt=NOW,
                permissionContext=self._permission(),
                contextEnvelope=context,
                responsePreferences=None,
            ),
            context=context,
            policy=AdvisorPromptPolicy(),
        )
        sections = {item.sectionType: item for item in prompt.contextSections}
        history_section = sections[AdvisorPromptSectionType.CONVERSATION_CONTEXT]
        runtime_section = sections[AdvisorPromptSectionType.RUNTIME_CONTEXT]
        spec_section = sections[AdvisorPromptSectionType.SPECIFICATION_REFERENCE]
        request_section = sections[AdvisorPromptSectionType.CURRENT_REQUEST]

        self.assertIn("classification=UNTRUSTED CONVERSATION DATA", history_section.content)
        self.assertIn("What was the earlier question?", history_section.content)
        self.assertIn("Earlier answer.", history_section.content)
        self.assertNotIn("Canonical meaning of executionEntryAllowed",
                         history_section.content)
        self.assertIn("botState=RUNNING", runtime_section.content)
        self.assertIn("Canonical Specification A", spec_section.content)
        self.assertIn("What is the current question?", request_section.content)
        self.assertIn("classification=UNTRUSTED CURRENT REQUEST DATA",
                      request_section.content)


class GatewayIntegrationTest(unittest.TestCase):
    def test_conversation_persists_and_round_trips(self):
        store = _tmp_store()
        service = RecordingService()
        app = build_gateway_app(store, service)
        client = TestClient(app)

        first = client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "First question"},
            headers=_gateway_headers(origin=ORIGIN),
        )
        self.assertEqual(first.status_code, 200)
        body = first.json()
        conversation_id = body["conversationId"]
        self.assertIsInstance(conversation_id, str)
        self.assertEqual(body["advisorResponse"]["summary"], "Safe answer.")
        self.assertEqual(service.last_input.contextInput.conversationHistory, ())

        second = client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Second question", "conversationId": conversation_id},
            headers=_gateway_headers(origin=ORIGIN),
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["conversationId"], conversation_id)
        history = service.last_input.contextInput.conversationHistory
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].content, "First question")
        self.assertEqual(history[1].content, "Safe answer.")

        history_response = client.get(
            "/api/ai-advisor/conversation/history",
            params={"conversationId": conversation_id},
            headers=_gateway_headers(fetch_site="same-origin"),
        )
        messages = history_response.json()["messages"]
        self.assertEqual(
            [m["content"] for m in messages],
            ["First question", "Safe answer.", "Second question", "Safe answer."],
        )

    def test_clear_is_scoped_and_list_returns_only_owned(self):
        store = _tmp_store()
        service = RecordingService()
        app = build_gateway_app(store, service)
        client = TestClient(app)

        created = client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Hello"},
            headers=_gateway_headers("operator-a", origin=ORIGIN),
        ).json()["conversationId"]

        self.assertEqual(
            client.post(
                "/api/ai-advisor/conversation/clear",
                json={"conversationId": created},
                headers=_gateway_headers("operator-b", origin=ORIGIN),
            ).json()["cleared"], False,
        )
        self.assertEqual(
            len(client.get(
                "/api/ai-advisor/conversation",
                headers=_gateway_headers("operator-b", fetch_site="same-origin"),
            ).json()["conversations"]), 0,
        )
        cleared = client.post(
            "/api/ai-advisor/conversation/clear",
            json={"conversationId": created},
            headers=_gateway_headers("operator-a", origin=ORIGIN),
        ).json()
        self.assertTrue(cleared["cleared"])
        self.assertEqual(
            client.get(
                "/api/ai-advisor/conversation",
                headers=_gateway_headers("operator-a", fetch_site="same-origin"),
            ).json()["conversations"], [],
        )

    def test_failed_provider_rolls_back_user_message(self):
        store = _tmp_store()
        service = RecordingService(_failed_result)
        app = build_gateway_app(store, service)
        client = TestClient(app)
        response = client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Will fail"},
            headers=_gateway_headers(origin=ORIGIN),
        )
        self.assertEqual(response.status_code, 503)
        conversation_id = response.json().get("conversationId")
        if conversation_id is None:
            pending = store.list_conversations("operator-1")
            self.assertEqual(len(pending), 1)
            conversation_id = pending[0].conversationId
        # A failed provider must not leave a dangling user message.
        self.assertEqual(
            [m.content for m in store.read_messages("operator-1", conversation_id)],
            [],
        )

    def test_foreign_conversation_on_post_fails_closed(self):
        store = _tmp_store()
        service = RecordingService()
        app = build_gateway_app(store, service)
        client = TestClient(app)
        created = client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "owner"},
            headers=_gateway_headers("operator-a", origin=ORIGIN),
        ).json()["conversationId"]
        calls_after_owner = service.calls
        self.assertEqual(calls_after_owner, 1)
        forbidden = client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "intruder", "conversationId": created},
            headers=_gateway_headers("operator-b", origin=ORIGIN),
        )
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(forbidden.json()["errorCode"], "AUTHORIZATION_DENIED")
        self.assertEqual(service.calls, calls_after_owner)


class BrowserInputIntegrationTest(unittest.TestCase):
    def test_assemble_accepts_bounded_history(self):
        history = (
            AdvisorConversationMessage(
                messageId="h1", role=AdvisorRole.USER,
                content="prior", createdAt=NOW, sourceReferences=(),
            ),
        )
        service_input = assemble_browser_service_input(
            prompt="current",
            principal_id="operator-1",
            now=NOW,
            request_id="req-1",
            conversation_history=history,
        )
        self.assertEqual(
            service_input.contextInput.conversationHistory, history
        )
        contents = {
            item.content
            for item in service_input.request.contextEnvelope.conversationHistory
        }
        self.assertIn("prior", contents)
        self.assertIn("current", contents)


if __name__ == "__main__":
    unittest.main()
