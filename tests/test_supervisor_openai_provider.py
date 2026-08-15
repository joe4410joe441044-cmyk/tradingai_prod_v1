import json
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from backend.ai_advisor.credential_loader import EnvironmentCredentialLoader
from backend.ai_advisor.provider_transport import OpenAITransportTimeout
from backend.supervisor.contracts import MasterSupervisorDecision
from backend.supervisor.conversation_contracts import SupervisorConversationProviderOutput
from backend.supervisor.openai_provider import OpenAIStructuredProvider
from backend.supervisor.provider import ProviderAvailability
from backend.supervisor.provider_configuration import (
    SupervisorProviderConfiguration,
    SupervisorProviderMode,
)


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["SHADOW"]
    answer: str


def openai_config():
    return SupervisorProviderConfiguration(
        mode=SupervisorProviderMode.OPENAI,
        endpoint="",
        model="gpt-4o-mini",
        timeoutSeconds=45.0,
        credentialId="OPENAI_API_KEY",
        maxOutputTokens=4096,
    )


def credential_loader(value="sk-test-secret"):
    return EnvironmentCredentialLoader(
        ("OPENAI_API_KEY",),
        environmentReader=lambda key: value,
    )


class FakeTransport:
    def __init__(self, response=None, exception=None):
        self.response = response or {"output_text": "{}", "finish_reason": "completed"}
        self.exception = exception
        self.calls = []

    def invoke(self, request):
        self.calls.append(request)
        if self.exception is not None:
            raise self.exception
        return self.response


def test_identity_availability_and_disabled_rejection():
    provider = OpenAIStructuredProvider(
        openai_config(), credential_loader=credential_loader(), transport=FakeTransport()
    )
    assert provider.identity.name == "OPENAI"
    assert provider.availability is ProviderAvailability.AVAILABLE

    with pytest.raises(ValueError):
        OpenAIStructuredProvider(SupervisorProviderConfiguration())
    with pytest.raises(ValueError):
        OpenAIStructuredProvider(
            SupervisorProviderConfiguration(mode=SupervisorProviderMode.OLLAMA_LOCAL)
        )


def test_missing_credential_reports_unavailable():
    provider = OpenAIStructuredProvider(
        openai_config(),
        credential_loader=EnvironmentCredentialLoader(
            ("OPENAI_API_KEY",), environmentReader=lambda key: None
        ),
        transport=FakeTransport(),
    )
    assert provider.availability is ProviderAvailability.UNAVAILABLE
    status = provider.status()
    assert status["provider"] == "OPENAI"
    assert status["operationalEffect"] == "NONE"
    assert status["mode"] == "SHADOW"


def test_structured_output_is_parsed_and_validated():
    transport = FakeTransport(
        response={"output_text": json.dumps({"mode": "SHADOW", "answer": "safe"}), "finish_reason": "completed"}
    )
    provider = OpenAIStructuredProvider(
        openai_config(), credential_loader=credential_loader(), transport=transport
    )
    result = provider.generate_structured_output({"message": "state"}, Output, 45.0)
    assert result.failureCode is None
    assert result.output.mode == "SHADOW"
    assert result.output.answer == "safe"
    assert len(transport.calls) == 1
    request = transport.calls[0]
    assert request.model == "gpt-4o-mini"
    assert request.responseFormat == "json_object"
    assert request.stream is False
    assert "schema" in request.input
    assert "Input observation" in request.input


def test_invalid_json_and_extra_fields_fail_closed():
    for text in ("not json", json.dumps({"mode": "SHADOW", "answer": "x", "extra": 1})):
        transport = FakeTransport(
            response={"output_text": text, "finish_reason": "completed"}
        )
        provider = OpenAIStructuredProvider(
            openai_config(), credential_loader=credential_loader(), transport=transport
        )
        result = provider.generate_structured_output({}, Output, 45.0)
        assert result.output is None
        assert result.failureCode.value == "SUPERVISOR_OUTPUT_INVALID"


def test_transport_timeout_maps_to_provider_timeout():
    transport = FakeTransport(exception=OpenAITransportTimeout("timeout"))
    provider = OpenAIStructuredProvider(
        openai_config(), credential_loader=credential_loader(), transport=transport
    )
    result = provider.generate_structured_output({}, Output, 45.0)
    assert result.failureCode.value == "SUPERVISOR_PROVIDER_TIMEOUT"
    assert result.output is None


def test_mode_promotion_is_rejected_by_contract_validation():
    transport = FakeTransport(
        response={"output_text": json.dumps({"mode": "ACTIVE", "answer": "promoted"}), "finish_reason": "completed"}
    )
    provider = OpenAIStructuredProvider(
        openai_config(), credential_loader=credential_loader(), transport=transport
    )
    result = provider.generate_structured_output({}, Output, 45.0)
    assert result.failureCode.value == "SUPERVISOR_OUTPUT_INVALID"


def test_master_conversation_prompt_contains_grounding_rules():
    transport = FakeTransport(
        response={"output_text": json.dumps({"answer": "ok", "warnings": []}), "finish_reason": "completed"}
    )
    provider = OpenAIStructuredProvider(
        openai_config(), credential_loader=credential_loader(), transport=transport
    )
    result = provider.generate_structured_output(
        {"agentId": "MASTER_SUPERVISOR", "message": "state?", "systemState": {}},
        SupervisorConversationProviderOutput, 45.0,
    )
    assert result.failureCode is None
    prompt = transport.calls[0].input
    assert "start-blocking" in prompt
    assert "root cause" in prompt.lower()
    assert "enumerate" in prompt


def test_mm_conversation_prompt_contains_grounding_rules():
    transport = FakeTransport(
        response={"output_text": json.dumps({"answer": "ok", "warnings": []}), "finish_reason": "completed"}
    )
    provider = OpenAIStructuredProvider(
        openai_config(), credential_loader=credential_loader(), transport=transport
    )
    provider.generate_structured_output(
        {
            "agentId": "MM_SUPERVISOR",
            "message": "mm?",
            "systemState": {
                "moneyManagement": {
                    "currentExposure": None,
                    "remainingExposure": "1.583673932",
                    "drawdown": None,
                }
            },
            "mmAssessment": {},
        },
        SupervisorConversationProviderOutput, 45.0,
    )
    prompt = transport.calls[0].input
    assert "Money Management" in prompt
    assert "does NOT mean the market" in prompt
    assert "market stability" in prompt.lower()
    assert "unknown" in prompt.lower()
    assert "'currentExposure' is exposure currently in use" in prompt
    assert "'remainingExposure' is remaining exposure capacity" in prompt
    assert "never call it simply 'Exposure'" in prompt
    assert '"currentExposure":null' in prompt
    assert '"remainingExposure":"1.583673932"' in prompt


def test_master_decision_prompt_no_longer_treats_execution_disabled_as_emergency():
    transport = FakeTransport(response={"output_text": "{}"})
    provider = OpenAIStructuredProvider(
        openai_config(), credential_loader=credential_loader(), transport=transport
    )
    provider.generate_structured_output(
        {"context": {"governanceExecutionEnabled": False}}, MasterSupervisorDecision, 45.0,
    )
    prompt = transport.calls[0].input
    assert "is NOT an emergency" in prompt
    assert "governanceExecutionEnabled" in prompt
