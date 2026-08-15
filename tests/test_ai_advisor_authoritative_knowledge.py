import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.ai_advisor.authoritative_knowledge import (
    AuthoritativeKnowledgeEntry,
    KnowledgeAuthorityLevel,
    load_authoritative_specifications,
    production_knowledge_manifest,
    select_highest_authority,
)
from backend.ai_advisor.browser_gateway import assemble_browser_service_input
from backend.ai_advisor.context_builder import build_advisor_context
from backend.ai_advisor.prompt_builder import build_advisor_prompt, render_advisor_prompt
from backend.ai_advisor.prompt_models import AdvisorPromptPolicy
from backend.ai_advisor.response_models import (
    AdvisorRawResponse,
    AdvisorResponseStatus,
)
from backend.ai_advisor.response_validation import validate_advisor_response
from tests.test_ai_advisor_provider_contract import fixture_text
from tests.test_ai_advisor_prompt_builder import NOW, make_request, permission
from tests.test_ai_advisor_response_validation import candidate_payload


class AuthoritativeKnowledgeManifestTest(unittest.TestCase):
    def test_production_manifest_loads_six_hash_pinned_approved_sources(self):
        loaded = load_authoritative_specifications(strict=True, loaded_at=NOW)
        self.assertEqual(len(loaded), 6)
        self.assertEqual(
            {item.sourceId for item in loaded},
            {item.sourceId for item in production_knowledge_manifest()},
        )
        self.assertTrue(all(item.contentHash for item in loaded))
        self.assertTrue(all(item.excerpt for item in loaded))
        self.assertTrue(all(item.topics for item in loaded))

    def test_unlisted_file_is_not_silently_trusted(self):
        body = b"Approved bounded knowledge."
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs" / "approved.md").write_bytes(body)
            (root / "docs" / "rogue.md").write_text(
                "unapproved knowledge", encoding="utf-8"
            )
            entry = AuthoritativeKnowledgeEntry(
                sourceId="approved",
                knowledgeKey="component-test",
                authority=KnowledgeAuthorityLevel.MASTER_SPEC,
                title="Approved",
                relativePath="docs/approved.md",
                version="1.0",
                topics=("TEST",),
                excerpt="Approved bounded knowledge.",
                expectedHash="sha256:" + hashlib.sha256(body).hexdigest(),
            )
            loaded = load_authoritative_specifications(
                repository_root=root,
                loaded_at=NOW,
                entries=(entry,),
                strict=True,
            )
            self.assertEqual(tuple(item.sourceId for item in loaded), ("approved",))
            self.assertNotIn("rogue", loaded[0].excerpt)

    def test_higher_authority_wins_for_the_same_knowledge_key(self):
        base = production_knowledge_manifest()[0]
        feature = base.model_copy(
            update={
                "sourceId": "feature",
                "authority": KnowledgeAuthorityLevel.FEATURE_SPEC,
            }
        )
        constitution = base.model_copy(
            update={
                "sourceId": "constitution",
                "authority": KnowledgeAuthorityLevel.CONSTITUTION,
            }
        )
        selected = select_highest_authority((feature, constitution))
        self.assertEqual(tuple(item.sourceId for item in selected), ("constitution",))

    def test_component_knowledge_and_traceable_source_ids_reach_prompt(self):
        specs = load_authoritative_specifications(strict=True, loaded_at=NOW)
        value = assemble_browser_service_input(
            prompt="TradingAIの主要コンポーネントを説明してください。",
            principal_id="operator",
            now=NOW,
            request_id="request-knowledge",
            approved_specifications=specs,
        )
        prompt = build_advisor_prompt(
            request=value.request,
            context=value.request.contextEnvelope,
            policy=AdvisorPromptPolicy(),
        )
        rendered = render_advisor_prompt(prompt)
        self.assertIn("knowledgeKind=STATIC", rendered)
        for component in (
            "Market Intelligence",
            "AI Advisor",
            "Money Management",
            "Market Recorder",
            "Supervisor",
        ):
            self.assertIn(component, rendered)
        for source in specs:
            self.assertIn(source.sourceId, rendered)
        self.assertIn("status=NOT_AVAILABLE", rendered)

    def test_grounded_multi_component_answer_is_accepted_with_traceability(self):
        specs = load_authoritative_specifications(strict=True, loaded_at=NOW)
        value = assemble_browser_service_input(
            prompt="TradingAIの主要コンポーネントと関係を説明してください。",
            principal_id="operator",
            now=NOW,
            request_id="request-knowledge",
            approved_specifications=specs,
        )
        prompt = build_advisor_prompt(
            request=value.request,
            context=value.request.contextEnvelope,
            policy=AdvisorPromptPolicy(),
        )
        facts = [
            ("mi", "Market Intelligenceは記録された市場と意思決定をレビューします。", "market-intelligence-component-v1.0"),
            ("advisor", "AI Advisorは研究、分析、説明を行う読み取り専用パートナーです。", "ai-advisor-master-v1.0"),
            ("mm", "Money Managementは資本配分とリスクを決定します。", "money-management-master-v1.0"),
            ("recorder", "Market Recorderは再生可能なマーケットデータを保存します。", "market-recorder-master-v1.0"),
            ("supervisor", "Supervisorは決定論的Python権限を置き換えない運用監督層です。", "supervisor-master-v1.1"),
        ]
        payload = candidate_payload()
        payload["requestId"] = "request-knowledge"
        payload["summary"] = (
            "各コンポーネントは、記録、レビュー、研究、リスク管理、運用監督を分担し、"
            "GovernanceとExecutionの決定論的な安全境界を維持します。"
        )
        payload["facts"] = [
            {
                "factId": fact_id,
                "statement": statement,
                "sourceIds": [source_id],
                "freshness": "NOT_APPLICABLE",
            }
            for fact_id, statement, source_id in facts
        ]
        payload["inferences"] = []
        payload["unknowns"] = []
        payload["warnings"] = []
        payload["sourceReferences"] = sorted(source_id for _, _, source_id in facts)
        payload["freshnessDisclosures"] = [
            {"sourceId": source_id, "freshness": "NOT_APPLICABLE"}
            for source_id in payload["sourceReferences"]
        ]
        raw = AdvisorRawResponse(
            requestId="request-knowledge",
            promptVersion="1.0",
            responseFormatVersion="1.0",
            responseText=fixture_text(payload),
            receivedAt=NOW,
        )
        result = validate_advisor_response(
            raw_response=raw,
            request=value.request,
            context=value.request.contextEnvelope,
            prompt_envelope=prompt,
        )
        self.assertEqual(result.status, AdvisorResponseStatus.VALID)
        self.assertEqual(len(result.groundedClaims), 5)
        self.assertEqual(
            {citation.sourceId for citation in result.citations},
            set(payload["sourceReferences"]),
        )

    def test_static_market_knowledge_cannot_authorize_a_current_market_fact(self):
        request, context = make_request(message="What is BTCUSDT doing now?")
        prompt = build_advisor_prompt(
            request=request,
            context=context,
            policy=AdvisorPromptPolicy(),
        )
        payload = candidate_payload()
        payload["summary"] = "BTCUSDT is currently bullish."
        raw = AdvisorRawResponse(
            requestId="request-1",
            promptVersion="1.0",
            responseFormatVersion="1.0",
            responseText=fixture_text(payload),
            receivedAt=NOW,
        )
        result = validate_advisor_response(
            raw_response=raw,
            request=request,
            context=context,
            prompt_envelope=prompt,
        )
        self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)

    def test_static_spec_cannot_authorize_a_current_runtime_value(self):
        request, context = make_request(message="What is the current Risk State?")
        static_context = build_advisor_context(
            generated_at=NOW,
            permission_context=permission(),
            specifications=load_authoritative_specifications(
                strict=True, loaded_at=NOW
            ),
        )
        request = request.model_copy(update={"contextEnvelope": static_context})
        prompt = build_advisor_prompt(
            request=request,
            context=static_context,
            policy=AdvisorPromptPolicy(),
        )
        payload = candidate_payload()
        payload["summary"] = "The current Risk State is NORMAL."
        payload["facts"] = [{
            "factId": "fake-current-risk",
            "statement": "The current Risk State is NORMAL.",
            "sourceIds": ["money-management-master-v1.0"],
            "freshness": "NOT_APPLICABLE",
        }]
        payload["inferences"] = []
        payload["unknowns"] = []
        payload["warnings"] = []
        payload["sourceReferences"] = ["money-management-master-v1.0"]
        payload["freshnessDisclosures"] = [{
            "sourceId": "money-management-master-v1.0",
            "freshness": "NOT_APPLICABLE",
        }]
        raw = AdvisorRawResponse(
            requestId="request-1",
            promptVersion="1.0",
            responseFormatVersion="1.0",
            responseText=fixture_text(payload),
            receivedAt=NOW,
        )
        result = validate_advisor_response(
            raw_response=raw,
            request=request,
            context=static_context,
            prompt_envelope=prompt,
        )
        self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)


