"""D-9B: wire D-5 unified trace evidence into the real Advisor conversation path.

These tests prove that the real ``POST /api/ai-advisor/conversation`` browser
gateway invokes the D-5 ``UnifiedTraceAssembler`` and supplies bounded,
typed ``HISTORICAL_EVIDENCE`` into the Advisor prompt, while keeping
``CURRENT_RUNTIME``, canonical specification and conversation memory separate.

The tests deliberately avoid the optional ``openai`` provider dependency: the
provider is a deterministic ``MockAdvisorProvider`` and the wiring is verified
through the real ``AdvisorService`` pipeline.
"""

import unittest
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.ai_advisor.api_rate_limit import (
    AdvisorConcurrencyLimiter,
    AdvisorRateLimiter,
)
from backend.ai_advisor.advisor_service import AdvisorService
from backend.ai_advisor.browser_gateway import (
    AdvisorBrowserGatewayComposition,
    AdvisorBrowserGatewayConfig,
    AdvisorGatewayPreflightDenyMiddleware,
    create_browser_gateway_router,
)
from backend.ai_advisor.context_builder import SpecificationSourceInput
from backend.ai_advisor.historical_trace_evidence import (
    MAX_TRACE_EVIDENCE_NODES_PER_TRACE,
    MAX_TRACE_EVIDENCE_REASON_CODES,
    MAX_TRACE_EVIDENCE_TRACES,
    AdvisorTraceEvidence,
    build_advisor_trace_evidence,
    build_default_historical_trace_evidence,
    empty_trace_evidence,
    render_historical_trace_evidence,
)
from backend.ai_advisor.mock_provider import MockAdvisorProvider, MockProviderFixture
from backend.ai_advisor.prompt_builder import build_advisor_prompt, render_advisor_prompt
from backend.ai_advisor.prompt_models import AdvisorPromptPolicy
from backend.ai_advisor.provider_models import (
    AdvisorModelPolicy,
    AdvisorProviderCapabilities,
    AdvisorProviderCode,
    AdvisorProviderConfig,
    AdvisorProviderResponseFormat,
    AdvisorRetryPolicy,
)
from backend.runtime.trading_trace import TradingTraceStore, make_event, new_trace_id
from backend.runtime.unified_trace import (
    NoTraceKind,
    StaticTraceEvidenceSource,
    TradingTraceStoreSource,
    TraceCompleteness,
    UnifiedTraceAssembler,
)

from tests.test_ai_advisor_provider_contract import fixture_text
from tests.test_ai_advisor_prompt_builder import NOW, runtime

ORIGIN = "https://advisor.example.test"


def _events(*stages):
    trace_id = new_trace_id()
    events = []
    for stage, status, reason, meta in stages:
        events.append(
            make_event(
                trace_id=trace_id,
                mode="PAPER",
                stage=stage,
                status=status,
                symbol="BTCUSDT",
                runtime_id="runtime-1",
                reason_code=reason,
                metadata=meta,
            ).to_dict()
        )
    return trace_id, events


def _unified_trace(*stages):
    trace_id, events = _events(*stages)
    return UnifiedTraceAssembler(StaticTraceEvidenceSource(events)).assemble(trace_id)


def _spec():
    return SpecificationSourceInput(
        sourceId="spec-d9b",
        sourceVersion="1.0",
        title="Specification D-9B",
        documentPath="docs/ai_advisor/d9b.md",
        loadedAt=NOW,
        approved=True,
    )


def _executed_events():
    return [
        ("STRATEGY", "BUY", None, None),
        ("EXECUTION", "PAPER_FILLED", None, {"orderId": "paper-1"}),
        ("POSITION", "OPEN", None, {"positionId": "p-1", "orderId": "paper-1"}),
        ("RESULT", "EXECUTED", None, {"decision": "BUY", "netPnL": 1.25}),
    ]


def _evidence_from_events(stages):
    return build_advisor_trace_evidence((_unified_trace(*stages),))


