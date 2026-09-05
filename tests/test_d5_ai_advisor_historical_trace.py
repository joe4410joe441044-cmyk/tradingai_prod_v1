"""D-5 tests for the bounded, separ HISTORICAL_EVIDENCE Advisor context."""

import unittest

from backend.ai_advisor.context_builder import (
    SpecificationSourceInput,
    build_advisor_context,
)
from backend.ai_advisor.conversation_models import (
    AdvisorRequest,
    AdvisorResponsePreferences,
    AdvisorDetailLevel,
    AdvisorResponseFormat,
)
from backend.ai_advisor.historical_trace_evidence import (
    AdvisorTraceEvidence,
    AdvisorUnifiedTrace,
    MAX_TRACE_EVIDENCE_NODES_PER_TRACE,
    MAX_TRACE_EVIDENCE_REASON_CODES,
    MAX_TRACE_EVIDENCE_TRACES,
    build_advisor_trace_evidence,
    empty_trace_evidence,
    historical_trace_lines,
    render_historical_trace_evidence,
)
from backend.ai_advisor.prompt_builder import build_advisor_prompt, render_advisor_prompt
from backend.ai_advisor.prompt_models import (
    AdvisorPromptPolicy,
    AdvisorPromptSectionType,
)
from backend.runtime.unified_trace import (
    LinkStrength,
    StaticTraceEvidenceSource,
    TraceCompleteness,
    TraceNodeType,
    UnifiedTraceAssembler,
)
from backend.runtime.trading_trace import make_event, new_trace_id

from tests.test_ai_advisor_prompt_builder import NOW, permission, runtime


def _unified_trace(*stages):
    trace_id = new_trace_id()
    events = []
    for stage, status, reason, meta in stages:
        events.append(
            make_event(
                trace_id=trace_id, mode="PAPER", stage=stage, status=status,
                symbol="BTCUSDT", runtime_id="runtime-1", reason_code=reason,
                metadata=meta,
            ).to_dict()
        )
    return UnifiedTraceAssembler(StaticTraceEvidenceSource(events)).assemble(trace_id)


def _executed_trace():
    return _unified_trace(
        ("STRATEGY", "BUY", None, None),
        ("EXECUTION", "PAPER_FILLED", None, {"orderId": "paper-1"}),
        ("POSITION", "OPEN", None, {"positionId": "p-1", "orderId": "paper-1"}),
        ("RESULT", "EXECUTED", None, {"decision": "BUY", "netPnL": 1.25}),
    )


def _no_trade_trace():
    return _unified_trace(
        ("STRATEGY", "HOLD", "LIQUIDITY_INSTABILITY", None),
        ("RESULT", "SUPPRESSED", "LIQUIDITY_INSTABILITY", None),
    )


def _context_with_evidence(evidence):
    return build_advisor_context(
        generated_at=NOW,
        permission_context=permission(),
        runtime=runtime(),
        specifications=(
            SpecificationSourceInput(
                sourceId="spec-a",
                sourceVersion="1.0",
                title="Specification A",
                documentPath="docs/ai_advisor/a.md",
                loadedAt=NOW,
                approved=True,
            ),
        ),
        trace_evidence=evidence,
    )


def _request(context):
    return AdvisorRequest(
        schemaVersion="1.0",
        requestId="request-1",
        message="Why did this trade happen?",
        locale="en-US",
        requestedAt=NOW,
        permissionContext=permission(),
        contextEnvelope=context,
        responsePreferences=AdvisorResponsePreferences(
            locale="en-US",
            detailLevel=AdvisorDetailLevel.STANDARD,
            includeSources=True,
            includeWarnings=True,
            format=AdvisorResponseFormat.STRUCTURED,
        ),
    )


