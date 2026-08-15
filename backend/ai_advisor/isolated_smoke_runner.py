"""Process-scoped, fail-closed runner for an isolated AI Advisor smoke test."""

import argparse
import asyncio
import hashlib
import hmac
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from types import MappingProxyType
from typing import Callable, Literal, TextIO, Tuple

import httpx
from fastapi import FastAPI
from pydantic import ConfigDict, Field, field_validator, model_validator

from backend.ai_advisor.context_builder import build_advisor_context
from backend.ai_advisor.conversation_models import (
    AdvisorCapability,
    AdvisorDetailLevel,
    AdvisorPermissionContext,
    AdvisorRequest,
    AdvisorResponseFormat,
    AdvisorResponsePreferences,
    AuthenticationState,
    AuthorizationState,
)
from backend.ai_advisor.credential_loader import (
    CredentialLoader,
    CredentialResolutionInput,
    CredentialResolutionStatus,
)
from backend.ai_advisor.live_connectivity import OPENAI_OFFICIAL_ENDPOINT
from backend.ai_advisor.openai_sdk_transport import OpenAIClientFactory
from backend.ai_advisor.production_composition import (
    ProviderInteractionPolicy,
    ProductionCompositionResult,
    build_ai_advisor_production_composition,
)
from backend.ai_advisor.production_config_models import (
    ProductionConfigLoadResult,
    ProductionReadinessStatus,
)
from backend.ai_advisor.production_config_loader import (
    EnvironmentProductionConfigLoader,
)
from backend.ai_advisor.provider_config import CredentialSource, ProviderName
from backend.ai_advisor.provider_failure_observation import (
    ProviderFailureObservation,
    ProviderFailureStage,
    ProviderSafeReason,
    RecordingProviderFailureObservationSink,
    ResponseContractDiagnostic,
    ResponseContractField,
    ResponseTopLevelType,
    ResponseValidationCode,
)
from backend.ai_advisor.provider_models import AdvisorProviderContractModel
from backend.ai_advisor.service_models import (
    AdvisorServiceContextInput,
    AdvisorServiceInput,
)
from backend.ai_advisor.usage_observation import (
    AdvisorTokenUsage,
    RecordingProviderMetadataObservationSink,
    RecordingUsageObservationSink,
    SafeEndpointClassification,
    SafeProviderName,
    UsageObservationStatus,
    safe_metadata_identifier,
)
from backend.ai_advisor.systemd_credential_loader import (
    SystemdCredentialAvailability,
    SystemdCredentialLoader,
)
from backend.api.ai_advisor import create_advice_router

SMOKE_OUTPUT_TOKENS = 512
SMOKE_MODEL = "gpt-4o-mini"
_PLACEHOLDER_MODELS = frozenset({"openai-advisor-model", "placeholder", "unknown"})
_LIVE_APPROVAL_SHA256 = (
    "354c95f58c289a835d81b32b66a7ad9396a8d688139bf5229f23785d59f2fc3c"
)


def isolated_non_secret_environment():
    """Return an immutable, process-only view of approved smoke configuration."""

    return MappingProxyType(
        {
            "AI_ADVISOR_ENDPOINT_ENABLED": "true",
            "AI_ADVISOR_NETWORK_ALLOWED": "true",
            "AI_ADVISOR_LIVE_TEST_ALLOWED": "true",
            "AI_ADVISOR_LIVE_KILL_SWITCH": "false",
            "AI_ADVISOR_AUTH_CREDENTIAL_ID": "AI_ADVISOR_AUTH_TOKEN",
            "AI_ADVISOR_AUTH_CREDENTIAL_SOURCE": "SYSTEMD_CREDENTIAL",
            "AI_ADVISOR_CREDENTIAL_ID": "OPENAI_API_KEY",
            "AI_ADVISOR_CREDENTIAL_SOURCE": "SYSTEMD_CREDENTIAL",
            "AI_ADVISOR_MODEL": SMOKE_MODEL,
            "AI_ADVISOR_BASE_URL": OPENAI_OFFICIAL_ENDPOINT,
            "AI_ADVISOR_LIVE_MAX_OUTPUT_TOKENS": str(SMOKE_OUTPUT_TOKENS),
            "AI_ADVISOR_PROVIDER_TIMEOUT_SECONDS": "30",
            "AI_ADVISOR_ENDPOINT_TIMEOUT_SECONDS": "35",
        }
    )


