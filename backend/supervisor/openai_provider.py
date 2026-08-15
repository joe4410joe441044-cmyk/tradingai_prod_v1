"""OpenAI structured-output provider for the Supervisor.

This adapter reuses the AI Advisor's guarded OpenAI SDK transport so the two
systems share one secure credential/transport authority, while keeping the
Supervisor's provider-neutral ``StructuredOutputProvider`` protocol, SHADOW-only
contracts, and fail-closed semantics intact. Responsibilities remain separated:
the Supervisor only ever requests read-only interpretation of a bounded snapshot
and never inherits AI Advisor prompt, contract, or authority behavior.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Mapping

from pydantic import BaseModel

from backend.ai_advisor.credential_loader import (
    CredentialLoader,
    CredentialResolutionInput,
    CredentialResolutionStatus,
    EnvironmentCredentialLoader,
)
from backend.ai_advisor.openai_sdk_transport import (
    DefaultOpenAIClientFactory,
    OpenAIClientFactory,
    OpenAISDKTransport,
)
from backend.ai_advisor.provider_config import (
    PROVIDER_CONNECTION_CONFIG_VERSION,
    CredentialReference,
    CredentialSource,
    ProviderConnectionConfig,
    ProviderName,
    ProviderResponseFormat,
)
from backend.ai_advisor.provider_transport import (
    OpenAITransportAuthenticationError,
    OpenAITransportConfigurationError,
    OpenAITransportConnectionError,
    OpenAITransportInternalError,
    OpenAITransportRateLimitError,
    OpenAITransportRejectedError,
    OpenAITransportRequest,
    OpenAITransportTimeout,
)

from .failure_codes import SupervisorFailureCode
from .provider import ProviderAvailability, ProviderIdentity, ProviderResult
from .provider_configuration import (
    OPENAI_SUPERVISOR_TIMEOUT_SECONDS,
    SupervisorProviderConfiguration,
    SupervisorProviderMode,
)


_TIMESTAMP_INSTRUCTIONS = {
    "MMSupervisorAssessment": (
        "Copy timestamp values exactly (character for character) from the input: "
        "set 'sourceEvaluatedAt' to the value of 'context.mmEvaluatedAt' (if that "
        "is null use 'context.snapshotCapturedAt'), and set 'assessedAt' to the "
        "value of the top-level 'requestedAt'."
    ),
    "MasterSupervisorDecision": (
        "Copy timestamp values exactly (character for character) from the input: "
        "set 'sourceEvaluatedAt' to the value of 'context.snapshotCapturedAt', and "
        "set 'decidedAt' to the value of the top-level 'requestedAt'."
    ),
}

_CONTRACT_NOTES = {
    "MMSupervisorAssessment": (
        "Assess strictly from the input context. Do not treat an unknown or "
        "unavailable value (for example Drawdown) as normal, healthy, or low risk; "
        "record such missing values in 'uncertainties'. MM State NORMAL means the "
        "Money Management state is NORMAL, not that the market is stable. Never "
        "assert market conditions, volatility, or liquidity, which are outside the "
        "Money Management context."
    ),
    "MasterSupervisorDecision": (
        "Decide strictly from the input context. If 'context.emergencyLocked' is "
        "true, or 'context.emergencyState' is LOCKED/ACTION_REQUIRED/PROCESSING, "
        "then set 'overallPosture' to LOCKED, 'tradingRecommendation' to STOP, and "
        "'humanAttention' to IMMEDIATE_ACTION. A false "
        "'context.governanceExecutionEnabled' by itself is the normal SHADOW/paper "
        "execution-disabled state and is NOT an emergency; do not set LOCKED or "
        "IMMEDIATE_ACTION for it alone. When governance execution is disabled, the "
        "Bot/Loop/Execution are stopped, or the market is not ready, set "
        "'overallPosture' to CAUTION or DEFENSIVE and 'tradingRecommendation' to "
        "STOP or PAUSE_NEW_ENTRIES (never CONTINUE). Only if every freshness value "
        "in the context is FRESH, there are no warnings, governance execution is "
        "enabled, emergency state is READY, the market is ready, and the MM "
        "assessment is NORMAL, set 'overallPosture' to NORMAL and "
        "'tradingRecommendation' to CONTINUE. Never use GROWTH. Set "
        "'mmRecommendation.riskDirection' to the value of 'context.mmRiskDirection' "
        "(or to REDUCE or PAUSE), and set 'mmRecommendation.riskMultiplier' to "
        "null. State only facts visible in the context; do not invent root causes "
        "that are absent from it."
    ),
}

_BASE_CONVERSATION_NOTE = (
    "Answer the operator's message using only the provided observation data. "
    "Do not invent or assume values; if a requested value is absent, state that it "
    "is unknown or unavailable. Never claim that any setting, mode, order, or "
    "operation was changed."
)

_MASTER_CONVERSATION_NOTE = (
    "You are the Master Supervisor. Base the answer only on the provided "
    "'systemState', 'mmAssessment', and 'masterDecision'. When asked whether trading "
    "can start, enumerate the concrete start-blocking factors that are directly "
    "visible in the observation (for example: Bot STOPPED means the Bot is not "
    "running; Loop STOPPED means the Loop is not running; Execution STOPPED means "
    "execution is stopped; Auto Trade disabled means auto trading is off; Market not "
    "ready means market preparation is incomplete). Never answer that the blocking "
    "reasons are unknown when the observation directly shows these factors. Do not "
    "infer root causes that are absent from the observation (for example why the Bot "
    "is stopped or why the Market is not ready); explicitly separate any root cause "
    "that cannot be determined from the current snapshot."
)

_MM_CONVERSATION_NOTE = (
    "You are the Money Management (MM) Supervisor. Your authority is Money "
    "Management only. Base the answer only on the provided 'mmAssessment' and the "
    "money management state. MM State NORMAL means the Money Management state is "
    "NORMAL; it does NOT mean the market is NORMAL or stable. Never assert market "
    "stability, volatility, strategy favorability, or liquidity sufficiency, because "
    "these are outside the Money Management context. State unknown or unavailable "
    "values explicitly (for example if Drawdown is unknown, say it is not currently "
    "available) instead of assuming they are normal or low risk. Do not conflate the "
    "Money Management execution-entry allowance with the overall system execution "
    "state. Treat 'currentExposure' and 'remainingExposure' as distinct concepts: "
    "'currentExposure' is exposure currently in use, while 'remainingExposure' is "
    "remaining exposure capacity. If 'currentExposure' is null, report current "
    "exposure as unknown or unavailable. If 'remainingExposure' has a value, label "
    "it explicitly as remaining exposure or remaining exposure capacity; never call "
    "it simply 'Exposure' and never present it as current exposure."
)


def _conversation_note(agent_id: object) -> str:
    if agent_id == "MASTER_SUPERVISOR":
        return _BASE_CONVERSATION_NOTE + " " + _MASTER_CONVERSATION_NOTE
    if agent_id == "MM_SUPERVISOR":
        return _BASE_CONVERSATION_NOTE + " " + _MM_CONVERSATION_NOTE
    return _BASE_CONVERSATION_NOTE


def _render_prompt(
    input_data: Mapping[str, object],
    schema: dict,
    contract_name: str,
) -> str:
    schema_text = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    data_text = json.dumps(input_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    notes = " ".join(
        note for note in (
            _TIMESTAMP_INSTRUCTIONS.get(contract_name),
            _CONTRACT_NOTES.get(contract_name),
            _conversation_note(input_data.get("agentId"))
            if contract_name == "SupervisorConversationProviderOutput"
            else None,
        ) if note
    )
    return (
        "Return only a JSON object that validates against this schema:\n"
        + schema_text
        + "\n\nInput observation:\n"
        + data_text
        + ("\n\n" + notes if notes else "")
        + "\n\nRespond with the JSON object only. Do not invent or round any "
        + "timestamp; copy the exact string from the input."
    )


class OpenAIStructuredProvider:
    """Supervisor structured-output provider backed by the OpenAI transport."""

    def __init__(
        self,
        configuration: SupervisorProviderConfiguration,
        *,
        credential_loader: CredentialLoader | None = None,
        client_factory: OpenAIClientFactory | None = None,
        transport=None,
        version: str = "1.0",
    ) -> None:
        if configuration.mode is not SupervisorProviderMode.OPENAI:
            raise ValueError("only OpenAI supervisor mode is allowed")
        if not configuration.model or not configuration.credentialId:
            raise ValueError("OpenAI supervisor model and credential id are required")
        self._configuration = configuration
        self._version = version
        self._credential_loader = credential_loader or EnvironmentCredentialLoader(
            (configuration.credentialId,)
        )
        self._transport = transport or OpenAISDKTransport(
            config=self._connection(),
            credentialLoader=self._credential_loader,
            clientFactory=client_factory or DefaultOpenAIClientFactory(),
            allowNetworkInvocation=True,
            liveConnectivityGate=None,
        )
        self._gate = threading.BoundedSemaphore(1)
        self._last_success: datetime | None = None
        self._last_failure: SupervisorFailureCode | None = None
        self._last_checked: datetime | None = None

    def _connection(self) -> ProviderConnectionConfig:
        return ProviderConnectionConfig(
            configVersion=PROVIDER_CONNECTION_CONFIG_VERSION,
            provider=ProviderName.OPENAI,
            model=self._configuration.model,
            credentialReference=CredentialReference(
                credentialId=self._configuration.credentialId,
                source=CredentialSource.ENVIRONMENT,
            ),
            endpoint=None,
            timeoutSeconds=min(
                self._configuration.timeoutSeconds,
                OPENAI_SUPERVISOR_TIMEOUT_SECONDS,
            ),
            maxOutputTokens=self._configuration.maxOutputTokens,
            temperature=0.0,
            responseFormat=ProviderResponseFormat.STRICT_JSON,
            enabled=True,
        )

    @property
    def identity(self) -> ProviderIdentity:
        return ProviderIdentity("OPENAI", self._version)

    @property
    def availability(self) -> ProviderAvailability:
        if self._configuration.mode is not SupervisorProviderMode.OPENAI:
            return ProviderAvailability.UNAVAILABLE
        try:
            self._last_checked = datetime.now(timezone.utc)
            resolution = self._credential_loader.resolve(
                CredentialResolutionInput(
                    credentialReference=CredentialReference(
                        credentialId=self._configuration.credentialId,
                        source=CredentialSource.ENVIRONMENT,
                    ),
                    provider=ProviderName.OPENAI,
                    allowEnvironmentRead=True,
                )
            )
            succeeded = resolution.status is CredentialResolutionStatus.SUCCEEDED
            self._last_failure = None if succeeded else SupervisorFailureCode.PROVIDER_UNAVAILABLE
            return ProviderAvailability.AVAILABLE if succeeded else ProviderAvailability.UNAVAILABLE
        except Exception:
            self._last_failure = SupervisorFailureCode.PROVIDER_UNAVAILABLE
            return ProviderAvailability.UNAVAILABLE

    def generate_structured_output(
        self,
        input_data: Mapping[str, object],
        output_contract: type[BaseModel],
        timeout_seconds: float,
    ) -> ProviderResult:
        connection = self._connection()
        timeout = min(float(timeout_seconds), connection.timeoutSeconds)
        if not self._gate.acquire(timeout=timeout):
            self._last_failure = SupervisorFailureCode.PROVIDER_TIMEOUT
            return ProviderResult(None, SupervisorFailureCode.PROVIDER_TIMEOUT)
        try:
            self._last_checked = datetime.now(timezone.utc)
            prompt = _render_prompt(
                input_data,
                output_contract.model_json_schema(),
                output_contract.__name__,
            )
            request = OpenAITransportRequest(
                model=connection.model,
                input=prompt,
                timeoutSeconds=timeout,
                maxOutputTokens=connection.maxOutputTokens,
                temperature=0.0,
                responseFormat="json_object",
                stream=False,
            )
            raw = self._transport.invoke(request)
            text = raw.get("output_text") if isinstance(raw, Mapping) else None
            if not isinstance(text, str) or not text.strip():
                self._last_failure = SupervisorFailureCode.OUTPUT_INVALID
                return ProviderResult(None, SupervisorFailureCode.OUTPUT_INVALID)
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                self._last_failure = SupervisorFailureCode.OUTPUT_INVALID
                return ProviderResult(None, SupervisorFailureCode.OUTPUT_INVALID)
            validated = output_contract.model_validate(parsed)
            self._last_success = datetime.now(timezone.utc)
            self._last_failure = None
            return ProviderResult(validated)
        except OpenAITransportTimeout:
            self._last_failure = SupervisorFailureCode.PROVIDER_TIMEOUT
            return ProviderResult(None, SupervisorFailureCode.PROVIDER_TIMEOUT)
        except OpenAITransportAuthenticationError:
            self._last_failure = SupervisorFailureCode.PROVIDER_UNAVAILABLE
            return ProviderResult(None, SupervisorFailureCode.PROVIDER_UNAVAILABLE)
        except OpenAITransportRateLimitError:
            self._last_failure = SupervisorFailureCode.FAIL_CLOSED
            return ProviderResult(None, SupervisorFailureCode.FAIL_CLOSED)
        except (
            OpenAITransportConnectionError,
            OpenAITransportConfigurationError,
            OpenAITransportInternalError,
            OpenAITransportRejectedError,
        ):
            self._last_failure = SupervisorFailureCode.PROVIDER_UNAVAILABLE
            return ProviderResult(None, SupervisorFailureCode.PROVIDER_UNAVAILABLE)
        except Exception:
            self._last_failure = SupervisorFailureCode.OUTPUT_INVALID
            return ProviderResult(None, SupervisorFailureCode.OUTPUT_INVALID)
        finally:
            self._gate.release()

    def status(self) -> dict:
        available = self.availability
        return {
            "provider": "OPENAI",
            "model": self._configuration.model,
            "availability": available.value,
            "localhostOnly": False,
            "mode": "SHADOW",
            "lastCheckedAt": self._last_checked.isoformat() if self._last_checked else None,
            "lastSuccessAt": self._last_success.isoformat() if self._last_success else None,
            "lastFailureCode": self._last_failure.value if self._last_failure else None,
            "operationalEffect": "NONE",
        }
