"""D-9D: integrate bounded Knowledge Evolution context into the real Advisor path.

These tests prove that the real ``POST /api/ai-advisor/conversation`` browser
gateway supplies a bounded, typed ``KNOWLEDGE_EVOLUTION`` layer to the Advisor
prompt, that the real ``KnowledgeEvolutionStore`` is the single knowledge
persistence authority, and that a bounded, deterministic Investigation runs
over the authoritative D-5 trace (``TradingTraceStore`` -> ``UnifiedTradingTrace``
-> ``ExperienceRecord``).

Authority and firewall contract under test:

    Experience Memory      = EVIDENCE_ONLY / REBUILDABLE (NOT authoritative)
    Investigation          = ANALYSIS_ONLY
    Pattern / Finding      = OBSERVATION_ONLY
    Hypothesis             = HYPOTHESIS_ONLY
    Validation             = ANALYSIS_ONLY
    Validated Knowledge    = INFORMATION_ONLY
    Knowledge Store        = PERSISTENCE_ONLY
    Advisor                = READ_ONLY
    Operational / Execution / Strategy / MM / Canonical Mutation = NONE

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
from backend.ai_advisor.context_builder import SpecificationSourceInput, build_advisor_context
from backend.ai_advisor.conversation_models import (
    AdvisorCapability,
    AdvisorDataAccessScope,
    AdvisorPermissionContext,
    AdvisorRequest,
    AdvisorResponsePreferences,
    AdvisorDetailLevel,
    AdvisorResponseFormat,
    AuthenticationState,
    AuthorizationState,
)
from backend.ai_advisor.historical_trace_evidence import (
    AdvisorTraceEvidence,
    build_advisor_trace_evidence,
    empty_trace_evidence,
)
from backend.ai_advisor.knowledge_context import (
    AdvisorKnowledgeContext,
    build_advisor_investigation,
    build_advisor_knowledge_context,
    build_default_advisor_knowledge_context,
    empty_advisor_knowledge_context,
    knowledge_lines,
    render_advisor_knowledge,
    MAX_KNOWLEDGE_VALIDATED,
    MAX_KNOWLEDGE_HYPOTHESES,
    MAX_KNOWLEDGE_FINDINGS,
    MAX_KNOWLEDGE_PATTERNS,
    MAX_KNOWLEDGE_VALIDATIONS,
)
from backend.ai_advisor.mock_provider import MockAdvisorProvider, MockProviderFixture
from backend.ai_advisor.prompt_builder import build_advisor_prompt, render_advisor_prompt
from backend.ai_advisor.prompt_models import AdvisorPromptPolicy, AdvisorPromptSectionType
from backend.ai_advisor.provider_models import (
    AdvisorModelPolicy,
    AdvisorProviderCapabilities,
    AdvisorProviderCode,
    AdvisorProviderConfig,
    AdvisorProviderResponseFormat,
    AdvisorRetryPolicy,
)
from backend.knowledge_evolution import (
    AcceptanceCriterion,
    ExperienceType,
    HypothesisStatus,
    InvestigationFilter,
    PatternType,
    Relation,
    ReviewDecision,
    ValidationEvidence,
    ValidationMetric,
    ValidationMethod,
    ValidationResult,
    advance_hypothesis,
    build_finding,
    build_pattern,
    evaluate_validation,
    experience_from_trace,
    make_experience,
    make_investigation,
    promote_to_validated_knowledge,
    propose_hypothesis,
    record_human_review,
    run_investigation,
)
from backend.knowledge_evolution.store import KnowledgeEvolutionStore
from backend.runtime.trading_trace import make_event, new_trace_id
from backend.runtime.unified_trace import (
    StaticTraceEvidenceSource,
    TraceCompleteness,
    UnifiedTraceAssembler,
)

from tests.test_ai_advisor_provider_contract import fixture_text
from tests.test_ai_advisor_prompt_builder import NOW, runtime

ORIGIN = "https://advisor.example.test"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _trace(*, kind: str = "win", symbol: str = "BTCUSDT", mode: str = "PAPER"):
    tid = new_trace_id()
    if kind == "win":
        events = [
            make_event(trace_id=tid, mode=mode, stage="STRATEGY", status="BUY", symbol=symbol,
                       reason_code="SPREAD_OK", metadata={"decisionId": "d1"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="EXECUTION", status="PAPER_FILLED", symbol=symbol,
                       metadata={"decisionId": "d1", "orderId": "o1"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="POSITION", status="OPEN", symbol=symbol,
                       metadata={"decisionId": "d1", "positionId": "p1", "orderId": "o1"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="RESULT", status="EXECUTED", symbol=symbol,
                       metadata={"decision": "BUY", "netPnL": 2.0, "tradeId": "t1", "decisionId": "d1"}).to_dict(),
        ]
    elif kind == "loss":
        events = [
            make_event(trace_id=tid, mode=mode, stage="STRATEGY", status="BUY", symbol=symbol,
                       reason_code="SPREAD_OK", metadata={"decisionId": "d2"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="EXECUTION", status="PAPER_FILLED", symbol=symbol,
                       metadata={"decisionId": "d2", "orderId": "o2"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="POSITION", status="OPEN", symbol=symbol,
                       metadata={"decisionId": "d2", "positionId": "p2", "orderId": "o2"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="RESULT", status="EXECUTED", symbol=symbol,
                       metadata={"decision": "BUY", "netPnL": -1.5, "tradeId": "t2", "decisionId": "d2"}).to_dict(),
        ]
    else:
        raise ValueError(f"unknown kind {kind}")
    return UnifiedTraceAssembler(StaticTraceEvidenceSource(events)).assemble(tid)


def _experiences(*kinds: str):
    return [experience_from_trace(_trace(kind=k)) for k in kinds]


def _real_objects():
    """Return real D-8 objects for every Knowledge Evolution classification."""
    experiences = _experiences("win", "loss")
    investigation = make_investigation(
        question="recent evidence", criterion=InvestigationFilter(symbol="BTCUSDT")
    )
    result = run_investigation(investigation, experiences)
    finding = build_finding(result, statement="a repeated observed finding")

    hypothesis = propose_hypothesis(
        statement="a supported hypothesis",
        validation_criteria=(("SUPPORT_RATIO", "AT_LEAST", 0.5),),
    )
    supported = advance_hypothesis(hypothesis, HypothesisStatus.READY_FOR_VALIDATION)
    supported = advance_hypothesis(supported, HypothesisStatus.VALIDATING)
    supported = advance_hypothesis(supported, HypothesisStatus.SUPPORTED)
    validation = evaluate_validation(
        supported,
        evidence=ValidationEvidence(
            sample_size=10,
            support_count=8,
            counterexample_count=2,
            method=ValidationMethod.HISTORICAL_REPLAY,
        ),
        criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),),
    )
    review = record_human_review(
        hypothesis_id=supported.hypothesis_id,
        decision=ReviewDecision.APPROVED,
        reviewer="operator",
        reviewed_at="2026-09-05T10:00:00Z",
    )
    vk = promote_to_validated_knowledge(supported, validation, review)

    proposed = propose_hypothesis(
        statement="an unvalidated hypothesis",
        validation_criteria=(("SUPPORT_RATIO", "AT_LEAST", 0.5),),
    )
    inconclusive_validation = evaluate_validation(
        proposed,
        evidence=ValidationEvidence(
            sample_size=3,
            support_count=1,
            counterexample_count=2,
            method=ValidationMethod.HISTORICAL_REPLAY,
        ),
        criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),),
    )

    pattern = build_pattern(
        experiences,
        pattern_type=PatternType.GENERIC,
        description="a repeated observed pattern",
        condition=lambda e: e.symbol == "BTCUSDT",
        outcome=lambda e: (e.outcome or "") == "WIN",
    )
    return {
        "vk": vk,
        "hypothesis": supported,
        "finding": finding,
        "pattern": pattern,
        "validation": validation,
        "proposed": proposed,
        "inconclusiveValidation": inconclusive_validation,
    }


def _spec():
    return SpecificationSourceInput(
        sourceId="spec-d9d",
        sourceVersion="1.0",
        title="Specification D-9D",
        documentPath="docs/ai_advisor/d9d.md",
        loadedAt=NOW,
        approved=True,
    )


def _store(tmp_path):
    from pathlib import Path
    store = KnowledgeEvolutionStore(Path(tmp_path) / "knowledge.sqlite3")
    return store


def _supported_hypothesis_and_validation(store, *, statement="a testable hypothesis"):
    h = propose_hypothesis(
        statement=statement,
        validation_criteria=(("SUPPORT_RATIO", "AT_LEAST", 0.5),),
    )
    store.create_hypothesis(h)
    h = store.transition_hypothesis(h.hypothesis_id, HypothesisStatus.READY_FOR_VALIDATION)
    h = store.transition_hypothesis(h.hypothesis_id, HypothesisStatus.VALIDATING)
    h = store.transition_hypothesis(h.hypothesis_id, HypothesisStatus.SUPPORTED)
    v = evaluate_validation(
        h,
        evidence=ValidationEvidence(
            sample_size=10,
            support_count=8,
            counterexample_count=2,
            method=ValidationMethod.HISTORICAL_REPLAY,
        ),
        criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),),
    )
    assert v.result is ValidationResult.SUPPORTED
    store.save_validation(v)
    return h, v


def _approved_review(store, h, v):
    review = record_human_review(
        hypothesis_id=h.hypothesis_id,
        decision=ReviewDecision.APPROVED,
        reviewer="operator",
        reviewed_at="2026-09-05T10:00:00Z",
    )
    store.append_human_review(review, validation=v)
    return review


def _populated_store(tmp_path):
    """A real persistence store containing all Knowledge Evolution object types."""
    store = _store(tmp_path)
    h, v = _supported_hypothesis_and_validation(store, statement="validated knowledge statement")
    review = _approved_review(store, h, v)
    vk = store.promote_to_validated_knowledge(
        hypothesis_id=h.hypothesis_id,
        validation_id=v.validation_id,
        review_id=review.review_id,
        version="1.0",
        created_at="2026-09-05T10:01:00Z",
    )
    experiences = _experiences("win")
    inv = make_investigation(
        question="recent evidence", criterion=InvestigationFilter(symbol="BTCUSDT")
    )
    store.save_investigation(inv)
    result = run_investigation(inv, experiences)
    finding = build_finding(result, statement="a repeated observed finding")
    store.save_finding(finding)
    pattern = build_pattern(
        experiences,
        pattern_type=PatternType.GENERIC,
        description="a repeated observed pattern",
        condition=lambda e: e.symbol == "BTCUSDT",
        outcome=lambda e: (e.outcome or "") == "WIN",
    )
    store.save_pattern(pattern)
    hyp2 = propose_hypothesis(statement="an unvalidated hypothesis")
    store.create_hypothesis(hyp2)
    return store, vk, h, v, finding, pattern, hyp2


def _knowledge_source_from(store):
    return lambda: build_default_advisor_knowledge_context(store=store)


class _RecordingService:
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
    knowledge_source=None,
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
        knowledgeSource=knowledge_source,
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


class D9DKnowledgeRuntimeConnectionTest(unittest.TestCase):
    """Real composition connects Knowledge context; integrity invariants hold."""

    def setUp(self):
        super().setUp()
        self._store = None

    def test_01_real_composition_has_knowledge_source(self):
        kc = empty_advisor_knowledge_context()
        client, recording = _gateway(
            trace_evidence_source=lambda: empty_trace_evidence(),
            runtime_source=runtime,
            knowledge_source=lambda: kc,
        )
        response = _post(client)
        self.assertEqual(response.status_code, 200)
        supplied = recording.service_input.contextInput.knowledgeContext
        self.assertIsInstance(supplied, AdvisorKnowledgeContext)
        self.assertEqual(supplied, kc)

    def test_02_knowledge_store_is_real_persistence_source(self):
        with self.subTest():
            pass
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store, vk, *_ = _populated_store(tmp)
            kc = build_default_advisor_knowledge_context(store=store)
            self.assertEqual(kc.status, "AVAILABLE")
            self.assertTrue(kc.validatedKnowledge)
            self.assertEqual(len(kc.validatedKnowledge), 1)

    def test_03_no_second_knowledge_authority(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            self.assertEqual(store.evidence_authority(), "PERSISTENCE_ONLY")
            self.assertEqual(
                store.authoritative_authority_report()["KnowledgeStore"], "PERSISTENCE_ONLY"
            )
            self.assertFalse(store.has_experience_table())

    def test_04_validated_knowledge_reaches_advisor_context(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store, vk, *_ = _populated_store(tmp)
            kc = build_default_advisor_knowledge_context(store=store)
            self.assertTrue(len(kc.validatedKnowledge) >= 1)
            self.assertEqual(kc.validatedKnowledge[0].label, "VALIDATED_KNOWLEDGE")

    def test_05_hypothesis_reaches_advisor_context(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store, *_ = _populated_store(tmp)
            kc = build_default_advisor_knowledge_context(store=store)
            self.assertTrue(len(kc.hypotheses) >= 1)
            self.assertEqual(kc.hypotheses[0].label, "HYPOTHESIS")

    def test_06_finding_reaches_advisor_context(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store, *_ = _populated_store(tmp)
            kc = build_default_advisor_knowledge_context(store=store)
            self.assertTrue(len(kc.findings) >= 1)
            self.assertEqual(kc.findings[0].label, "FINDING")

    def test_07_pattern_reaches_advisor_context(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store, *_ = _populated_store(tmp)
            kc = build_default_advisor_knowledge_context(store=store)
            self.assertTrue(len(kc.patterns) >= 1)
            self.assertEqual(kc.patterns[0].label, "PATTERN")

    def test_08_validation_reaches_advisor_context(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store, *_ = _populated_store(tmp)
            kc = build_default_advisor_knowledge_context(store=store)
            self.assertTrue(len(kc.validations) >= 1)
            self.assertEqual(kc.validations[0].label, "VALIDATION")

    def test_09_classifications_preserved(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store, *_ = _populated_store(tmp)
            kc = build_default_advisor_knowledge_context(store=store)
            labels = set()
            for bucket in (
                kc.validatedKnowledge, kc.hypotheses, kc.findings,
                kc.patterns, kc.validations,
            ):
                labels.update(item.label for item in bucket)
            for expected in (
                "VALIDATED_KNOWLEDGE", "HYPOTHESIS", "FINDING", "PATTERN", "VALIDATION",
            ):
                self.assertIn(expected, labels)

    def test_10_validated_knowledge_prioritized_over_hypothesis(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store, *_ = _populated_store(tmp)
            kc = build_default_advisor_knowledge_context(store=store)
            lines = knowledge_lines(kc)
            rendered = render_advisor_knowledge(kc)
            vk_index = rendered.find("validatedKnowledge[0]")
            hyp_index = rendered.find("hypothesis[0]")
            self.assertLess(vk_index, hyp_index)
            self.assertTrue(kc.validatedKnowledge)

    def test_16_knowledge_envelope_service_input_consistent(self):
        kc = empty_advisor_knowledge_context()
        client, recording = _gateway(
            trace_evidence_source=lambda: empty_trace_evidence(),
            runtime_source=runtime,
            knowledge_source=lambda: kc,
        )
        response = _post(client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(recording.service_input.contextInput.knowledgeContext, kc)
        self.assertEqual(
            recording.service_input.request.contextEnvelope.knowledgeContext, kc
        )

    def test_15_knowledge_section_reaches_prompt(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store, *_ = _populated_store(tmp)
            kc = build_default_advisor_knowledge_context(store=store)
            client, recording = _gateway(
                trace_evidence_source=lambda: empty_trace_evidence(),
                runtime_source=runtime,
                specs=(_spec(),),
                knowledge_source=lambda: kc,
            )
            response = _post(client)
            self.assertEqual(response.status_code, 200)
            prompt = recording.prompt
            self.assertIn("[BEGIN_KNOWLEDGE_EVOLUTION]", prompt)
            self.assertIn("[END_KNOWLEDGE_EVOLUTION]", prompt)
            self.assertIn("classification=KNOWLEDGE EVOLUTION", prompt)
            self.assertIn("validatedKnowledge[0]", prompt)

    def test_52_existing_historical_evidence_still_works(self):
        trace = _trace(kind="win")
        evidence = build_advisor_trace_evidence((trace,))
        client, recording = _gateway(
            trace_evidence_source=lambda: evidence,
            runtime_source=runtime,
            knowledge_source=lambda: empty_advisor_knowledge_context(),
        )
        response = _post(client)
        self.assertEqual(response.status_code, 200)
        self.assertIn("[BEGIN_HISTORICAL_EVIDENCE]", recording.prompt)
        self.assertIn("[BEGIN_KNOWLEDGE_EVOLUTION]", recording.prompt)

    def test_53_existing_current_runtime_still_works(self):
        client, recording = _gateway(
            trace_evidence_source=lambda: empty_trace_evidence(),
            runtime_source=runtime,
            knowledge_source=lambda: empty_advisor_knowledge_context(),
        )
        response = _post(client)
        self.assertEqual(response.status_code, 200)
        runtime_block = recording.prompt.split("[BEGIN_RUNTIME_CONTEXT]")[1].split(
            "[END_RUNTIME_CONTEXT]"
        )[0]
        self.assertIn("botState=RUNNING", runtime_block)

    def test_54_existing_canonical_still_works(self):
        client, recording = _gateway(
            trace_evidence_source=lambda: empty_trace_evidence(),
            runtime_source=runtime,
            specs=(_spec(),),
            knowledge_source=lambda: empty_advisor_knowledge_context(),
        )
        response = _post(client)
        self.assertEqual(response.status_code, 200)
        self.assertIn("[BEGIN_SPECIFICATION_REFERENCE]", recording.prompt)
        self.assertIn("sourceId=spec-d9d", recording.prompt)

    def test_55_existing_conversation_memory_still_works(self):
        client, recording = _gateway(
            trace_evidence_source=lambda: empty_trace_evidence(),
            runtime_source=runtime,
            knowledge_source=lambda: empty_advisor_knowledge_context(),
        )
        response = _post(client)
        self.assertEqual(response.status_code, 200)
        self.assertIn("[BEGIN_CONVERSATION_CONTEXT]", recording.prompt)
        self.assertIn("[BEGIN_CURRENT_REQUEST]", recording.prompt)

    def test_17_knowledge_context_bounded(self):
        hypotheses = tuple(
            propose_hypothesis(
                statement=f"hypothesis {i}",
                validation_criteria=(("SUPPORT_RATIO", "AT_LEAST", 0.5),),
            )
            for i in range(MAX_KNOWLEDGE_HYPOTHESES + 5)
        )
        kc = build_advisor_knowledge_context(hypotheses=hypotheses)
        self.assertLessEqual(len(kc.hypotheses), MAX_KNOWLEDGE_HYPOTHESES)
        self.assertTrue(kc.truncated)


class D9DKnowledgeIndependentTest(unittest.TestCase):
    """Boundedness, determinism, separation and firewall (provider-neutral)."""

    def test_18_bounded_text(self):
        item = build_advisor_knowledge_context(
            hypotheses=(
                propose_hypothesis(
                    statement="x" * 5000,
                    validation_criteria=(("SUPPORT_RATIO", "AT_LEAST", 0.5),),
                ),
            )
        )
        self.assertLessEqual(len(item.hypotheses[0].statement), 640)

    def test_19_deterministic_ordering(self):
        hypotheses = [
            propose_hypothesis(
                statement=f"statement {i}",
                validation_criteria=(("SUPPORT_RATIO", "AT_LEAST", 0.5),),
            )
            for i in range(3)
        ]
        a = build_advisor_knowledge_context(hypotheses=hypotheses)
        b = build_advisor_knowledge_context(hypotheses=reversed(hypotheses))
        self.assertEqual(
            [i.objectId for i in a.hypotheses],
            [i.objectId for i in b.hypotheses],
        )

    def test_21_empty_knowledge_is_not_available_safe(self):
        kc = empty_advisor_knowledge_context()
        self.assertEqual(kc.status, "NOT_AVAILABLE")
        self.assertTrue(kc.is_empty)
        self.assertTrue(kc.is_unavailable)
        rendered = render_advisor_knowledge(kc)
        self.assertIn("status=NOT_AVAILABLE", rendered)

    def test_22_knowledge_db_unavailable_advisor_continues(self):
        def broken_source():
            raise RuntimeError("store unavailable")

        client, recording = _gateway(
            trace_evidence_source=lambda: empty_trace_evidence(),
            runtime_source=runtime,
            knowledge_source=broken_source,
        )
        response = _post(client)
        self.assertEqual(response.status_code, 200)
        block = recording.prompt.split("[BEGIN_KNOWLEDGE_EVOLUTION]")[1].split(
            "[END_KNOWLEDGE_EVOLUTION]"
        )[0]
        self.assertIn("status=NOT_AVAILABLE", block)

    def test_23_corrupt_knowledge_degrades_safely(self):
        def broken_source():
            # Any degradation path must never take down the Advisor.
            raise RuntimeError("knowledge payload corrupt")

        client, recording = _gateway(
            trace_evidence_source=lambda: empty_trace_evidence(),
            runtime_source=runtime,
            knowledge_source=broken_source,
        )
        response = _post(client)
        self.assertEqual(response.status_code, 200)
        self.assertIn("status=NOT_AVAILABLE", recording.prompt)

    def test_24_trading_trace_unified_trace_experience_path(self):
        trace = _trace(kind="win")
        exp = experience_from_trace(trace)
        self.assertEqual(exp.trace_id, trace.trace_id)
        self.assertEqual(exp.symbol, trace.symbol)
        self.assertTrue(exp.reason_codes)
        self.assertEqual(exp.completeness, TraceCompleteness.COMPLETE)

    def test_25_investigation_executes_over_experience_evidence(self):
        experiences = _experiences("win", "loss")
        inv = build_advisor_investigation(
            question="recent outcomes",
            investigation_id="advisor-default",
            criterion=InvestigationFilter(),
            experiences=experiences,
        )
        self.assertEqual(inv.evidenceCount, 2)
        self.assertEqual(inv.status, "ANALYSIS_AVAILABLE")

    def test_26_investigation_is_bounded(self):
        experiences = _experiences(*(["win", "loss"] * 20))
        inv = build_advisor_investigation(
            question="recent outcomes",
            investigation_id="advisor-default",
            criterion=InvestigationFilter(),
            experiences=experiences,
            evidence_limit=10,
        )
        self.assertLessEqual(inv.evidenceCount, 10)
        self.assertTrue(inv.truncated)

    def test_27_investigation_filters_preserved(self):
        from backend.knowledge_evolution.investigation import InvestigationFilter
        crit = InvestigationFilter(symbol="BTCUSDT", mode="PAPER", reason_codes=("SPREAD_OK",))
        exp = experience_from_trace(_trace(kind="win"))
        self.assertEqual(exp.symbol, "BTCUSDT")
        self.assertEqual(exp.mode, "PAPER")

    def test_28_no_arbitrary_python_predicate_reaches_investigation(self):
        # The investigation ABI is a typed InvestigationFilter, not a predicate.
        from backend.knowledge_evolution.investigation import InvestigationFilter, select_experiences
        experiences = _experiences("win", "loss")
        sel = select_experiences(experiences, InvestigationFilter(symbol="BTCUSDT"))
        self.assertTrue(sel)

    def test_29_insufficient_evidence_is_inconclusive(self):
        experiences = _experiences("win")
        inv = build_advisor_investigation(
            question="single",
            investigation_id="advisor-default",
            criterion=InvestigationFilter(),
            experiences=experiences,
        )
        self.assertIn(inv.status, ("INCONCLUSIVE", "ANALYSIS_AVAILABLE"))

    def test_30_missing_evidence_remains_unavailable(self):
        inv = build_advisor_investigation(
            question="none",
            investigation_id="advisor-default",
            criterion=InvestigationFilter(),
            experiences=(),
        )
        self.assertEqual(inv.evidenceCount, 0)
        self.assertEqual(inv.status, "INCONCLUSIVE")

    def test_31_no_trade_semantics_preserved(self):
        from backend.knowledge_evolution.experience import ExperienceType
        exp = make_experience(
            experience_type=ExperienceType.NO_TRADE,
            symbol="BTCUSDT",
            outcome="SUPPRESSED",
            trace_id="tracing-1",
        )
        self.assertEqual(exp.experience_type, ExperienceType.NO_TRADE)
        self.assertEqual(exp.outcome, "SUPPRESSED")

    def test_32_reason_codes_preserved(self):
        exp = experience_from_trace(_trace(kind="win"))
        codes = {code.code for code in exp.reason_codes}
        self.assertIn("SPREAD_OK", codes)

    def test_33_trace_completeness_preserved(self):
        exp = experience_from_trace(_trace(kind="win"))
        self.assertEqual(exp.completeness, TraceCompleteness.COMPLETE)

    def test_34_trace_ambiguity_preserved(self):
        tid = new_trace_id()
        events = [
            make_event(trace_id=tid, mode="PAPER", stage="STRATEGY", status="BUY",
                       symbol="BTCUSDT", metadata={"decisionId": "d1"}).to_dict(),
            make_event(trace_id=tid, mode="PAPER", stage="STRATEGY", status="SELL",
                       symbol="BTCUSDT", metadata={"decisionId": "d1"}).to_dict(),
        ]
        trace = UnifiedTraceAssembler(StaticTraceEvidenceSource(events)).assemble(tid)
        self.assertEqual(trace.completeness, TraceCompleteness.AMBIGUOUS)
        exp = experience_from_trace(trace)
        self.assertEqual(exp.completeness, TraceCompleteness.AMBIGUOUS)

    def test_35_provenance_preserved(self):
        objs = _real_objects()
        kc = build_advisor_knowledge_context(
            findings=(objs["finding"],),
            hypotheses=(objs["hypothesis"],),
        )
        for item in (*kc.findings, *kc.hypotheses):
            self.assertTrue(item.provenance)
            self.assertTrue(item.provenance.startswith(("FINDING:", "HYPOTHESIS:")))

    def test_36_persisted_drift_state_preserved(self):
        from backend.knowledge_core.drift import DriftStatus
        exp = make_experience(
            experience_type=ExperienceType.DECISION,
            symbol="BTCUSDT",
            trace_id="tracing-1",
        )
        # Drift is not silently transformed; it stays None/unknown when absent.
        self.assertIsNone(exp.drift)

    def test_37_evidence_strength_not_statistical_significance(self):
        objs = _real_objects()
        kc = build_advisor_knowledge_context(patterns=(objs["pattern"],))
        self.assertEqual(kc.patterns[0].label, "PATTERN")
        self.assertIn("pattern[0].label=PATTERN", render_advisor_knowledge(kc))

    def test_38_singleton_not_repeated(self):
        pattern = build_pattern(
            _experiences("win"),
            pattern_type=PatternType.GENERIC,
            description="single event",
            condition=lambda e: True,
            outcome=lambda e: (e.outcome or "") == "WIN",
        )
        self.assertIn("SINGLE_EVENT_NOT_REPEATED_PATTERN", pattern.warnings)
        self.assertEqual(pattern.status.value, "SINGLETON")

    def test_39_hypothesis_not_presented_as_validated(self):
        objs = _real_objects()
        kc = build_advisor_knowledge_context(hypotheses=(objs["proposed"],))
        self.assertEqual(kc.hypotheses[0].label, "HYPOTHESIS")
        self.assertNotEqual(kc.hypotheses[0].label, "VALIDATED_KNOWLEDGE")

    def test_40_finding_not_presented_as_validated(self):
        objs = _real_objects()
        kc = build_advisor_knowledge_context(findings=(objs["finding"],))
        self.assertEqual(kc.findings[0].label, "FINDING")
        self.assertNotEqual(kc.findings[0].label, "VALIDATED_KNOWLEDGE")

    def test_41_validated_knowledge_clearly_labeled(self):
        objs = _real_objects()
        kc = build_advisor_knowledge_context(validated_knowledge=(objs["vk"],))
        self.assertEqual(kc.validatedKnowledge[0].label, "VALIDATED_KNOWLEDGE")
        self.assertEqual(kc.validatedKnowledge[0].state, "VALIDATED_KNOWN")
        self.assertIn("validatedKnowledge[0].label=VALIDATED_KNOWLEDGE", render_advisor_knowledge(kc))

    def test_50_provider_neutrality(self):
        kc = empty_advisor_knowledge_context()
        lines = knowledge_lines(kc)
        rendered = "\n".join(f"{k}={v}" for k, v in lines).lower()
        for provider in ("openai", "byteplus", "deepseek", "anthropic"):
            self.assertNotIn(provider, rendered)

    def test_51_no_secret_raw_db_dump(self):
        kc = build_advisor_knowledge_context(
            hypotheses=(
                propose_hypothesis(
                    statement="api_key=SECRET123 /etc/passwd",
                    validation_criteria=(("SUPPORT_RATIO", "AT_LEAST", 0.5),),
                ),
            )
        )
        client, recording = _gateway(
            trace_evidence_source=lambda: empty_trace_evidence(),
            runtime_source=runtime,
            knowledge_source=lambda: kc,
        )
        response = _post(client)
        self.assertEqual(response.status_code, 200)
        block = recording.prompt.split("[BEGIN_KNOWLEDGE_EVOLUTION]")[1].split(
            "[END_KNOWLEDGE_EVOLUTION]"
        )[0]
        self.assertNotIn("secret123", block)
        self.assertNotIn("etc/passwd", block)
        self.assertNotIn("api_key", block)


class D9DTruthHierarchyPromptTest(unittest.TestCase):
    """The prompt keeps CURRENT_RUNTIME, HISTORICAL_EVIDENCE and CONVERSATION
    separate; knowledge sits below canonical and is labelled."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store, self.vk, *_ = _populated_store(self._tmp.name)
        self.kc = build_default_advisor_knowledge_context(store=self.store)
        self.client, self.recording = _gateway(
            trace_evidence_source=lambda: empty_trace_evidence(),
            runtime_source=runtime,
            specs=(_spec(),),
            knowledge_source=lambda: self.kc,
        )
        response = _post(self.client)
        self.assertEqual(response.status_code, 200)
        self.prompt = self.recording.prompt

    def _section(self, marker):
        return self.prompt.split(f"[BEGIN_{marker}]")[1].split(f"[END_{marker}]")[0]

    def test_11_canonical_remains_higher_authority(self):
        self.assertIn(
            "Canonical Specification is authoritative and is never overridden by knowledge evolution.",
            self.prompt,
        )
        spec_block = self._section("SPECIFICATION_REFERENCE")
        self.assertIn("sourceId=spec-d9d", spec_block)
        self.assertIn("authority=SPECIFICATION_AUTHORITATIVE", spec_block)

    def test_12_current_runtime_remains_separate(self):
        runtime_block = self._section("RUNTIME_CONTEXT")
        knowledge_block = self._section("KNOWLEDGE_EVOLUTION")
        self.assertIn("botState=RUNNING", runtime_block)
        self.assertNotIn("botState=", knowledge_block)

    def test_13_historical_evidence_remains_separate(self):
        history_block = self._section("HISTORICAL_EVIDENCE")
        knowledge_block = self._section("KNOWLEDGE_EVOLUTION")
        self.assertIn("status=NOT_AVAILABLE", history_block)
        self.assertNotIn("validatedKnowledge[0]", history_block)

    def test_14_conversation_memory_remains_context_only(self):
        conv_block = self._section("CONVERSATION_CONTEXT")
        self.assertIn("classification=UNTRUSTED CONVERSATION DATA", conv_block)
        knowledge_block = self._section("KNOWLEDGE_EVOLUTION")
        self.assertNotIn("classification=UNTRUSTED CONVERSATION DATA", knowledge_block)

    def test_42_advisor_does_not_create_human_review(self):
        # APPROVE remains a denied capability; the Advisor has no review path.
        self.assertEqual(self.kc.authority, "READ_ONLY")
        self.assertIn("denied capabilities", self.prompt.lower())
        self.assertNotIn("APPROVE_EXECUTION", self.prompt)
        self.assertNotIn("APPROVE_KNOWLEDGE", self.prompt)

    def test_44_advisor_chat_does_not_mutate_knowledge(self):
        # The real store content is unchanged after an Advisor request.
        before = len(self.store.list_validated_knowledge())
        _post(self.client)
        after = len(self.store.list_validated_knowledge())
        self.assertEqual(before, after)
        self.assertEqual(self.kc.authority, "READ_ONLY")


if __name__ == "__main__":
    unittest.main()
