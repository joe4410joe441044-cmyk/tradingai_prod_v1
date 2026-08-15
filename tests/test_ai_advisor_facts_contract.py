"""R6 facts schema contract regression and prompt/parser alignment tests.

These tests pin the single authoritative ``facts`` contract shared by the
prompt builder, the strict response parser, and the application DTO. They
regress the exact R5 blocker (CONSTRAINT_VIOLATION on ``facts`` for a
source-less advisory response) without weakening fail-closed validation.
"""

import json
import unittest
from datetime import datetime, timezone

from backend.ai_advisor.conversation_models import AdvisorFreshnessState
from backend.ai_advisor.provider_failure_observation import (
    ResponseContractField,
    ResponseValidationCode,
)
from backend.ai_advisor.prompt_models import build_response_instruction
from backend.ai_advisor.response_models import (
    MAX_FACTS,
    MAX_RESPONSE_SOURCES,
    MAX_STATEMENT_CHARACTERS,
    AdvisorFact,
    AdvisorRawResponse,
    AdvisorResponseCandidate,
    AdvisorResponseStatus,
)
from backend.ai_advisor.response_parser import (
    AdvisorResponseParsingError,
    parse_advisor_response,
)

NOW = datetime(2026, 7, 26, 13, tzinfo=timezone.utc)


def _fact(fact_id="fact-1", statement="The configured mode is PAPER."):
    return {
        "factId": fact_id,
        "statement": statement,
        "sourceIds": ["advisor-runtime"],
        "freshness": "FRESH",
    }


def _candidate(**overrides):
    payload = {
        "responseVersion": "1.0",
        "requestId": "request-1",
        "promptVersion": "1.0",
        "summary": "Read-only advisory.",
        "facts": [_fact()],
        "inferences": [],
        "unknowns": [],
        "warnings": [],
        "sourceReferences": ["advisor-runtime"],
        "freshnessDisclosures": [{"sourceId": "advisor-runtime", "freshness": "FRESH"}],
        "safetyDisclosures": [
            "READ_ONLY",
            "NO_ACTION_EXECUTED",
            "NO_STATE_CHANGED",
            "NO_TOOL_USED",
        ],
    }
    payload.update(overrides)
    return payload


def _parse(payload):
    raw = AdvisorRawResponse(
        requestId="request-1",
        promptVersion="1.0",
        responseFormatVersion="1.0",
        responseText=json.dumps(payload),
        receivedAt=NOW,
    )
    return parse_advisor_response(raw)


def _diagnostic(payload):
    try:
        _parse(payload)
        return None
    except AdvisorResponseParsingError as error:
        return error.diagnostic


class FactsPromptParserContractTest(unittest.TestCase):
    def test_prompt_describes_facts_contract_that_matches_parser(self):
        instruction = build_response_instruction(
            request_id="request-1", prompt_version="1.0"
        )
        self.assertIn(
            f"facts: required non-null JSON array, 0 to {MAX_FACTS} objects",
            instruction,
        )
        self.assertIn(
            f"statement (non-null string, 1 to {MAX_STATEMENT_CHARACTERS} characters)",
            instruction,
        )
        min_len = None
        max_len = None
        for meta in AdvisorFact.model_fields["sourceIds"].metadata:
            if getattr(meta, "min_length", None) is not None:
                min_len = meta.min_length
            if getattr(meta, "max_length", None) is not None:
                max_len = meta.max_length
        self.assertEqual((min_len, max_len), (1, MAX_RESPONSE_SOURCES))
        self.assertIn(
            f"sourceIds (non-null array of {min_len} to {max_len} non-null strings",
            instruction,
        )
        expected_enum = "|".join(state.value for state in AdvisorFreshnessState)
        self.assertIn(
            f"freshness (non-null string enum {expected_enum})",
            instruction,
        )
        self.assertIn(
            "Never invent a sourceId or cite a source that was not supplied",
            instruction,
        )
        self.assertIn(
            "facts, inferences, sourceReferences, and freshnessDisclosures "
            "must all be empty arrays",
            instruction,
        )


