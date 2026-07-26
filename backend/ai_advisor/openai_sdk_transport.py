"""Guarded OpenAI SDK transport with lazy imports and no implicit retries."""

from dataclasses import dataclass
from typing import Any, Protocol

from backend.ai_advisor.credential_loader import (
    CredentialLoader,
    CredentialResolutionInput,
    CredentialResolutionStatus,
    EphemeralCredential,
)
from backend.ai_advisor.live_connectivity import LiveConnectivityGate
from backend.ai_advisor.provider_config import ProviderConnectionConfig, ProviderName
from backend.ai_advisor.provider_invocation_guard import (
    InvocationGuardInput,
    evaluate_invocation_guard,
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
from backend.ai_advisor.usage_observation import (
    NoOpUsageObservationSink,
    UsageObservationSink,
    project_sdk_usage,
)


class OpenAIClientFactory(Protocol):
    def create(
        self,
        *,
        credential: EphemeralCredential,
        endpoint: str | None,
        timeout_seconds: float,
    ) -> Any:
        """Create one SDK client without caching credentials."""


@dataclass(frozen=True)
class DefaultOpenAIClientFactory:
    def create(
        self,
        *,
        credential: EphemeralCredential,
        endpoint: str | None,
        timeout_seconds: float,
    ) -> Any:
        try:
            from openai import OpenAI
        except ImportError:
            raise OpenAITransportConfigurationError(
                "advisor provider unavailable"
            ) from None
        try:
            return OpenAI(
                api_key=credential._consume(),
                base_url=endpoint,
                timeout=timeout_seconds,
                max_retries=0,
            )
        except Exception:
            raise OpenAITransportConfigurationError(
                "advisor provider unavailable"
            ) from None


def _map_sdk_exception(exception: Exception) -> Exception:
    try:
        import openai

        if isinstance(exception, openai.AuthenticationError):
            mapped = OpenAITransportAuthenticationError
        elif isinstance(exception, openai.RateLimitError):
            mapped = OpenAITransportRateLimitError
        elif isinstance(
            exception,
            (
                openai.PermissionDeniedError,
                openai.BadRequestError,
                openai.APIStatusError,
            ),
        ):
            mapped = OpenAITransportRejectedError
        elif isinstance(exception, openai.APITimeoutError):
            mapped = OpenAITransportTimeout
        elif isinstance(exception, openai.APIConnectionError):
            mapped = OpenAITransportConnectionError
        elif isinstance(exception, openai.OpenAIError):
            mapped = OpenAITransportInternalError
        else:
            mapped = OpenAITransportInternalError
    except Exception:
        mapped = OpenAITransportInternalError
    return mapped("advisor provider unavailable")


@dataclass(frozen=True)
class OpenAISDKTransport:
    config: ProviderConnectionConfig
    credentialLoader: CredentialLoader
    clientFactory: OpenAIClientFactory
    allowNetworkInvocation: bool = False
    liveConnectivityGate: LiveConnectivityGate | None = None
    usageObservationSink: UsageObservationSink = NoOpUsageObservationSink()

    def __post_init__(self) -> None:
        if not isinstance(self.allowNetworkInvocation, bool):
            raise TypeError("strict network invocation flag required")
        try:
            trusted = ProviderConnectionConfig.model_validate(
                self.config.model_dump(warnings=False)
            )
        except Exception:
            raise ValueError("advisor provider configuration invalid") from None
        object.__setattr__(self, "config", trusted)

    def _guard(self, *, credential_resolved: bool):
        return evaluate_invocation_guard(
            InvocationGuardInput(
                providerEnabled=self.config.enabled,
                provider=self.config.provider,
                networkInvocationAllowed=self.allowNetworkInvocation,
                credentialResolved=credential_resolved,
                transportConfigured=True,
                configurationValid=True,
            )
        )

    def invoke(self, request: OpenAITransportRequest) -> Any:
        try:
            trusted_request = OpenAITransportRequest.model_validate(
                request.model_dump(warnings=False)
            )
        except Exception:
            raise OpenAITransportConfigurationError(
                "advisor provider unavailable"
            ) from None
        if self.liveConnectivityGate is not None:
            decision = self.liveConnectivityGate.authorize_and_acquire(trusted_request)
            if decision.allowed is not True:
                raise OpenAITransportConfigurationError(
                    "advisor provider unavailable"
                ) from None
        initial_guard = self._guard(credential_resolved=False)
        if (
            initial_guard.reasonCode.value != "CREDENTIAL_UNAVAILABLE"
            and initial_guard.allowed is not True
        ):
            raise OpenAITransportConfigurationError("advisor provider unavailable")
        reference = self.config.credentialReference
        if reference is None:
            raise OpenAITransportConfigurationError("advisor provider unavailable")
        resolution = self.credentialLoader.resolve(
            CredentialResolutionInput(
                credentialReference=reference,
                provider=ProviderName.OPENAI,
                allowEnvironmentRead=reference.source.value == "ENVIRONMENT",
            )
        )
        if (
            resolution.status is not CredentialResolutionStatus.SUCCEEDED
            or resolution.credential is None
            or self._guard(credential_resolved=True).allowed is not True
        ):
            raise OpenAITransportConfigurationError("advisor provider unavailable")
        try:
            client = self.clientFactory.create(
                credential=resolution.credential,
                endpoint=self.config.endpoint,
                timeout_seconds=self.config.timeoutSeconds,
            )
            response = client.responses.create(
                model=trusted_request.model,
                input=trusted_request.input,
                max_output_tokens=trusted_request.maxOutputTokens,
                temperature=trusted_request.temperature,
                text={"format": {"type": "json_object"}},
                stream=False,
                store=False,
                timeout=trusted_request.timeoutSeconds,
            )
        except (
            OpenAITransportAuthenticationError,
            OpenAITransportConfigurationError,
            OpenAITransportConnectionError,
            OpenAITransportInternalError,
            OpenAITransportRateLimitError,
            OpenAITransportRejectedError,
            OpenAITransportTimeout,
        ):
            raise
        except Exception as exception:
            raise _map_sdk_exception(exception) from None
        try:
            self.usageObservationSink.observe(project_sdk_usage(response))
        except Exception:
            pass
        try:
            text = response.output_text
            status = getattr(response, "status", "completed")
            if not isinstance(text, str) or not text.strip():
                raise ValueError
            if len(text) > 64_000:
                raise ValueError
            if status not in {"completed", None}:
                raise ValueError
            return {"output_text": text, "finish_reason": "completed"}
        except Exception:
            raise OpenAITransportRejectedError("advisor provider unavailable") from None