class HumanActionableUnknownTest(unittest.TestCase):
    def _validate_unknown(self, *, topic, reason, required_source_type, facts=None):
        request, context = make_request(message="Explain what is known and missing.")
        prompt = build_advisor_prompt(
            request=request,
            context=context,
            policy=AdvisorPromptPolicy(),
        )
        payload = candidate_payload()
        payload["summary"] = "確認できる情報と不足情報を分けて説明します。"
        payload["facts"] = facts or []
        payload["inferences"] = []
        payload["unknowns"] = [
            {
                "unknownId": "unknown-1",
                "topic": topic,
                "reason": reason,
                "requiredSourceType": required_source_type,
            }
        ]
        payload["warnings"] = [
            {"code": "MISSING_SOURCE", "message": "情報を確認できません。"}
        ]
        used = {
            source_id
            for fact in payload["facts"]
            for source_id in fact["sourceIds"]
        }
        payload["sourceReferences"] = sorted(used)
        source_map = {source.sourceId: source for source in context.sources}
        payload["freshnessDisclosures"] = [
            {
                "sourceId": source_id,
                "freshness": source_map[source_id].freshness.state.value,
            }
            for source_id in sorted(used)
        ]
        raw = AdvisorRawResponse(
            requestId="request-1",
            promptVersion="1.0",
            responseFormatVersion="1.0",
            responseText=fixture_text(payload),
            receivedAt=NOW,
        )
        return validate_advisor_response(
            raw_response=raw,
            request=request,
            context=context,
            prompt_envelope=prompt,
        )

    def test_unknown_component_detail_is_human_actionable(self):
        result = self._validate_unknown(
            topic="未定義コンポーネントの役割",
            reason="CONTRACT_NOT_DEFINED",
            required_source_type="SPECIFICATION",
        )
        item = result.actionableUnknowns[0]
        self.assertEqual(item.subject, "未定義コンポーネントの役割")
        self.assertIn("承認済みTradingAI仕様", item.reason)
        self.assertIn("仕様", item.missingInformation)
        self.assertIn("管理者", item.safeNextStep)
        self.assertIn("見送って", item.decisionImpact)
        self.assertEqual(item.operationalEffect, "NONE")

    def test_unknown_current_runtime_state_remains_unknown_despite_static_specs(self):
        result = self._validate_unknown(
            topic="現在のMoney Management Risk State",
            reason="INSUFFICIENT_CONTEXT",
            required_source_type="MONEY_MANAGEMENT",
        )
        item = result.actionableUnknowns[0]
        self.assertIn("現在のRisk State", item.missingInformation)
        self.assertIn("Runtime / Status", item.safeNextStep)
        self.assertEqual(result.groundedClaims[-1].claimType, "UNKNOWN")

    def test_unknown_current_market_state_has_safe_read_only_next_step(self):
        result = self._validate_unknown(
            topic="現在のBTCUSDT市場状態",
            reason="SOURCE_MISSING",
            required_source_type="MARKET_INTELLIGENCE",
        )
        item = result.actionableUnknowns[0]
        self.assertIn("Data Quality", item.missingInformation)
        self.assertIn("Market Intelligence画面", item.safeNextStep)
        self.assertNotIn("有効", item.safeNextStep)
        self.assertEqual(item.operationalEffect, "NONE")

    def test_partially_known_response_preserves_fact_and_actionable_unknown(self):
        result = self._validate_unknown(
            topic="現在のRisk State",
            reason="SOURCE_MISSING",
            required_source_type="MONEY_MANAGEMENT",
            facts=[
                {
                    "factId": "fact-static",
                    "statement": "承認済み仕様はAI Advisorを読み取り専用と定義します。",
                    "sourceIds": ["spec-a"],
                    "freshness": "NOT_APPLICABLE",
                }
            ],
        )
        self.assertEqual(result.status, AdvisorResponseStatus.VALID_WITH_WARNINGS)
        self.assertEqual(len(result.facts), 1)
        self.assertEqual(len(result.actionableUnknowns), 1)

    def test_decision_critical_missing_data_always_defers_decision(self):
        result = self._validate_unknown(
            topic="取引判断に必要なExecution Outcome",
            reason="SOURCE_STALE",
            required_source_type="EXECUTION_RESULT",
        )
        item = result.actionableUnknowns[0]
        self.assertIn("取引判断", item.decisionImpact)
        self.assertIn("見送って", item.decisionImpact)
        self.assertEqual(item.operationalEffect, "NONE")


if __name__ == "__main__":
    unittest.main()