class FactsParserRegressionTest(unittest.TestCase):
    def test_canonical_facts_are_accepted(self):
        parsed = _parse(_candidate())
        self.assertIsInstance(parsed, AdvisorResponseCandidate)
        self.assertIsInstance(parsed.facts, tuple)
        self.assertEqual(len(parsed.facts), 1)

    def test_multiple_facts_within_limits_are_accepted(self):
        parsed = _parse(_candidate(facts=[_fact("fact-a"), _fact("fact-b")]))
        self.assertEqual(len(parsed.facts), 2)

    def test_empty_facts_are_accepted(self):
        parsed = _parse(
            _candidate(
                facts=[],
                inferences=[],
                sourceReferences=[],
                freshnessDisclosures=[],
            )
        )
        self.assertEqual(parsed.facts, ())

    def test_facts_wrong_top_level_type_rejected(self):
        diagnostic = _diagnostic(_candidate(facts="wrong"))
        self.assertEqual(
            diagnostic.validationCode, ResponseValidationCode.FIELD_TYPE_INVALID
        )
        self.assertEqual(diagnostic.invalidField, ResponseContractField.FACTS)

    def test_fact_wrong_object_type_rejected(self):
        diagnostic = _diagnostic(_candidate(facts=["not-an-object"]))
        self.assertEqual(
            diagnostic.validationCode, ResponseValidationCode.NESTED_SCHEMA_INVALID
        )
        self.assertEqual(diagnostic.invalidField, ResponseContractField.FACTS)

    def test_missing_required_fact_fields_rejected(self):
        fact = _fact()
        fact.pop("factId")
        diagnostic = _diagnostic(_candidate(facts=[fact]))
        self.assertEqual(
            diagnostic.validationCode, ResponseValidationCode.NESTED_SCHEMA_INVALID
        )
        self.assertEqual(diagnostic.invalidField, ResponseContractField.FACTS)

    def test_empty_required_text_rejected(self):
        diagnostic = _diagnostic(_candidate(facts=[_fact(statement="")]))
        self.assertEqual(
            diagnostic.validationCode, ResponseValidationCode.CONSTRAINT_VIOLATION
        )
        self.assertEqual(diagnostic.invalidField, ResponseContractField.FACTS)

    def test_invalid_source_ids_type_rejected(self):
        fact = _fact()
        fact["sourceIds"] = "advisor-runtime"
        diagnostic = _diagnostic(_candidate(facts=[fact]))
        self.assertEqual(
            diagnostic.validationCode, ResponseValidationCode.FIELD_TYPE_INVALID
        )
        self.assertEqual(diagnostic.invalidField, ResponseContractField.FACTS)

    def test_missing_source_ids_rejected(self):
        fact = _fact()
        fact.pop("sourceIds")
        diagnostic = _diagnostic(_candidate(facts=[fact]))
        self.assertEqual(
            diagnostic.validationCode, ResponseValidationCode.NESTED_SCHEMA_INVALID
        )
        self.assertEqual(diagnostic.invalidField, ResponseContractField.FACTS)

    def test_empty_source_ids_rejected(self):
        fact = _fact()
        fact["sourceIds"] = []
        diagnostic = _diagnostic(_candidate(facts=[fact]))
        self.assertEqual(
            diagnostic.validationCode, ResponseValidationCode.CONSTRAINT_VIOLATION
        )
        self.assertEqual(diagnostic.invalidField, ResponseContractField.FACTS)

    def test_too_many_facts_rejected(self):
        diagnostic = _diagnostic(
            _candidate(facts=[_fact(f"fact-{index}") for index in range(33)])
        )
        self.assertEqual(
            diagnostic.validationCode, ResponseValidationCode.CONSTRAINT_VIOLATION
        )
        self.assertEqual(diagnostic.invalidField, ResponseContractField.FACTS)

    def test_unknown_nested_structure_rejected(self):
        fact = _fact()
        fact["extra"] = True
        diagnostic = _diagnostic(_candidate(facts=[fact]))
        self.assertEqual(
            diagnostic.validationCode, ResponseValidationCode.UNEXPECTED_FIELD
        )
        self.assertEqual(
            diagnostic.invalidField, ResponseContractField.UNKNOWN_OR_UNEXPECTED
        )

    def test_malformed_json_rejected(self):
        raw = AdvisorRawResponse(
            requestId="request-1",
            promptVersion="1.0",
            responseFormatVersion="1.0",
            responseText="not json",
            receivedAt=NOW,
        )
        with self.assertRaises(AdvisorResponseParsingError) as raised:
            parse_advisor_response(raw)
        self.assertEqual(
            raised.exception.diagnostic.validationCode,
            ResponseValidationCode.JSON_DECODE_FAILED,
        )

    def test_valid_json_but_invalid_advisor_schema_rejected(self):
        payload = _candidate()
        payload.pop("summary")
        diagnostic = _diagnostic(payload)
        self.assertEqual(
            diagnostic.validationCode, ResponseValidationCode.REQUIRED_FIELD_MISSING
        )
        self.assertEqual(diagnostic.invalidField, ResponseContractField.SUMMARY)


class ConnectivityNoSourceContractTest(unittest.TestCase):
    def test_source_less_advisory_requires_empty_facts_and_validates(self):
        from backend.ai_advisor.browser_gateway import assemble_browser_service_input
        from backend.ai_advisor.prompt_builder import (
            build_advisor_prompt,
            render_advisor_prompt,
        )
        from backend.ai_advisor.prompt_models import AdvisorPromptPolicy
        from backend.ai_advisor.response_validation import (
            validate_advisor_response,
        )

        service_input = assemble_browser_service_input(
            prompt="Are you connected and operational?",
            principal_id="operator-1",
            now=NOW,
            request_id="request-1",
        )
        context = service_input.request.contextEnvelope
        self.assertEqual([source.sourceId for source in context.sources], [])
        prompt = build_advisor_prompt(
            request=service_input.request,
            context=context,
            policy=AdvisorPromptPolicy(),
        )
        rendered = render_advisor_prompt(prompt)
        self.assertIn("status=NOT_AVAILABLE", rendered)

        ungrounded = _candidate(
            facts=[
                {
                    "factId": "fact-1",
                    "statement": "The advisor is connected.",
                    "sourceIds": [],
                    "freshness": "FRESH",
                }
            ],
            sourceReferences=[],
            freshnessDisclosures=[],
        )
        with self.assertRaises(AdvisorResponseParsingError) as raised:
            _parse(ungrounded)
        self.assertEqual(
            raised.exception.diagnostic.validationCode,
            ResponseValidationCode.CONSTRAINT_VIOLATION,
        )
        self.assertEqual(
            raised.exception.diagnostic.invalidField, ResponseContractField.FACTS
        )

        honest = _candidate(
            facts=[],
            inferences=[],
            sourceReferences=[],
            freshnessDisclosures=[],
        )
        raw = AdvisorRawResponse(
            requestId="request-1",
            promptVersion="1.0",
            responseFormatVersion="1.0",
            responseText=json.dumps(honest),
            receivedAt=NOW,
        )
        envelope = validate_advisor_response(
            raw_response=raw,
            request=service_input.request,
            context=context,
            prompt_envelope=prompt,
        )
        self.assertEqual(envelope.status, AdvisorResponseStatus.VALID)
        self.assertEqual(envelope.facts, ())
        self.assertEqual(envelope.sourceReferences, ())


if __name__ == "__main__":
    unittest.main()
