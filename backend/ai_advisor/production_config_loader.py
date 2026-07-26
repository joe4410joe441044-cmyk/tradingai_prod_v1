"""Explicit production configuration loaders without secret resolution."""

import os
from dataclasses import dataclass, field
from typing import Callable, Mapping

from backend.ai_advisor.production_config_models import (
    PRODUCTION_CONFIG_VERSION,
    AIAdvisorProductionConfig,
    ProductionConfigFailureCode,
    ProductionConfigLoadResult,
    ProductionConfigSource,
)
from backend.ai_advisor.provider_config import (
    CredentialReference,
    CredentialSource,
    ProviderName,
)

ENVIRONMENT_KEYS = {
    "endpointEnabled": "AI_ADVISOR_ENDPOINT_ENABLED",
    "networkInvocationAllowed": "AI_ADVISOR_NETWORK_ALLOWED",
    "provider": "AI_ADVISOR_PROVIDER",
    "model": "AI_ADVISOR_MODEL",
    "credentialId": "AI_ADVISOR_CREDENTIAL_ID",
    "credentialSource": "AI_ADVISOR_CREDENTIAL_SOURCE",
    "authenticationCredentialId": "AI_ADVISOR_AUTH_CREDENTIAL_ID",
    "authenticationCredentialSource": "AI_ADVISOR_AUTH_CREDENTIAL_SOURCE",
    "baseUrl": "AI_ADVISOR_BASE_URL",
    "providerTimeoutSeconds": "AI_ADVISOR_PROVIDER_TIMEOUT_SECONDS",
    "endpointTimeoutSeconds": "AI_ADVISOR_ENDPOINT_TIMEOUT_SECONDS",
    "requestSizeLimitBytes": "AI_ADVISOR_REQUEST_SIZE_LIMIT_BYTES",
    "rateLimitWindowSeconds": "AI_ADVISOR_RATE_LIMIT_WINDOW_SECONDS",
    "rateLimitMaxRequests": "AI_ADVISOR_RATE_LIMIT_MAX_REQUESTS",
    "concurrencyLimit": "AI_ADVISOR_CONCURRENCY_LIMIT",
    "concurrencyAcquireTimeoutSeconds": (
        "AI_ADVISOR_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS"
    ),
    "principalId": "AI_ADVISOR_PRINCIPAL_ID",
    "advisorAccessAllowed": "AI_ADVISOR_ACCESS_ALLOWED",
    "liveTestExplicitlyAllowed": "AI_ADVISOR_LIVE_TEST_ALLOWED",
    "liveKillSwitchActive": "AI_ADVISOR_LIVE_KILL_SWITCH",
    "liveMaximumInputBytes": "AI_ADVISOR_LIVE_MAX_INPUT_BYTES",
    "liveMaximumInputTokens": "AI_ADVISOR_LIVE_MAX_INPUT_TOKENS",
    "liveMaximumOutputTokens": "AI_ADVISOR_LIVE_MAX_OUTPUT_TOKENS",
}


def _failure(
    code=ProductionConfigFailureCode.AI_ADVISOR_CONFIG_INVALID,
) -> ProductionConfigLoadResult:
    return ProductionConfigLoadResult(
        succeeded=False,
        failureCode=code,
        safeMessage="AI Advisor configuration is invalid.",
    )


def _strict_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError("invalid boolean")


def _optional_float(value: str | None, default: float) -> float:
    return default if value is None else float(value)


def _optional_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    if not value or any(character not in "0123456789" for character in value):
        raise ValueError("invalid integer")
    return int(value)


