"""Fail-closed one-shot safety gate for explicitly permitted live tests."""

from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Literal, Optional, Tuple

from pydantic import Field, model_validator

from backend.ai_advisor.provider_config import ProviderName
from backend.ai_advisor.provider_models import AdvisorProviderContractModel
from backend.ai_advisor.provider_transport import OpenAITransportRequest

OPENAI_OFFICIAL_ENDPOINT = "https://api.openai.com/v1"


class LiveConnectivityFailureCode(str, Enum):
    LIVE_DISABLED = "LIVE_DISABLED"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"
    AUTHENTICATION_NOT_READY = "AUTHENTICATION_NOT_READY"
    PROVIDER_NOT_READY = "PROVIDER_NOT_READY"
    CREDENTIAL_NOT_READY = "CREDENTIAL_NOT_READY"
    MODEL_NOT_ALLOWED = "MODEL_NOT_ALLOWED"
    ENDPOINT_NOT_ALLOWED = "ENDPOINT_NOT_ALLOWED"
    REQUEST_BUDGET_EXHAUSTED = "REQUEST_BUDGET_EXHAUSTED"
    TOKEN_BUDGET_INVALID = "TOKEN_BUDGET_INVALID"
    LIVE_PERMIT_UNAVAILABLE = "LIVE_PERMIT_UNAVAILABLE"


class LiveConnectivityPolicy(AdvisorProviderContractModel):
    endpointEnabled: bool
    networkInvocationAllowed: bool
    liveTestExplicitlyAllowed: bool = False
    killSwitchActive: bool = True
    authenticationReady: bool
    providerReady: bool
    credentialReferenceReady: bool
    provider: Literal[ProviderName.OPENAI]
    model: str = Field(min_length=1, max_length=128)
    allowedModels: Tuple[str, ...] = Field(min_length=1, max_length=8)
    providerEndpoint: Optional[str] = Field(default=None, repr=False, exclude=True)
    allowedProviderEndpoints: Tuple[str, ...] = Field(
        default=(OPENAI_OFFICIAL_ENDPOINT,),
        min_length=1,
        max_length=4,
        repr=False,
        exclude=True,
    )
    maximumLiveTestRequests: Literal[1] = 1
    maximumInputBytes: int = Field(ge=1, le=65_536)
    maximumInputTokens: int = Field(ge=1, le=65_536)
    maximumOutputTokens: int = Field(ge=1, le=16_384)
    timeoutSeconds: float = Field(gt=0, le=120)
    retryCount: Literal[0] = 0
    streamingAllowed: Literal[False] = False
    toolCallingAllowed: Literal[False] = False
    backgroundInvocationAllowed: Literal[False] = False
    batchInvocationAllowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_allowlists(self) -> "LiveConnectivityPolicy":
        if len(set(self.allowedModels)) != len(self.allowedModels):
            raise ValueError("model allowlist must be unique")
        if len(set(self.allowedProviderEndpoints)) != len(
            self.allowedProviderEndpoints
        ):
            raise ValueError("endpoint allowlist must be unique")
        return self


class LiveConnectivityDecision(AdvisorProviderContractModel):
    allowed: bool
    failureCode: Optional[LiveConnectivityFailureCode] = None
    safeMessage: Literal[
        "Live provider invocation allowed.",
        "Live provider invocation denied.",
    ]
    permitNumber: Optional[Literal[1]] = None

    @model_validator(mode="after")
    def validate_decision(self) -> "LiveConnectivityDecision":
        if self.allowed:
            if self.failureCode is not None or self.permitNumber != 1:
                raise ValueError("allowed live decision requires permit")
        elif self.failureCode is None or self.permitNumber is not None:
            raise ValueError("denied live decision requires failure")
        return self


class LiveConnectivityDeniedError(ValueError):
    def __init__(self, code: LiveConnectivityFailureCode):
        self.code = code
        super().__init__("Live provider invocation denied.")


