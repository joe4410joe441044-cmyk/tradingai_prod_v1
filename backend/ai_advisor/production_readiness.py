"""Pure readiness evaluation and secret-free operational projection."""

from backend.ai_advisor.production_config_models import (
    AIAdvisorProductionConfig,
    ProductionOperationalStatus,
    ProductionReadiness,
    ProductionReadinessStatus,
)


def evaluate_production_readiness(
    configuration: AIAdvisorProductionConfig,
    *,
    authentication_reference_allowed: bool,
    provider_reference_allowed: bool,
    provider_configuration_valid: bool,
) -> ProductionReadiness:
    if configuration.endpointEnabled is not True:
        return ProductionReadiness(
            status=ProductionReadinessStatus.DISABLED,
            endpointAvailable=False,
            networkInvocationAvailable=False,
            authenticationReady=False,
            providerReady=False,
            credentialReady=False,
            safeReasons=("ENDPOINT_DISABLED",),
        )
    if (
        configuration.authenticationCredentialReference is None
        or authentication_reference_allowed is not True
    ):
        return ProductionReadiness(
            status=ProductionReadinessStatus.AUTHENTICATION_UNAVAILABLE,
            endpointAvailable=False,
            networkInvocationAvailable=False,
            authenticationReady=False,
            providerReady=provider_configuration_valid,
            credentialReady=False,
            safeReasons=("AUTHENTICATION_CONFIGURATION_UNAVAILABLE",),
        )
    if provider_configuration_valid is not True:
        return ProductionReadiness(
            status=ProductionReadinessStatus.PROVIDER_UNAVAILABLE,
            endpointAvailable=False,
            networkInvocationAvailable=False,
            authenticationReady=True,
            providerReady=False,
            credentialReady=False,
            safeReasons=("PROVIDER_CONFIGURATION_UNAVAILABLE",),
        )
    if configuration.networkInvocationAllowed is not True:
        return ProductionReadiness(
            status=ProductionReadinessStatus.READY_OFFLINE,
            endpointAvailable=True,
            networkInvocationAvailable=False,
            authenticationReady=True,
            providerReady=True,
            credentialReady=False,
            safeReasons=("NETWORK_INVOCATION_DISABLED",),
        )
    if (
        configuration.credentialReference is None
        or provider_reference_allowed is not True
    ):
        return ProductionReadiness(
            status=ProductionReadinessStatus.CREDENTIAL_UNAVAILABLE,
            endpointAvailable=True,
            networkInvocationAvailable=False,
            authenticationReady=True,
            providerReady=True,
            credentialReady=False,
            safeReasons=("PROVIDER_CREDENTIAL_UNAVAILABLE",),
        )
    return ProductionReadiness(
        status=ProductionReadinessStatus.READY_LIVE,
        endpointAvailable=True,
        networkInvocationAvailable=True,
        authenticationReady=True,
        providerReady=True,
        credentialReady=True,
        safeReasons=(),
    )


def project_operational_status(
    configuration: AIAdvisorProductionConfig,
    readiness: ProductionReadiness,
) -> ProductionOperationalStatus:
    return ProductionOperationalStatus(
        enabled=configuration.endpointEnabled,
        status=readiness.status,
        authenticationReady=readiness.authenticationReady,
        providerReady=readiness.providerReady,
        networkAllowed=configuration.networkInvocationAllowed,
        networkReady=readiness.networkInvocationAvailable,
        liveTestAllowed=configuration.liveTestExplicitlyAllowed,
        killSwitchActive=configuration.liveKillSwitchActive,
    )