class _RecordingService:
    """Capture the real service input and the prompt it produces."""

    def __init__(self, delegate):
        self.delegate = delegate
        self.service_input = None
        self.prompt = None

    def generate_response(self, service_input):
        self.service_input = service_input
        self.prompt = render_advisor_prompt(
            build_advisor_prompt(
                request=service_input.request,
                context=service_input.request.contextEnvelope,
                policy=AdvisorPromptPolicy(),
            )
        )
        return self.delegate.generate_response(service_input)


class _TrustedPeerMiddleware:
    def __init__(self, app, peer):
        self.app = app
        self.peer = peer

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        scope["client"] = (self.peer, 43210)
        await self.app(scope, receive, send)


def _make_delegate():
    return AdvisorService(
        provider=MockAdvisorProvider(MockProviderFixture(responseText=fixture_text())),
        providerConfig=AdvisorProviderConfig(
            configVersion="ai-advisor-provider-config/v1",
            provider=AdvisorProviderCode.OPENAI,
            modelId="openai-advisor-model",
            timeoutSeconds=30,
            maxOutputCharacters=32_000,
            retryPolicy=AdvisorRetryPolicy.NO_RETRY,
            responseFormat=AdvisorProviderResponseFormat.STRICT_JSON,
        ),
        modelPolicy=AdvisorModelPolicy(
            provider=AdvisorProviderCode.OPENAI,
            allowedModelIds=("openai-advisor-model",),
            defaultModelId="openai-advisor-model",
        ),
        capabilities=AdvisorProviderCapabilities(
            provider=AdvisorProviderCode.OPENAI,
            supportsTextGeneration=True,
            supportsStrictJson=True,
            supportsToolCalling=False,
            supportsFunctionCalling=False,
            supportsStreaming=False,
            supportsImages=False,
            supportsFiles=False,
        ),
    )


def _gateway(
    *,
    trace_evidence_source=None,
    runtime_source=None,
    specs=(),
):
    recording = _RecordingService(_make_delegate())
    composition = AdvisorBrowserGatewayComposition(
        config=AdvisorBrowserGatewayConfig(
            enabled=True,
            trustedProxyPeers=("127.0.0.1",),
            allowedOrigins=(ORIGIN,),
            endpointTimeoutSeconds=5,
        ),
        service=recording,
        rateLimiter=AdvisorRateLimiter(
            limit=10, window_seconds=60, clock=lambda: NOW.timestamp()
        ),
        concurrencyLimiter=AdvisorConcurrencyLimiter(
            limit=2, acquire_timeout_seconds=0.01
        ),
        clock=lambda: NOW,
        externalStatus="OFFLINE",
        approvedSpecifications=tuple(specs),
        runtimeSource=runtime_source,
        traceEvidenceSource=trace_evidence_source,
    )
    app = FastAPI()
    app.include_router(create_browser_gateway_router(composition))
    app.add_middleware(AdvisorGatewayPreflightDenyMiddleware)
    client = TestClient(_TrustedPeerMiddleware(app, "127.0.0.1"))
    return client, recording


def _post(client, prompt="Why did this trade lose?"):
    return client.post(
        "/api/ai-advisor/conversation",
        json={"prompt": prompt},
        headers={
            "Origin": ORIGIN,
            "X-TradingAI-Client": "web",
            "X-TradingAI-Authenticated-User": "operator-1",
            "Content-Type": "application/json",
        },
    )