class SmokeTestMode(str, Enum):
    DRY_RUN = "DRY_RUN"
    LIVE_ONE_SHOT = "LIVE_ONE_SHOT"


class SmokePreflightStatus(str, Enum):
    READY_FOR_CONFIGURATION = "READY_FOR_CONFIGURATION"
    MODEL_DECISION_REQUIRED = "MODEL_DECISION_REQUIRED"
    CREDENTIAL_REFERENCE_NOT_READY = "CREDENTIAL_REFERENCE_NOT_READY"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"
    BLOCKED = "BLOCKED"


class CredentialReferenceStatus(str, Enum):
    REFERENCE_ALLOWED = "REFERENCE_ALLOWED"
    REFERENCE_NOT_ALLOWED = "REFERENCE_NOT_ALLOWED"


class CredentialSourceStatus(str, Enum):
    SOURCE_AVAILABLE = "SOURCE_AVAILABLE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class CredentialAvailabilityStatus(str, Enum):
    AVAILABILITY_UNVERIFIED = "AVAILABILITY_UNVERIFIED"


class CredentialReferencePreflight(AdvisorProviderContractModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        hide_input_in_errors=True,
    )

    authenticationReference: CredentialReferenceStatus
    authenticationSource: CredentialSourceStatus
    authenticationAvailability: CredentialAvailabilityStatus
    providerReference: CredentialReferenceStatus
    providerSource: CredentialSourceStatus
    providerAvailability: CredentialAvailabilityStatus


