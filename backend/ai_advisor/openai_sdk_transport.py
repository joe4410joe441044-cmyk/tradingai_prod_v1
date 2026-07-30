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
from backend.ai_advisor.provider_failure_observation import (
    NoOpProviderFailureObservationSink,
    ProviderFailureObservation,
    ProviderFailureObservationSink,
    ProviderFailureStage,
    ProviderSafeReason,
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
            from openai import DefaultHttpxClient, OpenAI
        except ImportError:
            raise OpenAITransportConfigurationError(
                "advisor provider unavailable"
            ) from None
        try:
            http_client = DefaultHttpxClient(
                timeout=timeout_seconds,
                follow_redirects=False,
            )
            return OpenAI(
                api_key=credential._consume(),
                base_url=endpoint,
                timeout=timeout_seconds,
                max_retries=0,
                http_client=http_client,
            )
        except Exception:
            raise OpenAITransportConfigurationError(
                "advisor provider unavailable"
            ) from None


def _safe_http_status(exception: Exception) -> int | None:
    value = getattr(exception, "status_code", None)
    return (
        value
        if isinstance(value, int)
        and not isinstance(value, bool)
        and 400 <= value <= 599
        else None
    )


def _map_sdk_exception(
    exception: Exception,
) -> tuple[Exception, ProviderSafeReason, int | None]:
    status = _safe_http_status(exception)
    try:
        import openai

        if isinstance(exception, openai.AuthenticationError):
            mapped = OpenAITransportAuthenticationError
            reason = ProviderSafeReason.LIVE_PROVIDER_AUTHENTICATION_FAILED
        elif isinstance(exception, openai.RateLimitError):
            mapped = OpenAITransportRateLimitError
            reason = ProviderSafeReason.LIVE_PROVIDER_RATE_OR_QUOTA_LIMITED
        elif isinstance(exception, openai.PermissionDeniedError):
            mapped = OpenAITransportRejectedError
            reason = ProviderSafeReason.LIVE_PROVIDER_PERMISSION_DENIED
        elif isinstance(exception, openai.BadRequestError):
            mapped = OpenAITransportRejectedError
            reason = ProviderSafeReason.LIVE_PROVIDER_BAD_REQUEST
        elif isinstance(exception, openai.APIStatusError) and status is not None:
            mapped = OpenAITransportRejectedError
            if status >= 500:
                reason = ProviderSafeReason.LIVE_PROVIDER_SERVER_ERROR
            elif status == 429:
                reason = ProviderSafeReason.LIVE_PROVIDER_RATE_OR_QUOTA_LIMITED
            elif status == 403:
                reason = ProviderSafeReason.LIVE_PROVIDER_PERMISSION_DENIED
            elif status == 401:
                reason = ProviderSafeReason.LIVE_PROVIDER_AUTHENTICATION_FAILED
            elif status == 400:
                reason = ProviderSafeReason.LIVE_PROVIDER_BAD_REQUEST
            else:
                reason = ProviderSafeReason.LIVE_PROVIDER_UNKNOWN_FAILURE
        elif isinstance(
            exception,
            openai.APIStatusError,
        ):
            mapped = OpenAITransportRejectedError
            reason = ProviderSafeReason.LIVE_PROVIDER_UNKNOWN_FAILURE
        elif isinstance(exception, openai.APITimeoutError):
            mapped = OpenAITransportTimeout
            reason = ProviderSafeReason.LIVE_PROVIDER_TIMEOUT
        elif isinstance(exception, openai.APIConnectionError):
            mapped = OpenAITransportConnectionError
            reason = ProviderSafeReason.LIVE_PROVIDER_CONNECTION_FAILED
        elif isinstance(exception, openai.OpenAIError):
            mapped = OpenAITransportInternalError
            reason = ProviderSafeReason.LIVE_PROVIDER_UNKNOWN_FAILURE
        else:
            mapped = OpenAITransportInternalError
            reason = ProviderSafeReason.LIVE_PROVIDER_UNKNOWN_FAILURE
    except Exception:
        mapped = OpenAITransportInternalError
        reason = ProviderSafeReason.LIVE_PROVIDER_UNKNOWN_FAILURE
        status = None
    return mapped("advisor provider unavailable"), reason, status


@dataclass(frozen=True)
class OpenAISDKTransport:
    config: ProviderConnectionConfig
    credentialLoader: CredentialLoader
    clientFactory: OpenAIClientFactory
    allowNetworkInvocation: bool = False
    liveConnectivityGate: LiveConnectivityGate | None = None
    usageObservationSink: UsageObservationSink = NoOpUsageObservationSink()
    failureObservationSink: ProviderFailureObservationSink = (
        NoOpProviderFailureObservationSink()
    )

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

    def _observe_failure(
        self,
        reason: ProviderSafeReason,
        stage: ProviderFailureStage,
        *,
        attempted: bool,
        http_status: int | None = None,
    ) -> None:
        try:
            self.failureObservationSink.observe(
                ProviderFailureObservation(
                    safeReason=reason,
                    failureStage=stage,
                    httpStatus=http_status,
                    liveInvocationAttempted=attempted,
                )
            )
        except Exception:
            pass

    def invoke(self, request: OpenAITransportRequest) -> Any:
        try:
            trusted_request = OpenAITransportRequest.model_validate(
                request.model_dump(warnings=False)
            )
        except Exception:
            self._observe_failure(
                ProviderSafeReason.LIVE_PROVIDER_CLIENT_CONFIGURATION_FAILED,
                ProviderFailureStage.CONFIGURATION,
                attempted=False,
            )
            raise OpenAITransportConfigurationError(
                "advisor provider unavailable"
            ) from None
        if self.liveConnectivityGate is not None:
            decision = self.liveConnectivityGate.authorize_and_acquire(trusted_request)
            if decision.allowed is not True:
                self._observe_failure(
                    ProviderSafeReason.LIVE_PROVIDER_CLIENT_CONFIGURATION_FAILED,
                    ProviderFailureStage.CONFIGURATION,
                    attempted=False,
                )
                raise OpenAITransportConfigurationError(
                    "advisor provider unavailable"
                ) from None
        initial_guard = self._guard(credential_resolved=False)
        if (
            initial_guard.reasonCode.value != "CREDENTIAL_UNAVAILABLE"
            and initial_guard.allowed is not True
        ):
            self._observe_failure(
                ProviderSafeReason.LIVE_PROVIDER_CLIENT_CONFIGURATION_FAILED,
                ProviderFailureStage.CONFIGURATION,
                attempted=False,
            )
            raise OpenAITransportConfigurationError("advisor provider unavailable")
        reference = self.config.credentialReference
        if reference is None:
            self._observe_failure(
                ProviderSafeReason.LIVE_PROVIDER_CREDENTIAL_UNAVAILABLE,
                ProviderFailureStage.CREDENTIAL_RESOLUTION,
                attempted=False,
            )
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
            self._observe_failure(
                ProviderSafeReason.LIVE_PROVIDER_CREDENTIAL_UNAVAILABLE,
                ProviderFailureStage.CREDENTIAL_RESOLUTION,
                attempted=False,
            )
            raise OpenAITransportConfigurationError("advisor provider unavailable")
        try:
            client = self.clientFactory.create(
                credential=resolution.credential,
                endpoint=self.config.endpoint,
                timeout_seconds=self.config.timeoutSeconds,
            )
        except Exception:
            self._observe_failure(
                ProviderSafeReason.LIVE_PROVIDER_CLIENT_CONFIGURATION_FAILED,
                ProviderFailureStage.CLIENT_CREATION,
                attempted=False,
            )
            raise OpenAITransportConfigurationError(
                "advisor provider unavailable"
            ) from None
        try:
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
        except OpenAITransportAuthenticationError:
            self._observe_failure(
                ProviderSafeReason.LIVE_PROVIDER_AUTHENTICATION_FAILED,
                ProviderFailureStage.PROVIDER_INVOCATION,
                attempted=True,
            )
            raise
        except OpenAITransportRateLimitError:
            self._observe_failure(
                ProviderSafeReason.LIVE_PROVIDER_RATE_OR_QUOTA_LIMITED,
                ProviderFailureStage.PROVIDER_INVOCATION,
                attempted=True,
            )
            raise
        except OpenAITransportTimeout:
            self._observe_failure(
                ProviderSafeReason.LIVE_PROVIDER_TIMEOUT,
                ProviderFailureStage.PROVIDER_INVOCATION,
                attempted=True,
            )
            raise
        except OpenAITransportConnectionError:
            self._observe_failure(
                ProviderSafeReason.LIVE_PROVIDER_CONNECTION_FAILED,
                ProviderFailureStage.PROVIDER_INVOCATION,
                attempted=True,
            )
            raise
        except OpenAITransportRejectedError:
            self._observe_failure(
                ProviderSafeReason.LIVE_PROVIDER_UNKNOWN_FAILURE,
                ProviderFailureStage.PROVIDER_INVOCATION,
                attempted=True,
            )
            raise
        except (
            OpenAITransportConfigurationError,
            OpenAITransportInternalError,
        ):
            self._observe_failure(
                ProviderSafeReason.LIVE_PROVIDER_UNKNOWN_FAILURE,
                ProviderFailureStage.PROVIDER_INVOCATION,
                attempted=True,
            )
            raise
        except Exception as exception:
            mapped, reason, status = _map_sdk_exception(exception)
            self._observe_failure(
                reason,
                ProviderFailureStage.PROVIDER_INVOCATION,
                attempted=True,
                http_status=status,
            )
            raise mapped from None
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
            self._observe_failure(
                ProviderSafeReason.LIVE_PROVIDER_RESPONSE_CONTRACT_FAILED,
                ProviderFailureStage.RESPONSE_VALIDATION,
                attempted=True,
            )
            raise OpenAITransportRejectedError("advisor provider unavailable") from None