class AdvisorHistoricalTraceEvidenceTest(unittest.TestCase):
    def test_evidence_reduces_typed_nodes_and_keeps_reasons(self):
        evidence = build_advisor_trace_evidence((_executed_trace(),))
        self.assertFalse(evidence.truncated)
        self.assertEqual(len(evidence.traces), 1)
        projected = evidence.traces[0]
        self.assertEqual(projected.completeness, TraceCompleteness.COMPLETE.value)
        self.assertEqual(projected.orderCount, 1)
        node_types = {node.nodeType for node in projected.nodes}
        self.assertIn(TraceNodeType.DECISION.value, node_types)

    def test_bounds_report_truncation_explicitly(self):
        traces = tuple(_executed_trace() for _ in range(MAX_TRACE_EVIDENCE_TRACES + 3))
        evidence = build_advisor_trace_evidence(traces)
        self.assertTrue(evidence.truncated)
        self.assertLessEqual(len(evidence.traces), MAX_TRACE_EVIDENCE_TRACES)
        self.assertGreaterEqual(evidence.omittedTraceCount, 3)
        self.assertIsNotNone(evidence.warning)

    def test_node_budget_is_bounded(self):
        evidence = build_advisor_trace_evidence(
            (_executed_trace(),), max_nodes_per_trace=1
        )
        projected = evidence.traces[0]
        self.assertLessEqual(len(projected.nodes), 1)
        self.assertTrue(projected.nodesTruncated)

    def test_reason_code_budget_is_bounded(self):
        trace = _executed_trace()
        evidence = build_advisor_trace_evidence((trace,))
        projected = evidence.traces[0]
        self.assertLessEqual(len(projected.reasonCodes), MAX_TRACE_EVIDENCE_REASON_CODES)

    def test_historical_label_is_distinct_from_current_runtime(self):
        evidence = build_advisor_trace_evidence((_executed_trace(), _no_trade_trace()))
        context = _context_with_evidence(evidence)
        prompt = build_advisor_prompt(
            request=_request(context), context=context, policy=AdvisorPromptPolicy()
        )
        rendered = render_advisor_prompt(prompt)
        self.assertIn("[BEGIN_HISTORICAL_EVIDENCE]", rendered)
        self.assertIn("[END_HISTORICAL_EVIDENCE]", rendered)
        self.assertIn("classification=HISTORICAL EVIDENCE", rendered)
        self.assertIn("[BEGIN_RUNTIME_CONTEXT]", rendered)
        # The historical block must not claim to be current runtime state.
        history_section = next(
            s for s in prompt.contextSections
            if s.sectionType is AdvisorPromptSectionType.HISTORICAL_EVIDENCE
        )
        self.assertNotIn("botState=", history_section.content)
        self.assertNotIn("status=FRESH", history_section.content)

    def test_empty_evidence_is_explicitly_not_available(self):
        evidence = empty_trace_evidence()
        rendered = render_historical_trace_evidence(evidence)
        self.assertIn("classification=HISTORICAL EVIDENCE", rendered)
        self.assertIn("status=NOT_AVAILABLE", rendered)

    def test_full_history_is_not_injected(self):
        evidence = build_advisor_trace_evidence((_executed_trace(),))
        rendered = render_historical_trace_evidence(evidence).lower()
        # Raw decision inputs / full market microstructure must not be projected.
        self.assertNotIn("decisioninput", rendered)
        self.assertNotIn("orderbook", rendered)
        self.assertNotIn("pressure", rendered)
        # The projected text stays small and bounded.
        self.assertLess(len(rendered), 1600)

    def test_projected_text_is_bounded_per_trace(self):
        evidence = build_advisor_trace_evidence(
            tuple(_executed_trace() for _ in range(8))
        )
        for trace in evidence.traces:
            self.assertEqual(trace.traceId[:12], "trading-e2e-")
        rendered = render_historical_trace_evidence(evidence)
        # bounded by the trace budget already; never a full raw dump
        self.assertLess(len(rendered), 5000)

    def test_evidence_building_does_not_mutate_inputs(self):
        trace = _executed_trace()
        before = trace.to_dict()
        build_advisor_trace_evidence((trace,))
        self.assertEqual(trace.to_dict(), before)

    def test_operator_security_boundary_excludes_secrets(self):
        # A trace's data layer is already sanitized; the projection never
        # surfaces API keys/tokens.
        rendered = render_historical_trace_evidence(
            build_advisor_trace_evidence((_executed_trace(),))
        )
        for secret in ("apiKey", "authorization", "secret", "passphrase"):
            self.assertNotIn(secret.lower(), rendered.lower())

    def test_no_operational_authority_in_label(self):
        rendered = render_historical_trace_evidence(
            build_advisor_trace_evidence((_executed_trace(),))
        )
        # Historical evidence never asserts operational/execution authority.
        self.assertNotIn("grantsExecutionAuthority", rendered)
        self.assertNotIn("executionAuthority=", rendered)
        self.assertNotIn("autoTradeEnabled", rendered)
        self.assertNotIn("liveOrderEntryState", rendered)


if __name__ == "__main__":
    unittest.main()