class AtomicOneShotPermit:
    """Single-process permit which is never returned after acquisition."""

    def __init__(self):
        self._lock = Lock()
        self._consumed = 0

    @property
    def consumed(self) -> int:
        with self._lock:
            return self._consumed if self._consumed in (0, 1) else -1

    def try_acquire(self) -> bool:
        with self._lock:
            if (
                not isinstance(self._consumed, int)
                or isinstance(self._consumed, bool)
                or self._consumed != 0
            ):
                return False
            self._consumed = 1
            return True


@dataclass(frozen=True)
class LiveConnectivityGate:
    policy: LiveConnectivityPolicy
    permit: AtomicOneShotPermit = field(
        default_factory=AtomicOneShotPermit,
        repr=False,
        compare=False,
    )

    def authorize_and_acquire(
        self,
        request: OpenAITransportRequest,
    ) -> LiveConnectivityDecision:
        policy = self.policy
        if policy.killSwitchActive is not False:
            return self._denied(LiveConnectivityFailureCode.KILL_SWITCH_ACTIVE)
        try:
            trusted = OpenAITransportRequest.model_validate(
                request.model_dump(warnings=False)
            )
        except Exception:
            return self._denied(LiveConnectivityFailureCode.CONFIGURATION_INVALID)
        if (
            policy.retryCount != 0
            or policy.streamingAllowed is not False
            or policy.toolCallingAllowed is not False
            or policy.backgroundInvocationAllowed is not False
            or policy.batchInvocationAllowed is not False
            or policy.maximumLiveTestRequests != 1
        ):
            return self._denied(LiveConnectivityFailureCode.CONFIGURATION_INVALID)
        if (
            policy.endpointEnabled is not True
            or policy.networkInvocationAllowed is not True
            or policy.liveTestExplicitlyAllowed is not True
        ):
            return self._denied(LiveConnectivityFailureCode.LIVE_DISABLED)
        if policy.authenticationReady is not True:
            return self._denied(LiveConnectivityFailureCode.AUTHENTICATION_NOT_READY)
        if policy.providerReady is not True:
            return self._denied(LiveConnectivityFailureCode.PROVIDER_NOT_READY)
        if policy.credentialReferenceReady is not True:
            return self._denied(LiveConnectivityFailureCode.CREDENTIAL_NOT_READY)
        if (
            policy.provider is not ProviderName.OPENAI
            or trusted.model != policy.model
            or trusted.model not in policy.allowedModels
        ):
            return self._denied(LiveConnectivityFailureCode.MODEL_NOT_ALLOWED)
        endpoint = policy.providerEndpoint or OPENAI_OFFICIAL_ENDPOINT
        if endpoint not in policy.allowedProviderEndpoints:
            return self._denied(LiveConnectivityFailureCode.ENDPOINT_NOT_ALLOWED)
        input_bytes = len(trusted.input.encode("utf-8"))
        input_token_upper_bound = input_bytes
        if (
            input_bytes > policy.maximumInputBytes
            or input_token_upper_bound > policy.maximumInputTokens
            or trusted.maxOutputTokens > policy.maximumOutputTokens
            or trusted.maxOutputTokens < 1
            or trusted.timeoutSeconds != policy.timeoutSeconds
        ):
            return self._denied(LiveConnectivityFailureCode.TOKEN_BUDGET_INVALID)
        if self.permit.consumed != 0:
            return self._denied(LiveConnectivityFailureCode.REQUEST_BUDGET_EXHAUSTED)
        if not self.permit.try_acquire():
            return self._denied(LiveConnectivityFailureCode.LIVE_PERMIT_UNAVAILABLE)
        return LiveConnectivityDecision(
            allowed=True,
            safeMessage="Live provider invocation allowed.",
            permitNumber=1,
        )

    @staticmethod
    def _denied(code: LiveConnectivityFailureCode) -> LiveConnectivityDecision:
        return LiveConnectivityDecision(
            allowed=False,
            failureCode=code,
            safeMessage="Live provider invocation denied.",
        )