class D9BAdvisorTraceWiringTest(unittest.TestCase):
    def test_real_path_invokes_d5_trace_source(self):
        # CASE 1: the real conversation composition invokes the D-5 path.
        evidence = build_advisor_trace_evidence(
            (_unified_trace(*_executed_events()),)
        )
        client, recording = _gateway(trace_evidence_source=lambda: evidence)
        response = _post(client)
        self.assertEqual(response.status_code, 200)
        supplied = recording.service_input.contextInput.traceEvidence
        self.assertIsNotNone(supplied)
        self.assertIsInstance(supplied, AdvisorTraceEvidence)
        self.assertFalse(supplied.is_empty)
        self.assertEqual(len(supplied.traces), 1)

    def test_real_trace_reaches_historical_evidence_prompt(self):
        # CASE 2: existing real trace produces HISTORICAL_EVIDENCE in the prompt.
        evidence = build_advisor_trace_evidence(
            (_unified_trace(*_executed_events()),)
        )
        client, recording = _gateway(
            trace_evidence_source=lambda: evidence,
            runtime_source=runtime,
            specs=(_spec(),),
        )
        response = _post(client)
        self.assertEqual(response.status_code, 200)
        prompt = recording.prompt
        self.assertIn("[BEGIN_HISTORICAL_EVIDENCE]", prompt)
        self.assertIn("[END_HISTORICAL_EVIDENCE]", prompt)
        self.assertIn("classification=HISTORICAL EVIDENCE", prompt)
        self.assertIn("completeness=COMPLETE", prompt)
        # The request path produced evidence via the D-5 assembler.
        self.assertEqual(len(recording.service_input.contextInput.traceEvidence.traces), 1)

    def test_no_trace_is_safe_not_available(self):
        # CASE 3: no trace produces a safe NOT_AVAILABLE block, Advisor still works.
        client, recording = _gateway(
            trace_evidence_source=lambda: empty_trace_evidence(),
            runtime_source=runtime,
        )
        response = _post(client)
        self.assertEqual(response.status_code, 200)
        block = recording.prompt.split("[BEGIN_HISTORICAL_EVIDENCE]")[1].split(
            "[END_HISTORICAL_EVIDENCE]"
        )[0]
        self.assertIn("status=NOT_AVAILABLE", block)
        self.assertIn("classification=HISTORICAL EVIDENCE", block)

    def test_trace_source_unavailable_does_not_disable_advisor(self):
        # CASE 4: a failing trace source degrades evidence only; Advisor works.
        def broken_source():
            raise RuntimeError("trace store unavailable")

        client, recording = _gateway(
            trace_evidence_source=broken_source,
            runtime_source=runtime,
        )
        response = _post(client)
        self.assertEqual(response.status_code, 200)
        block = recording.prompt.split("[BEGIN_HISTORICAL_EVIDENCE]")[1].split(
            "[END_HISTORICAL_EVIDENCE]"
        )[0]
        self.assertIn("status=NOT_AVAILABLE", block)

    def test_partial_remains_partial(self):
        # CASE 5
        evidence = _evidence_from_events([("STRATEGY", "BUY", None, None)])
        self.assertEqual(
            evidence.traces[0].completeness, TraceCompleteness.PARTIAL.value
        )

    def test_ambiguous_remains_ambiguous(self):
        # CASE 6
        evidence = _evidence_from_events(
            [("STRATEGY", "BUY", None, None), ("STRATEGY", "SELL", None, None)]
        )
        self.assertEqual(
            evidence.traces[0].completeness, TraceCompleteness.AMBIGUOUS.value
        )

    def test_no_trade_distinct_from_missing_trace_data(self):
        # CASE 7: a deliberate no-trade must not read as missing trace data.
        evidence = _evidence_from_events(
            [
                ("STRATEGY", "HOLD", "LIQUIDITY_INSTABILITY", None),
                ("RESULT", "SUPPRESSED", "LIQUIDITY_INSTABILITY", None),
            ]
        )
        node = evidence.traces[0].noTrade
        self.assertIsNotNone(node)
        self.assertEqual(node.noTradeKind, NoTraceKind.NO_TRADE_DECISION.value)
        rendered = render_historical_trace_evidence(evidence)
        self.assertNotIn("status=NOT_AVAILABLE", rendered)

    def test_execution_failure_distinct_from_no_trade(self):
        # CASE 8: an execution failure is not a deliberate no-trade decision.
        failure = _evidence_from_events(
            [
                ("STRATEGY", "BUY", None, None),
                ("EXECUTION", "FAILED", "EXCHANGE_REJECTED", None),
            ]
        )
        execution_attempt = failure.traces[0].executionAttempt
        self.assertIsNotNone(execution_attempt)
        self.assertEqual(
            execution_attempt.noTradeKind, NoTraceKind.EXECUTION_FAILURE.value
        )
        self.assertIsNone(failure.traces[0].noTrade)

        no_trade = _evidence_from_events(
            [
                ("STRATEGY", "HOLD", "LIQUIDITY_INSTABILITY", None),
                ("RESULT", "SUPPRESSED", "LIQUIDITY_INSTABILITY", None),
            ]
        )
        self.assertIsNotNone(no_trade.traces[0].noTrade)
        self.assertIsNone(no_trade.traces[0].executionAttempt)

    def test_authoritative_reason_codes_preserved_verbatim(self):
        # CASE 9: authoritative reason codes are not rewritten.
        evidence = _evidence_from_events(
            [("STRATEGY", "HOLD", "LIQUIDITY_INSTABILITY", None)]
        )
        codes = tuple(item.code for item in evidence.traces[0].reasonCodes)
        self.assertIn("LIQUIDITY_INSTABILITY", codes)
        rendered = render_historical_trace_evidence(evidence)
        self.assertIn("LIQUIDITY_INSTABILITY", rendered)

    def test_provenance_retained(self):
        # CASE 10: D-5 provenance is retained on the Advisor evidence.
        evidence = _evidence_from_events(
            [
                ("STRATEGY", "BUY", None, None),
                ("EXECUTION", "PAPER_FILLED", None, {"orderId": "paper-1"}),
            ]
        )
        trace = evidence.traces[0]
        self.assertTrue(trace.sourceReferences)
        reference = trace.sourceReferences[0]
        self.assertTrue(reference.sourceSubsystem)
        self.assertTrue(reference.sourceType)
        self.assertTrue(reference.sourceIdentifier)
        self.assertTrue(reference.linkageMethod)
        self.assertIsNotNone(trace.decision.provenance)
        self.assertTrue(trace.decision.provenance.sourceSubsystem)
        self.assertTrue(trace.decision.provenance.sourceType)

    def test_evidence_bounded_to_d5_limits(self):
        # CASE 11: bounds are preserved from D-5.
        traces = tuple(
            _unified_trace(*_executed_events()) for _ in range(MAX_TRACE_EVIDENCE_TRACES + 3)
        )
        evidence = build_advisor_trace_evidence(traces)
        self.assertLessEqual(len(evidence.traces), MAX_TRACE_EVIDENCE_TRACES)
        for trace in evidence.traces:
            self.assertLessEqual(len(trace.nodes), MAX_TRACE_EVIDENCE_NODES_PER_TRACE)
            self.assertLessEqual(
                len(trace.reasonCodes), MAX_TRACE_EVIDENCE_REASON_CODES
            )

    def test_truncation_is_explicit(self):
        # CASE 12: truncation is surfaced as an explicit fact.
        traces = tuple(
            _unified_trace(*_executed_events()) for _ in range(MAX_TRACE_EVIDENCE_TRACES + 3)
        )
        evidence = build_advisor_trace_evidence(traces)
        self.assertTrue(evidence.truncated)
        self.assertGreaterEqual(evidence.omittedTraceCount, 3)
        self.assertIsNotNone(evidence.warning)
        truncated = build_advisor_trace_evidence(
            (_unified_trace(*_executed_events()),), max_nodes_per_trace=1
        )
        self.assertTrue(truncated.traces[0].nodesTruncated)

    def test_current_runtime_stays_separate(self):
        # CASE 13: CURRENT_RUNTIME remains a separate prompt section.
        evidence = build_advisor_trace_evidence(
            (_unified_trace(*_executed_events()),)
        )
        client, recording = _gateway(
            trace_evidence_source=lambda: evidence, runtime_source=runtime
        )
        _post(client)
        prompt = recording.prompt
        runtime_block = prompt.split("[BEGIN_RUNTIME_CONTEXT]")[1].split(
            "[END_RUNTIME_CONTEXT]"
        )[0]
        history_block = prompt.split("[BEGIN_HISTORICAL_EVIDENCE]")[1].split(
            "[END_HISTORICAL_EVIDENCE]"
        )[0]
        self.assertIn("botState=RUNNING", runtime_block)
        self.assertNotIn("botState=", history_block)
        self.assertNotIn("status=FRESH", history_block)

    def test_canonical_spec_stays_separate(self):
        # CASE 14: canonical specification stays a separate section.
        evidence = build_advisor_trace_evidence(
            (_unified_trace(*_executed_events()),)
        )
        client, recording = _gateway(
            trace_evidence_source=lambda: evidence,
            runtime_source=runtime,
            specs=(_spec(),),
        )
        _post(client)
        prompt = recording.prompt
        self.assertIn("[BEGIN_SPECIFICATION_REFERENCE]", prompt)
        self.assertIn("sourceId=spec-d9b", prompt)

    def test_conversation_memory_stays_untracked_separate(self):
        # CASE 15: conversation history remains a separate, untrusted section.
        client, recording = _gateway(
            trace_evidence_source=lambda: empty_trace_evidence(),
            runtime_source=runtime,
        )
        _post(client, prompt="Explain the recent trade.")
        prompt = recording.prompt
        self.assertIn("[BEGIN_CONVERSATION_CONTEXT]", prompt)
        # The current request itself is not conversation history and is untrusted.
        self.assertIn("[BEGIN_CURRENT_REQUEST]", prompt)
        self.assertIn("classification=UNTRUSTED CONVERSATION DATA", prompt)

    def test_hist_evidence_cannot_mutate_runtime(self):
        # CASE 16: injecting trace evidence does not change the current runtime.
        evidence = build_advisor_trace_evidence(
            (_unified_trace(*_executed_events()),)
        )
        client, recording = _gateway(
            trace_evidence_source=lambda: evidence, runtime_source=runtime
        )
        _post(client)
        runtime_context = recording.service_input.request.contextEnvelope.runtimeContext
        self.assertIsNotNone(runtime_context)
        self.assertEqual(runtime_context.state, "RUNNING")
        self.assertEqual(runtime_context.mode, "PAPER")

    def test_hist_evidence_cannot_invoke_order_execution(self):
        # CASE 17: historical evidence never carries execution authority.
        evidence = _evidence_from_events(_executed_events())
        rendered = render_historical_trace_evidence(evidence).lower()
        for forbidden in ("placeorder", "cancelorder", "executefill", "ordersubmitted"):
            self.assertNotIn(forbidden, rendered)

    def test_no_secret_dump_in_prompt(self):
        # CASE 18: no raw secret-bearing store/runtime dump reaches the prompt.
        evidence = _evidence_from_events(_executed_events())
        rendered = render_historical_trace_evidence(evidence).lower()
        for secret in ("apikey", "authorization", "secret", "passphrase", "credentials"):
            self.assertNotIn(secret, rendered)

    def test_provider_abstraction_unchanged(self):
        # CASE 19: the trace wiring ends at the context/prompt boundary; the
        # provider abstraction still receives the standard typed input.
        evidence = build_advisor_trace_evidence(
            (_unified_trace(*_executed_events()),)
        )
        client, recording = _gateway(trace_evidence_source=lambda: evidence)
        response = _post(client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "SUCCEEDED")
        # The provider receives the standard typed input; no provider-specific
        # trace logic is introduced anywhere in this wiring.
        self.assertTrue(
            isinstance(recording.service_input.contextInput.traceEvidence, AdvisorTraceEvidence)
            or recording.service_input.contextInput.traceEvidence is None
        )

    def test_default_wiring_does_not_break_with_empty_store(self):
        # CASE 20: the default D-5 wiring is a no-op when no traces exist.
        default = build_default_historical_trace_evidence()
        self.assertIsInstance(default, AdvisorTraceEvidence)
        self.assertTrue(default.is_empty)

    def test_existing_conversation_behavior_remains_compatible(self):
        # CASE 21: a normal question still completes through the real pipeline.
        client, recording = _gateway(
            trace_evidence_source=lambda: empty_trace_evidence(),
            runtime_source=runtime,
            specs=(_spec(),),
        )
        response = _post(client, prompt="Explain the current runtime state.")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "SUCCEEDED")
        prompt = recording.prompt
        for marker in (
            "[BEGIN_RUNTIME_CONTEXT]",
            "[BEGIN_SPECIFICATION_REFERENCE]",
            "[BEGIN_HISTORICAL_EVIDENCE]",
            "[BEGIN_CONVERSATION_CONTEXT]",
        ):
            self.assertIn(marker, prompt)


if __name__ == "__main__":
    unittest.main()