class IsolatedSmokeResult(AdvisorProviderContractModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        hide_input_in_errors=True,
    )

    mode: SmokeTestMode
    status: SmokePreflightStatus
    compositionBuilt: bool
    liveInvocationAttempted: bool
    invocationSucceeded: bool
    maximumProviderCalls: Literal[1] = 1
    providerRequestUpperBound: Literal[1] = 1
    retryPerformed: Literal[False] = False
    request_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    model: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    provider: SafeProviderName | None = None
    endpoint_classification: SafeEndpointClassification | None = None
    failureStage: ProviderFailureStage | None = None
    httpStatus: int | None = Field(default=None, ge=400, le=599)
    parseSucceeded: Literal[False] | None = None
    validationCode: ResponseValidationCode | None = None
    topLevelType: ResponseTopLevelType | None = None
    invalidField: ResponseContractField | None = None
    missingFields: Tuple[ResponseContractField, ...] = Field(
        default_factory=tuple,
        max_length=11,
        strict=False,
    )
    usageStatus: UsageObservationStatus = UsageObservationStatus.USAGE_UNAVAILABLE
    usage: AdvisorTokenUsage | None = None
    safeReasons: Tuple[str, ...]

    @field_validator("request_id", "model")
    @classmethod
    def validate_safe_metadata(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        return safe_metadata_identifier(value)

    @model_validator(mode="after")
    def validate_usage(self) -> "IsolatedSmokeResult":
        if (self.usageStatus is UsageObservationStatus.AVAILABLE) != (
            self.usage is not None
        ):
            raise ValueError("smoke usage invariant failed")
        classified_metadata = (
            self.model,
            self.provider,
            self.endpoint_classification,
        )
        if any(value is not None for value in classified_metadata) and not all(
            value is not None for value in classified_metadata
        ):
            raise ValueError("smoke provider metadata invariant failed")
        if self.request_id is not None and not all(
            value is not None for value in classified_metadata
        ):
            raise ValueError("smoke request metadata invariant failed")
        if self.invocationSucceeded and not all(
            value is not None for value in classified_metadata
        ):
            raise ValueError("successful smoke metadata required")
        diagnostic_values = (
            self.parseSucceeded,
            self.validationCode,
            self.topLevelType,
            self.invalidField,
        )
        has_diagnostic = any(value is not None for value in diagnostic_values) or bool(
            self.missingFields
        )
        if has_diagnostic:
            if (
                self.parseSucceeded is not False
                or self.validationCode is None
                or self.topLevelType is None
            ):
                raise ValueError("smoke response diagnostic invariant failed")
            ResponseContractDiagnostic(
                parseSucceeded=False,
                validationCode=self.validationCode,
                topLevelType=self.topLevelType,
                invalidField=self.invalidField,
                missingFields=self.missingFields,
            )
        return self


def sanitize_safe_result_stream(source: TextIO, target: TextIO) -> int:
    """Emit one fixed safe projection without rendering rejected input."""

    candidates: list[dict] = []
    unsafe_candidates = 0
    expected_fields = frozenset(IsolatedSmokeResult.model_fields)
    for line in source:
        decoded = None
        try:
            decoded = json.loads(line)
            if not isinstance(decoded, dict) or set(decoded) != expected_fields:
                if isinstance(decoded, dict):
                    unsafe_candidates += 1
                continue
            candidate = IsolatedSmokeResult.model_validate_json(line)
            candidates.append(candidate.model_dump(mode="json"))
        except Exception:
            if isinstance(decoded, dict):
                unsafe_candidates += 1
            continue

    if len(candidates) > 1:
        status = "MULTIPLE_CANDIDATES"
        exit_code = 21
        projection = {}
    elif unsafe_candidates:
        status = "UNSAFE_OR_UNKNOWN_FIELD_REJECTED"
        exit_code = 22
        projection = {}
    elif not candidates:
        status = "NOT_FOUND"
        exit_code = 20
        projection = {}
    else:
        status = "RECOVERED"
        exit_code = 0
        projection = candidates[0]
    target.write(
        json.dumps(
            {
                "recoveryStatus": status,
                "safeResultCandidates": len(candidates),
                "unsafeCandidatesRejected": unsafe_candidates,
                "safeProjection": projection,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    return exit_code


def smoke_result_exit_code(result: IsolatedSmokeResult) -> int:
    """Map a completed smoke result to a process exit code in one place."""
    if result.status is not SmokePreflightStatus.READY_FOR_CONFIGURATION:
        return 2 if result.status is SmokePreflightStatus.CONFIGURATION_INVALID else 1
    if result.mode is SmokeTestMode.DRY_RUN:
        succeeded = (
            result.compositionBuilt
            and not result.liveInvocationAttempted
            and not result.invocationSucceeded
            and result.safeReasons == ("DRY_RUN_COMPLETE",)
        )
    else:
        succeeded = (
            result.compositionBuilt
            and result.liveInvocationAttempted
            and result.invocationSucceeded
            and result.safeReasons
            in (("LIVE_ONE_SHOT_COMPLETE",), ("USAGE_UNAVAILABLE",))
        )
    return 0 if succeeded else 1


def _unexpected_cli_failure(mode: SmokeTestMode) -> IsolatedSmokeResult:
    return IsolatedSmokeResult(
        mode=mode,
        status=SmokePreflightStatus.BLOCKED,
        compositionBuilt=False,
        liveInvocationAttempted=False,
        invocationSucceeded=False,
        safeReasons=("UNEXPECTED_FAILURE",),
    )


def _cli_approval_failure(
    mode: SmokeTestMode,
    reason: str,
) -> IsolatedSmokeResult:
    return IsolatedSmokeResult(
        mode=mode,
        status=SmokePreflightStatus.BLOCKED,
        compositionBuilt=False,
        liveInvocationAttempted=False,
        invocationSucceeded=False,
        safeReasons=(reason,),
    )


@dataclass(frozen=True)
class _LoadedConfig:
    result: ProductionConfigLoadResult

    def load(self) -> ProductionConfigLoadResult:
        return self.result


def inspect_credential_references(
    *,
    configuration,
    allowed_authentication_ids: tuple[str, ...],
    allowed_provider_ids: tuple[str, ...],
) -> CredentialReferencePreflight:
    """Inspect references and source compatibility without resolving either secret."""

    authentication = configuration.authenticationCredentialReference
    provider = configuration.credentialReference
    return CredentialReferencePreflight(
        authenticationReference=(
            CredentialReferenceStatus.REFERENCE_ALLOWED
            if authentication is not None
            and authentication.credentialId in allowed_authentication_ids
            else CredentialReferenceStatus.REFERENCE_NOT_ALLOWED
        ),
        authenticationSource=(
            CredentialSourceStatus.SOURCE_AVAILABLE
            if authentication is not None
            and authentication.source
            in {
                CredentialSource.ENVIRONMENT,
                CredentialSource.SYSTEMD_CREDENTIAL,
            }
            else CredentialSourceStatus.SOURCE_UNAVAILABLE
        ),
        authenticationAvailability=(
            CredentialAvailabilityStatus.AVAILABILITY_UNVERIFIED
        ),
        providerReference=(
            CredentialReferenceStatus.REFERENCE_ALLOWED
            if provider is not None and provider.credentialId in allowed_provider_ids
            else CredentialReferenceStatus.REFERENCE_NOT_ALLOWED
        ),
        providerSource=(
            CredentialSourceStatus.SOURCE_AVAILABLE
            if provider is not None
            and provider.source
            in {
                CredentialSource.ENVIRONMENT,
                CredentialSource.SYSTEMD_CREDENTIAL,
            }
            else CredentialSourceStatus.SOURCE_UNAVAILABLE
        ),
        providerAvailability=CredentialAvailabilityStatus.AVAILABILITY_UNVERIFIED,
    )


def isolated_failure_shutdown_steps() -> tuple[str, ...]:
    """Return the fixed no-retry shutdown sequence for operator tooling."""

    return (
        "DO_NOT_RETRY",
        "DO_NOT_REGENERATE_PERMIT",
        "DO_NOT_CHANGE_MODEL_OR_BUDGET",
        "TERMINATE_ISOLATED_PROCESS",
        "DISCARD_PROCESS_SCOPED_SECRET_AND_MAPPING",
        "REVERIFY_NORMAL_SERVICE_SAFE_STATE",
        "REPORT_SAFE_FAILURE_ONLY",
    )


def build_fixed_synthetic_request(
    *,
    generated_at: datetime,
    principal_id: str = "isolated-smoke-test",
) -> AdvisorServiceInput:
    """Build the only request accepted by this runner; no trading data is included."""

    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    generated_at = generated_at.astimezone(timezone.utc)
    permission = AdvisorPermissionContext(
        principalId=principal_id,
        authenticationState=AuthenticationState.AUTHENTICATED,
        authorizationState=AuthorizationState.AUTHORIZED,
        role="USER",
        permissionLevel="READ_ONLY",
        allowedCapabilities=(AdvisorCapability.SYSTEM_GUIDANCE,),
        dataAccessScope=(),
        policyVersion="1.0",
        trustedServerContext=True,
    )
    context = build_advisor_context(
        generated_at=generated_at,
        permission_context=permission,
    )
    request = AdvisorRequest(
        schemaVersion="1.0",
        requestId="isolated-smoke-request",
        message="Explain the role and safety limits of this read-only advisor.",
        locale="en-US",
        requestedAt=generated_at,
        permissionContext=permission,
        contextEnvelope=context,
        responsePreferences=AdvisorResponsePreferences(
            locale="en-US",
            detailLevel=AdvisorDetailLevel.BRIEF,
            includeSources=False,
            includeWarnings=True,
            format=AdvisorResponseFormat.STRUCTURED,
        ),
    )
    return AdvisorServiceInput(
        request=request,
        contextInput=AdvisorServiceContextInput(generatedAt=generated_at),
        providerRequestId="isolated-smoke-provider-request",
        receivedAt=generated_at,
    )


@dataclass
class IsolatedSmokeTestRunner:
    configLoader: object = field(repr=False, compare=False)
    authenticationCredentialLoader: CredentialLoader = field(repr=False, compare=False)
    providerCredentialLoader: CredentialLoader = field(repr=False, compare=False)
    allowedAuthenticationCredentialIds: tuple[str, ...] = field(repr=False)
    allowedProviderCredentialIds: tuple[str, ...] = field(repr=False)
    approvedModels: tuple[str, ...]
    clientFactory: OpenAIClientFactory | None = field(
        default=None, repr=False, compare=False
    )
    clock: Callable[[], float] = field(default=lambda: 0.0, repr=False, compare=False)
    _liveComposition: ProductionCompositionResult | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _liveLock: Lock = field(default_factory=Lock, init=False, repr=False, compare=False)
    _usageSink: RecordingUsageObservationSink = field(
        default_factory=RecordingUsageObservationSink,
        init=False,
        repr=False,
        compare=False,
    )
    _metadataSink: RecordingProviderMetadataObservationSink = field(
        default_factory=RecordingProviderMetadataObservationSink,
        init=False,
        repr=False,
        compare=False,
    )
    _failureSink: RecordingProviderFailureObservationSink = field(
        default_factory=RecordingProviderFailureObservationSink,
        init=False,
        repr=False,
        compare=False,
    )

    @staticmethod
    def _result(
        mode: SmokeTestMode,
        status: SmokePreflightStatus,
        reason: str,
        *,
        composition_built: bool = False,
        attempted: bool = False,
        succeeded: bool = False,
        usage_status: UsageObservationStatus = (
            UsageObservationStatus.USAGE_UNAVAILABLE
        ),
        usage: AdvisorTokenUsage | None = None,
        request_id: str | None = None,
        model: str | None = None,
        provider: SafeProviderName | None = None,
        endpoint_classification: SafeEndpointClassification | None = None,
        failure_observation: ProviderFailureObservation | None = None,
    ) -> IsolatedSmokeResult:
        return IsolatedSmokeResult(
            mode=mode,
            status=status,
            compositionBuilt=composition_built,
            liveInvocationAttempted=attempted,
            invocationSucceeded=succeeded,
            request_id=request_id,
            model=model,
            provider=provider,
            endpoint_classification=endpoint_classification,
            failureStage=(
                failure_observation.failureStage
                if failure_observation is not None
                else None
            ),
            httpStatus=(
                failure_observation.httpStatus
                if failure_observation is not None
                else None
            ),
            parseSucceeded=(
                failure_observation.parseSucceeded
                if failure_observation is not None
                else None
            ),
            validationCode=(
                failure_observation.validationCode
                if failure_observation is not None
                else None
            ),
            topLevelType=(
                failure_observation.topLevelType
                if failure_observation is not None
                else None
            ),
            invalidField=(
                failure_observation.invalidField
                if failure_observation is not None
                else None
            ),
            missingFields=(
                failure_observation.missingFields
                if failure_observation is not None
                else ()
            ),
            usageStatus=usage_status,
            usage=usage,
            safeReasons=(
                (failure_observation.safeReason.value,)
                if failure_observation is not None
                else (reason,)
            ),
        )

    def _load_and_validate(self, mode: SmokeTestMode):
        loaded = self.configLoader.load()
        if not loaded.succeeded or loaded.configuration is None:
            return (
                None,
                None,
                self._result(
                    mode,
                    SmokePreflightStatus.CONFIGURATION_INVALID,
                    "CONFIGURATION_INVALID",
                ),
            )
        config = loaded.configuration
        if (
            mode is SmokeTestMode.LIVE_ONE_SHOT
            and config.liveKillSwitchActive is not False
        ):
            return (
                None,
                None,
                self._result(
                    mode,
                    SmokePreflightStatus.BLOCKED,
                    "KILL_SWITCH_ACTIVE",
                ),
            )
        model = config.model.strip()
        if model.lower() in _PLACEHOLDER_MODELS or not self.approvedModels:
            return (
                None,
                None,
                self._result(
                    mode,
                    SmokePreflightStatus.MODEL_DECISION_REQUIRED,
                    "MODEL_DECISION_REQUIRED",
                ),
            )
        if (
            self.approvedModels != (SMOKE_MODEL,)
            or model != SMOKE_MODEL
            or model not in self.approvedModels
        ):
            return (
                None,
                None,
                self._result(
                    mode,
                    SmokePreflightStatus.BLOCKED,
                    "MODEL_NOT_ALLOWED",
                ),
            )
        if (config.baseUrl or OPENAI_OFFICIAL_ENDPOINT) != OPENAI_OFFICIAL_ENDPOINT:
            return (
                None,
                None,
                self._result(
                    mode,
                    SmokePreflightStatus.BLOCKED,
                    "ENDPOINT_NOT_ALLOWED",
                ),
            )
        if not (
            isinstance(config.liveMaximumOutputTokens, int)
            and not isinstance(config.liveMaximumOutputTokens, bool)
            and config.liveMaximumOutputTokens == SMOKE_OUTPUT_TOKENS
        ):
            return (
                None,
                None,
                self._result(
                    mode,
                    SmokePreflightStatus.BLOCKED,
                    "OUTPUT_TOKEN_BUDGET_INVALID",
                ),
            )
        if not self._credential_probes_ready(config):
            return (
                None,
                None,
                self._result(
                    mode,
                    SmokePreflightStatus.CREDENTIAL_REFERENCE_NOT_READY,
                    "SYSTEMD_CREDENTIAL_UNAVAILABLE",
                ),
            )
        if mode is SmokeTestMode.LIVE_ONE_SHOT and self._liveComposition is not None:
            return self._liveComposition, config, None
        composition = build_ai_advisor_production_composition(
            provider_interaction_policy=ProviderInteractionPolicy.LIVE_TEST,
            config_loader=_LoadedConfig(loaded),
            authentication_credential_loader=self.authenticationCredentialLoader,
            provider_credential_loader=self.providerCredentialLoader,
            allowed_authentication_credential_ids=(
                self.allowedAuthenticationCredentialIds
            ),
            allowed_provider_credential_ids=self.allowedProviderCredentialIds,
            client_factory=self.clientFactory,
            usage_observation_sink=self._usageSink,
            metadata_observation_sink=self._metadataSink,
            failure_observation_sink=self._failureSink,
            clock=self.clock,
        )
        if composition.readiness.status in {
            ProductionReadinessStatus.CREDENTIAL_UNAVAILABLE,
            ProductionReadinessStatus.AUTHENTICATION_UNAVAILABLE,
        }:
            return (
                None,
                None,
                self._result(
                    mode,
                    SmokePreflightStatus.CREDENTIAL_REFERENCE_NOT_READY,
                    "CREDENTIAL_REFERENCE_NOT_READY",
                    composition_built=True,
                ),
            )
        if not composition.succeeded:
            return (
                None,
                None,
                self._result(
                    mode,
                    SmokePreflightStatus.BLOCKED,
                    "COMPOSITION_UNAVAILABLE",
                    composition_built=True,
                ),
            )
        if mode is SmokeTestMode.LIVE_ONE_SHOT:
            self._liveComposition = composition
        return composition, config, None

    def _credential_probes_ready(self, configuration) -> bool:
        pairs = (
            (
                self.authenticationCredentialLoader,
                configuration.authenticationCredentialReference,
            ),
            (
                self.providerCredentialLoader,
                configuration.credentialReference,
            ),
        )
        for loader, reference in pairs:
            probe = getattr(loader, "probe", None)
            if probe is None:
                continue
            if reference is None:
                return False
            try:
                result = probe(
                    CredentialResolutionInput(
                        credentialReference=reference,
                        provider=ProviderName.OPENAI,
                        allowEnvironmentRead=False,
                    )
                )
            except Exception:
                return False
            if result.availability is not SystemdCredentialAvailability.AVAILABLE:
                return False
        return True

    def run(
        self,
        *,
        mode: SmokeTestMode = SmokeTestMode.DRY_RUN,
        generated_at: datetime,
        live_approval: str | None = None,
    ) -> IsolatedSmokeResult:
        if not isinstance(mode, SmokeTestMode):
            return self._result(
                SmokeTestMode.DRY_RUN,
                SmokePreflightStatus.CONFIGURATION_INVALID,
                "MODE_INVALID",
            )
        if mode is SmokeTestMode.LIVE_ONE_SHOT:
            supplied = hashlib.sha256((live_approval or "").encode("utf-8")).hexdigest()
            if not hmac.compare_digest(supplied, _LIVE_APPROVAL_SHA256):
                return self._result(
                    mode,
                    SmokePreflightStatus.BLOCKED,
                    "LIVE_APPROVAL_REQUIRED",
                )
            with self._liveLock:
                return self._run_validated(mode=mode, generated_at=generated_at)
        return self._run_validated(mode=mode, generated_at=generated_at)

    def _run_validated(
        self,
        *,
        mode: SmokeTestMode,
        generated_at: datetime,
    ) -> IsolatedSmokeResult:
        composition, config, failure = self._load_and_validate(mode)
        if failure is not None:
            return failure
        assert isinstance(composition, ProductionCompositionResult)
        if mode is SmokeTestMode.DRY_RUN:
            build_fixed_synthetic_request(generated_at=generated_at)
            return self._result(
                mode,
                SmokePreflightStatus.READY_FOR_CONFIGURATION,
                "DRY_RUN_COMPLETE",
                composition_built=True,
            )
        assert config is not None
        service_input = build_fixed_synthetic_request(
            generated_at=generated_at,
            principal_id=config.principalId,
        )
        succeeded = self._invoke_authenticated_endpoint(
            composition=composition,
            service_input=service_input,
            authentication_reference=config.authenticationCredentialReference,
        )
        observation = self._usageSink.observation
        usage_status = (
            observation.status
            if observation is not None
            else UsageObservationStatus.USAGE_UNAVAILABLE
        )
        usage = observation.usage if observation is not None else None
        failure_observation = self._failureSink.observation
        metadata_observation = self._metadataSink.observation
        return self._result(
            mode,
            (
                SmokePreflightStatus.READY_FOR_CONFIGURATION
                if succeeded
                else SmokePreflightStatus.BLOCKED
            ),
            (
                "LIVE_ONE_SHOT_COMPLETE"
                if succeeded and usage is not None
                else ("USAGE_UNAVAILABLE" if succeeded else "LIVE_ONE_SHOT_FAILED")
            ),
            composition_built=True,
            attempted=True,
            succeeded=succeeded,
            usage_status=usage_status,
            usage=usage,
            request_id=(
                metadata_observation.requestId
                if metadata_observation is not None
                else None
            ),
            model=config.model,
            provider=SafeProviderName.OPENAI,
            endpoint_classification=SafeEndpointClassification.OFFICIAL_OPENAI,
            failure_observation=(failure_observation if not succeeded else None),
        )

    def _invoke_authenticated_endpoint(
        self,
        *,
        composition: ProductionCompositionResult,
        service_input: AdvisorServiceInput,
        authentication_reference,
    ) -> bool:
        if authentication_reference is None:
            return False
        resolution = self.authenticationCredentialLoader.resolve(
            CredentialResolutionInput(
                credentialReference=authentication_reference,
                provider=ProviderName.OPENAI,
                allowEnvironmentRead=(
                    authentication_reference.source.value == "ENVIRONMENT"
                ),
            )
        )
        if (
            resolution.status is not CredentialResolutionStatus.SUCCEEDED
            or resolution.credential is None
        ):
            self._failureSink.observe(
                ProviderFailureObservation(
                    safeReason=(
                        ProviderSafeReason.LIVE_PROVIDER_CREDENTIAL_UNAVAILABLE
                    ),
                    failureStage=ProviderFailureStage.CREDENTIAL_RESOLUTION,
                    liveInvocationAttempted=False,
                )
            )
            return False
        ephemeral_header = "Bearer " + resolution.credential._consume()
        try:
            return asyncio.run(
                self._post_in_process(
                    composition=composition,
                    service_input=service_input,
                    authorization_header=ephemeral_header,
                )
            )
        except Exception:
            return False
        finally:
            ephemeral_header = ""
            resolution = None

    async def _post_in_process(
        self,
        *,
        composition: ProductionCompositionResult,
        service_input: AdvisorServiceInput,
        authorization_header: str,
    ) -> bool:
        app = FastAPI()
        app.include_router(
            create_advice_router(composition.apiComposition),
            prefix="/api/ai-advisor",
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://isolated-asgi",
        ) as client:
            response = await client.post(
                "/api/ai-advisor/advice",
                content=json.dumps(
                    {"serviceInput": service_input.model_dump(mode="json")},
                    separators=(",", ":"),
                ),
                headers={
                    "Authorization": authorization_header,
                    "Content-Type": "application/json",
                },
            )
        if response.status_code == 502 and self._failureSink.observation is None:
            self._failureSink.observe(
                ProviderFailureObservation(
                    safeReason=(
                        ProviderSafeReason.LIVE_PROVIDER_RESPONSE_CONTRACT_FAILED
                    ),
                    failureStage=ProviderFailureStage.RESPONSE_VALIDATION,
                    httpStatus=502,
                    liveInvocationAttempted=True,
                )
            )
        elif response.status_code == 503 and self._failureSink.observation is None:
            self._failureSink.observe(
                ProviderFailureObservation(
                    safeReason=ProviderSafeReason.LIVE_PROVIDER_UNKNOWN_FAILURE,
                    failureStage=ProviderFailureStage.PROVIDER_INVOCATION,
                    httpStatus=503,
                    liveInvocationAttempted=True,
                )
            )
        return response.status_code == 200


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--mode",
        choices=tuple(mode.value for mode in SmokeTestMode),
        default=SmokeTestMode.DRY_RUN.value,
    )
    parser.add_argument(
        "--live-one-shot-approval",
        action="append",
        default=[],
        help=argparse.SUPPRESS,
    )
    arguments = parser.parse_args(argv)
    mode = SmokeTestMode(arguments.mode)
    approval_values = tuple(arguments.live_one_shot_approval)
    if mode is not SmokeTestMode.LIVE_ONE_SHOT and approval_values:
        result = _cli_approval_failure(mode, "LIVE_APPROVAL_NOT_ALLOWED")
        sys.stdout.write(result.model_dump_json() + "\n")
        return smoke_result_exit_code(result)
    if mode is SmokeTestMode.LIVE_ONE_SHOT:
        if len(approval_values) != 1:
            result = _cli_approval_failure(mode, "LIVE_APPROVAL_REQUIRED")
            sys.stdout.write(result.model_dump_json() + "\n")
            return smoke_result_exit_code(result)
        approval = approval_values[0]
        supplied = hashlib.sha256(approval.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(supplied, _LIVE_APPROVAL_SHA256):
            result = _cli_approval_failure(mode, "LIVE_APPROVAL_REQUIRED")
            sys.stdout.write(result.model_dump_json() + "\n")
            return smoke_result_exit_code(result)
    else:
        approval = None
    try:
        process_configuration = isolated_non_secret_environment()
        runner = IsolatedSmokeTestRunner(
            configLoader=EnvironmentProductionConfigLoader(
                environmentReader=process_configuration.get
            ),
            authenticationCredentialLoader=SystemdCredentialLoader(
                ("AI_ADVISOR_AUTH_TOKEN",)
            ),
            providerCredentialLoader=SystemdCredentialLoader(("OPENAI_API_KEY",)),
            allowedAuthenticationCredentialIds=("AI_ADVISOR_AUTH_TOKEN",),
            allowedProviderCredentialIds=("OPENAI_API_KEY",),
            approvedModels=(SMOKE_MODEL,),
        )
        result = runner.run(
            mode=mode,
            generated_at=datetime.now(timezone.utc),
            live_approval=approval,
        )
    except Exception:
        result = _unexpected_cli_failure(mode)
    sys.stdout.write(result.model_dump_json() + "\n")
    return smoke_result_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