def _build(
    values: Mapping[str, str],
    *,
    source: ProductionConfigSource,
) -> ProductionConfigLoadResult:
    try:
        if set(values) - set(ENVIRONMENT_KEYS):
            raise ValueError("unknown configuration field")
        endpoint_enabled = _strict_bool(
            values.get("endpointEnabled"),
            default=False,
        )
        network_allowed = _strict_bool(
            values.get("networkInvocationAllowed"),
            default=False,
        )
        access_allowed = _strict_bool(
            values.get("advisorAccessAllowed"),
            default=True,
        )
        credential_id = values.get("credentialId")
        auth_id = values.get("authenticationCredentialId")
        default_credential_source = (
            CredentialSource.ENVIRONMENT
            if source is ProductionConfigSource.ENVIRONMENT
            else CredentialSource.INJECTED
        )
        credential_source = CredentialSource(
            values.get("credentialSource", default_credential_source.value)
        )
        authentication_credential_source = CredentialSource(
            values.get(
                "authenticationCredentialSource",
                default_credential_source.value,
            )
        )
        configuration = AIAdvisorProductionConfig(
            configVersion=PRODUCTION_CONFIG_VERSION,
            source=source,
            endpointEnabled=endpoint_enabled,
            networkInvocationAllowed=network_allowed,
            provider=ProviderName(values.get("provider", "OPENAI")),
            model=values.get("model", "openai-advisor-model"),
            credentialReference=(
                CredentialReference(
                    credentialId=credential_id,
                    source=credential_source,
                )
                if credential_id is not None
                else None
            ),
            authenticationCredentialReference=(
                CredentialReference(
                    credentialId=auth_id,
                    source=authentication_credential_source,
                )
                if auth_id is not None
                else None
            ),
            baseUrl=values.get("baseUrl"),
            principalId=values.get("principalId", "ai-advisor-user"),
            advisorAccessAllowed=access_allowed,
            liveTestExplicitlyAllowed=_strict_bool(
                values.get("liveTestExplicitlyAllowed"),
                default=False,
            ),
            liveKillSwitchActive=_strict_bool(
                values.get("liveKillSwitchActive"),
                default=True,
            ),
            liveMaximumInputBytes=_optional_int(
                values.get("liveMaximumInputBytes"), 16_384
            ),
            liveMaximumInputTokens=_optional_int(
                values.get("liveMaximumInputTokens"), 16_384
            ),
            liveMaximumOutputTokens=_optional_int(
                values.get("liveMaximumOutputTokens"), 4096
            ),
            providerTimeoutSeconds=_optional_float(
                values.get("providerTimeoutSeconds"), 30.0
            ),
            endpointTimeoutSeconds=_optional_float(
                values.get("endpointTimeoutSeconds"), 35.0
            ),
            requestSizeLimitBytes=_optional_int(
                values.get("requestSizeLimitBytes"), 65_536
            ),
            rateLimitWindowSeconds=_optional_float(
                values.get("rateLimitWindowSeconds"), 60.0
            ),
            rateLimitMaxRequests=_optional_int(values.get("rateLimitMaxRequests"), 10),
            concurrencyLimit=_optional_int(values.get("concurrencyLimit"), 2),
            concurrencyAcquireTimeoutSeconds=_optional_float(
                values.get("concurrencyAcquireTimeoutSeconds"), 0.01
            ),
        )
        return ProductionConfigLoadResult(
            succeeded=True,
            configuration=configuration,
        )
    except Exception:
        return _failure()


@dataclass(frozen=True)
class EnvironmentProductionConfigLoader:
    environmentReader: Callable[[str], str | None] = field(
        default=os.environ.get,
        repr=False,
        compare=False,
    )

    def load(self) -> ProductionConfigLoadResult:
        try:
            values = {
                field_name: value
                for field_name, environment_name in ENVIRONMENT_KEYS.items()
                if (value := self.environmentReader(environment_name)) is not None
            }
        except Exception:
            return _failure()
        return _build(values, source=ProductionConfigSource.ENVIRONMENT)


@dataclass(frozen=True)
class InjectedProductionConfigLoader:
    values: Mapping[str, str] = field(repr=False)

    def load(self) -> ProductionConfigLoadResult:
        return _build(
            dict(self.values),
            source=ProductionConfigSource.INJECTED,
        )
