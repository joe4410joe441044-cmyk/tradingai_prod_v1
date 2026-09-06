"""Fail-closed production composition root with no startup network access."""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol

from backend.ai_advisor.advisor_service import AdvisorService
from backend.ai_advisor.api_models import AdvisorAPIConfig
from backend.ai_advisor.api_rate_limit import (
    AdvisorConcurrencyLimiter,
    AdvisorRateLimiter,
)
from backend.ai_advisor.api_security import (
    CredentialLoaderBearerAuthenticator,
    RejectingAdvisorAuthenticator,
)
from backend.ai_advisor.credential_loader import CredentialLoader
from backend.ai_advisor.openai_provider import OpenAIProviderAdapter
from backend.ai_advisor.live_connectivity import (
    OPENAI_OFFICIAL_ENDPOINT,
    InteractiveConnectivityGate,
    InteractiveConnectivityPolicy,
    LiveConnectivityGate,
    LiveConnectivityPolicy,
)
from backend.ai_advisor.openai_sdk_transport import (
    DefaultOpenAIClientFactory,
    OpenAIClientFactory,
    OpenAISDKTransport,
)
from backend.ai_advisor.production_config_models import (
    AIAdvisorProductionConfig,
    ProductionConfigFailureCode,
    ProductionConfigSource,
    ProductionOperationalStatus,
    ProductionReadiness,
    ProductionReadinessStatus,
)
from backend.ai_advisor.production_readiness import (
    evaluate_production_readiness,
    project_operational_status,
)
from backend.ai_advisor.provider_config import (
    PROVIDER_CONNECTION_CONFIG_VERSION,
    ProviderConnectionConfig,
    ProviderName,
    ProviderResponseFormat,
)
from backend.ai_advisor.provider_failure_observation import (
    NoOpProviderFailureObservationSink,
    ProviderFailureObservationSink,
)
from backend.ai_advisor.semantic_validation_observation import (
    NoOpSemanticValidationObservationSink,
    SemanticValidationObservationSink,
)
from backend.ai_advisor.provider_models import (
    MAX_PROVIDER_OUTPUT_CHARACTERS,
    PROVIDER_CONFIG_VERSION,
    AdvisorModelPolicy,
    AdvisorProviderCapabilities,
    AdvisorProviderCode,
    AdvisorProviderConfig,
    AdvisorProviderResponseFormat,
    AdvisorRetryPolicy,
)
from backend.ai_advisor.provider_registry import ProviderRegistry
from backend.ai_advisor.service_models import (
    AdvisorServiceFailure,
    AdvisorServiceFailureCode,
    AdvisorServiceInput,
    AdvisorServiceResult,
    AdvisorServiceStatus,
    service_failure_message,
)
from backend.ai_advisor.response_safety_observation import (
    NoOpResponseSafetyRejectionObservationSink,
    ResponseSafetyRejectionObservationSink,
)
from backend.ai_advisor.usage_observation import (
    NoOpProviderMetadataObservationSink,
    NoOpUsageObservationSink,
    ProviderMetadataObservationSink,
    UsageObservationSink,
)
from backend.api.ai_advisor import AdvisorAPIComposition


class ProductionConfigLoader(Protocol):
    def load(self):
        """Return one typed production configuration load result."""


class ProviderInteractionPolicy(str, Enum):
    INTERACTIVE = "INTERACTIVE"
    LIVE_TEST = "LIVE_TEST"


class OfflineUnavailableAdvisorService:
    def generate_response(
        self,
        service_input: AdvisorServiceInput,
    ) -> AdvisorServiceResult:
        return AdvisorServiceResult(
            status=AdvisorServiceStatus.FAILED,
            failure=AdvisorServiceFailure(
                code=AdvisorServiceFailureCode.ADVISOR_PROVIDER_FAILURE,
                safeMessage=service_failure_message(
                    AdvisorServiceFailureCode.ADVISOR_PROVIDER_FAILURE
                ),
                retryAllowed=False,
            ),
        )


@dataclass(frozen=True)
class ProductionCompositionResult:
    succeeded: bool
    readiness: ProductionReadiness
    operationalStatus: ProductionOperationalStatus
    apiComposition: AdvisorAPIComposition = field(repr=False, compare=False)
    failureCode: ProductionConfigFailureCode | None = None
    safeMessage: str | None = None


def _api_config(configuration: AIAdvisorProductionConfig, *, enabled: bool):
    return AdvisorAPIConfig(
        enabled=enabled,
        maxRequestBytes=configuration.requestSizeLimitBytes,
        rateLimitRequests=configuration.rateLimitMaxRequests,
        rateLimitWindowSeconds=configuration.rateLimitWindowSeconds,
        concurrencyLimit=configuration.concurrencyLimit,
        concurrencyAcquireTimeoutSeconds=(
            configuration.concurrencyAcquireTimeoutSeconds
        ),
        endpointTimeoutSeconds=configuration.endpointTimeoutSeconds,
    )


def _api_composition(
    *,
    configuration: AIAdvisorProductionConfig,
    enabled: bool,
    authenticator,
    service,
    clock: Callable[[], float],
) -> AdvisorAPIComposition:
    config = _api_config(configuration, enabled=enabled)
    return AdvisorAPIComposition(
        config=config,
        authenticator=authenticator,
        service=service,
        rateLimiter=AdvisorRateLimiter(
            limit=config.rateLimitRequests,
            window_seconds=config.rateLimitWindowSeconds,
            clock=clock,
        ),
        concurrencyLimiter=AdvisorConcurrencyLimiter(
            limit=config.concurrencyLimit,
            acquire_timeout_seconds=config.concurrencyAcquireTimeoutSeconds,
        ),
    )


def _provider_service(
    configuration: AIAdvisorProductionConfig,
    *,
    provider_credential_loader: CredentialLoader,
    client_factory: OpenAIClientFactory,
    readiness: ProductionReadiness,
    usage_observation_sink: UsageObservationSink,
    metadata_observation_sink: ProviderMetadataObservationSink,
    failure_observation_sink: ProviderFailureObservationSink,
    provider_interaction_policy: ProviderInteractionPolicy,
    response_safety_observation_sink: ResponseSafetyRejectionObservationSink,
    semantic_validation_observation_sink: SemanticValidationObservationSink,
):
    connection = ProviderConnectionConfig(
        configVersion=PROVIDER_CONNECTION_CONFIG_VERSION,
        provider=ProviderName.OPENAI,
        model=configuration.model,
        credentialReference=configuration.credentialReference,
        endpoint=configuration.baseUrl,
        timeoutSeconds=configuration.providerTimeoutSeconds,
        maxOutputTokens=configuration.liveMaximumOutputTokens,
        temperature=0.0,
        responseFormat=ProviderResponseFormat.STRICT_JSON,
        enabled=True,
    )
    common_policy = dict(
        endpointEnabled=configuration.endpointEnabled,
        networkInvocationAllowed=configuration.networkInvocationAllowed,
        killSwitchActive=configuration.liveKillSwitchActive,
        authenticationReady=readiness.authenticationReady,
        providerReady=readiness.providerReady,
        credentialReferenceReady=readiness.credentialReady,
        provider=ProviderName.OPENAI,
        model=configuration.model,
        allowedModels=(configuration.model,),
        providerEndpoint=configuration.baseUrl,
        allowedProviderEndpoints=(OPENAI_OFFICIAL_ENDPOINT,),
        maximumInputBytes=configuration.liveMaximumInputBytes,
        maximumInputTokens=configuration.liveMaximumInputTokens,
        maximumOutputTokens=configuration.liveMaximumOutputTokens,
        timeoutSeconds=configuration.providerTimeoutSeconds,
        retryCount=0,
        streamingAllowed=False,
        toolCallingAllowed=False,
        backgroundInvocationAllowed=False,
        batchInvocationAllowed=False,
    )
    if provider_interaction_policy is ProviderInteractionPolicy.INTERACTIVE:
        connectivity_gate = InteractiveConnectivityGate(
            InteractiveConnectivityPolicy(
                **common_policy,
                interactiveInvocationExplicitlyAllowed=True,
            )
        )
    elif provider_interaction_policy is ProviderInteractionPolicy.LIVE_TEST:
        connectivity_gate = LiveConnectivityGate(
            LiveConnectivityPolicy(
                **common_policy,
                liveTestExplicitlyAllowed=configuration.liveTestExplicitlyAllowed,
                maximumLiveTestRequests=1,
            )
        )
    else:
        raise ValueError("provider interaction policy is not classified")
    transport = OpenAISDKTransport(
        config=connection,
        credentialLoader=provider_credential_loader,
        clientFactory=client_factory,
        allowNetworkInvocation=configuration.networkInvocationAllowed,
        liveConnectivityGate=connectivity_gate,
        usageObservationSink=usage_observation_sink,
        metadataObservationSink=metadata_observation_sink,
        failureObservationSink=failure_observation_sink,
    )
    registry = ProviderRegistry(
        {
            ProviderName.OPENAI: lambda trusted: OpenAIProviderAdapter(
                trusted,
                transport,
            )
        }
    )
    provider = registry.resolve(connection)
    return AdvisorService(
        provider=provider,
        providerConfig=AdvisorProviderConfig(
            configVersion=PROVIDER_CONFIG_VERSION,
            provider=AdvisorProviderCode.OPENAI,
            modelId=configuration.model,
            timeoutSeconds=int(configuration.providerTimeoutSeconds),
            maxOutputCharacters=MAX_PROVIDER_OUTPUT_CHARACTERS,
            retryPolicy=AdvisorRetryPolicy.NO_RETRY,
            responseFormat=AdvisorProviderResponseFormat.STRICT_JSON,
        ),
        modelPolicy=AdvisorModelPolicy(
            provider=AdvisorProviderCode.OPENAI,
            allowedModelIds=(configuration.model,),
            defaultModelId=configuration.model,
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
        failureObservationSink=failure_observation_sink,
        semanticValidationObservationSink=semantic_validation_observation_sink,
        responseSafetyObservationSink=response_safety_observation_sink,
    )


def build_ai_advisor_production_composition(
    *,
    provider_interaction_policy: ProviderInteractionPolicy,
    config_loader: ProductionConfigLoader,
    authentication_credential_loader: CredentialLoader,
    provider_credential_loader: CredentialLoader,
    allowed_authentication_credential_ids: tuple[str, ...],
    allowed_provider_credential_ids: tuple[str, ...],
    client_factory: OpenAIClientFactory | None = None,
    usage_observation_sink: UsageObservationSink = NoOpUsageObservationSink(),
    metadata_observation_sink: ProviderMetadataObservationSink = (
        NoOpProviderMetadataObservationSink()
    ),
    failure_observation_sink: ProviderFailureObservationSink = (
        NoOpProviderFailureObservationSink()
    ),
    response_safety_observation_sink: ResponseSafetyRejectionObservationSink = (
        NoOpResponseSafetyRejectionObservationSink()
    ),
    semantic_validation_observation_sink: SemanticValidationObservationSink = (
        NoOpSemanticValidationObservationSink()
    ),
    clock: Callable[[], float] = time.monotonic,
) -> ProductionCompositionResult:
    if not isinstance(provider_interaction_policy, ProviderInteractionPolicy):
        raise ValueError("provider interaction policy is not classified")
    loaded = config_loader.load()
    configuration = loaded.configuration
    if not loaded.succeeded or configuration is None:
        configuration = AIAdvisorProductionConfig(
            configVersion="ai-advisor-production-config/v1",
            source=ProductionConfigSource.INJECTED,
        )
        readiness = ProductionReadiness(
            status=ProductionReadinessStatus.CONFIGURATION_INVALID,
            endpointAvailable=False,
            networkInvocationAvailable=False,
            authenticationReady=False,
            providerReady=False,
            credentialReady=False,
            safeReasons=("CONFIGURATION_INVALID",),
        )
        status = project_operational_status(configuration, readiness)
        return ProductionCompositionResult(
            succeeded=False,
            readiness=readiness,
            operationalStatus=status,
            apiComposition=_api_composition(
                configuration=configuration,
                enabled=False,
                authenticator=RejectingAdvisorAuthenticator(),
                service=OfflineUnavailableAdvisorService(),
                clock=clock,
            ),
            failureCode=ProductionConfigFailureCode.AI_ADVISOR_CONFIG_INVALID,
            safeMessage="AI Advisor composition is unavailable.",
        )
    auth_reference = configuration.authenticationCredentialReference
    provider_reference = configuration.credentialReference
    readiness = evaluate_production_readiness(
        configuration,
        authentication_reference_allowed=(
            auth_reference is not None
            and auth_reference.credentialId in allowed_authentication_credential_ids
        ),
        provider_reference_allowed=(
            provider_reference is not None
            and provider_reference.credentialId in allowed_provider_credential_ids
        ),
        provider_configuration_valid=(
            configuration.provider is ProviderName.OPENAI
            and bool(configuration.model.strip())
        ),
    )
    endpoint_ready = readiness.endpointAvailable
    authenticator = (
        CredentialLoaderBearerAuthenticator(
            principalId=configuration.principalId,
            advisorAccessAllowed=configuration.advisorAccessAllowed,
            credentialReference=auth_reference,
            credentialLoader=authentication_credential_loader,
        )
        if endpoint_ready and auth_reference is not None
        else RejectingAdvisorAuthenticator()
    )
    service = OfflineUnavailableAdvisorService()
    failure_code = None
    safe_message = None
    succeeded = readiness.status in {
        ProductionReadinessStatus.DISABLED,
        ProductionReadinessStatus.READY_OFFLINE,
        ProductionReadinessStatus.READY_LIVE,
    }
    if readiness.status is ProductionReadinessStatus.READY_LIVE:
        try:
            service = _provider_service(
                configuration,
                provider_credential_loader=provider_credential_loader,
                client_factory=client_factory or DefaultOpenAIClientFactory(),
                readiness=readiness,
                usage_observation_sink=usage_observation_sink,
                metadata_observation_sink=metadata_observation_sink,
                failure_observation_sink=failure_observation_sink,
                provider_interaction_policy=provider_interaction_policy,
                response_safety_observation_sink=(
                    response_safety_observation_sink
                ),
                semantic_validation_observation_sink=(
                    semantic_validation_observation_sink
                ),
            )
        except Exception:
            readiness = ProductionReadiness(
                status=ProductionReadinessStatus.PROVIDER_UNAVAILABLE,
                endpointAvailable=False,
                networkInvocationAvailable=False,
                authenticationReady=True,
                providerReady=False,
                credentialReady=False,
                safeReasons=("COMPOSITION_FAILED",),
            )
            endpoint_ready = False
            authenticator = RejectingAdvisorAuthenticator()
            succeeded = False
            failure_code = ProductionConfigFailureCode.AI_ADVISOR_COMPOSITION_FAILED
            safe_message = "AI Advisor composition is unavailable."
    elif not succeeded:
        failure_code = ProductionConfigFailureCode.AI_ADVISOR_COMPOSITION_FAILED
        safe_message = "AI Advisor composition is unavailable."
    status = project_operational_status(configuration, readiness)
    return ProductionCompositionResult(
        succeeded=succeeded,
        readiness=readiness,
        operationalStatus=status,
        apiComposition=_api_composition(
            configuration=configuration,
            enabled=endpoint_ready,
            authenticator=authenticator,
            service=service,
            clock=clock,
        ),
        failureCode=failure_code,
        safeMessage=safe_message,
    )
