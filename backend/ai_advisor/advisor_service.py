"""Pure application-layer orchestration for the AI Advisor pipeline."""

from dataclasses import dataclass

from backend.ai_advisor.context_builder import build_advisor_context
from backend.ai_advisor.conversation_models import AdvisorRequest
from backend.ai_advisor.conversation_validation import (
    validate_request_time,
    validate_trusted_request,
)
from backend.ai_advisor.prompt_builder import build_advisor_prompt
from backend.ai_advisor.prompt_models import AdvisorPromptPolicy
from backend.ai_advisor.no_source_response_normalizer import (
    normalize_no_source_response,
)
from backend.ai_advisor.provider_adapter import (
    AdvisorProvider,
    build_provider_request,
    invoke_provider_once,
)
from backend.ai_advisor.provider_models import (
    AdvisorModelPolicy,
    AdvisorProviderCapabilities,
    AdvisorProviderConfig,
    AdvisorProviderFailure,
    AdvisorProviderReceivedAt,
)
from backend.ai_advisor.provider_failure_observation import (
    NoOpProviderFailureObservationSink,
    ProviderFailureObservation,
    ProviderFailureCategory,
    ProviderFailureObservationSink,
    ProviderFailureStage,
    ProviderSafeReason,
    ResponseContractDiagnostic,
    ResponseTopLevelType,
    ResponseValidationCode,
)
from backend.ai_advisor.provider_validation import validate_provider_response
from backend.ai_advisor.response_models import AdvisorRawResponse
from backend.ai_advisor.response_parser import (
    AdvisorResponseParsingError,
    parse_advisor_response,
)
from backend.ai_advisor.response_validation import (
    validate_advisor_response_with_diagnostic,
)
from backend.ai_advisor.response_models import AdvisorResponseStatus
from backend.ai_advisor.response_safety_observation import (
    NoOpResponseSafetyRejectionObservationSink,
    ResponseSafetyRejectionObservationSink,
    project_response_safety_rejection,
)
from backend.ai_advisor.service_models import (
    AdvisorServiceContextInput,
    AdvisorServiceFailure,
    AdvisorServiceFailureCode,
    AdvisorServiceInput,
    AdvisorServiceResult,
    AdvisorServiceStatus,
    service_failure_message,
)


def _failure(code: AdvisorServiceFailureCode) -> AdvisorServiceResult:
    return AdvisorServiceResult(
        status=AdvisorServiceStatus.FAILED,
        response=None,
        failure=AdvisorServiceFailure(
            code=code,
            safeMessage=service_failure_message(code),
            retryAllowed=False,
        ),
    )


@dataclass(frozen=True)
class AdvisorService:
    provider: AdvisorProvider
    providerConfig: AdvisorProviderConfig
    modelPolicy: AdvisorModelPolicy
    capabilities: AdvisorProviderCapabilities
    failureObservationSink: ProviderFailureObservationSink = (
        NoOpProviderFailureObservationSink()
    )
    responseSafetyObservationSink: ResponseSafetyRejectionObservationSink = (
        NoOpResponseSafetyRejectionObservationSink()
    )

    def _observe_parse_failure(
        self,
        diagnostic: ResponseContractDiagnostic,
        *,
        request_id: str,
        provider_request_id: str,
    ) -> None:
        try:
            self.failureObservationSink.observe(
                ProviderFailureObservation(
                    model=self.providerConfig.modelId,
                    requestId=request_id,
                    providerRequestId=provider_request_id,
                    category=ProviderFailureCategory.RESPONSE_VALIDATION,
                    safeReason=(
                        ProviderSafeReason.LIVE_PROVIDER_RESPONSE_CONTRACT_FAILED
                    ),
                    failureStage=ProviderFailureStage.RESPONSE_VALIDATION,
                    httpStatus=502,
                    liveInvocationAttempted=True,
                    parseSucceeded=diagnostic.parseSucceeded,
                    validationCode=diagnostic.validationCode,
                    topLevelType=diagnostic.topLevelType,
                    invalidField=diagnostic.invalidField,
                    missingFields=diagnostic.missingFields,
                )
            )
        except Exception:
            return None

    def generate_response(
        self,
        service_input: AdvisorServiceInput,
    ) -> AdvisorServiceResult:
        """Execute every validated layer in fixed order without side effects."""

        try:
            if not isinstance(service_input, AdvisorServiceInput):
                raise TypeError
            request = AdvisorRequest.model_validate(
                service_input.request.model_dump(warnings=False)
            )
            received_at = AdvisorProviderReceivedAt(value=service_input.receivedAt)
            validate_trusted_request(request)
            validate_request_time(request, now=received_at.value)
        except Exception:
            return _failure(AdvisorServiceFailureCode.ADVISOR_INVALID_CONVERSATION)

        try:
            context_input = AdvisorServiceContextInput.model_validate(
                service_input.contextInput.model_dump(warnings=False)
            )
            context = build_advisor_context(
                generated_at=context_input.generatedAt,
                permission_context=request.permissionContext,
                runtime=context_input.runtime,
                runtime_source_id=context_input.runtimeSourceId,
                specifications=context_input.specifications,
                market_intelligence_sources=(context_input.marketIntelligenceSources),
                money_management_sources=context_input.moneyManagementSources,
                conversation_history=context_input.conversationHistory,
                current_message=context_input.currentMessage,
                trace_evidence=context_input.traceEvidence,
                knowledge_context=context_input.knowledgeContext,
            )
            if context != request.contextEnvelope:
                raise ValueError
        except Exception:
            return _failure(AdvisorServiceFailureCode.ADVISOR_CONTEXT_INVALID)

        try:
            prompt = build_advisor_prompt(
                request=request,
                context=context,
                policy=AdvisorPromptPolicy(),
            )
        except Exception:
            return _failure(AdvisorServiceFailureCode.ADVISOR_PROMPT_INVALID)

        try:
            provider_request = build_provider_request(
                request=request,
                prompt_envelope=prompt,
                config=self.providerConfig,
                model_policy=self.modelPolicy,
                capabilities=self.capabilities,
                provider_request_id=service_input.providerRequestId,
            )
        except Exception:
            return _failure(AdvisorServiceFailureCode.ADVISOR_PROVIDER_REQUEST_INVALID)

        try:
            provider_response = invoke_provider_once(
                provider=self.provider,
                request=provider_request,
            )
        except Exception:
            return _failure(AdvisorServiceFailureCode.ADVISOR_PROVIDER_FAILURE)

        try:
            raw_response = validate_provider_response(
                request=provider_request,
                response=provider_response,
                capabilities=self.capabilities,
                received_at=received_at,
            )
        except Exception:
            return _failure(AdvisorServiceFailureCode.ADVISOR_PROVIDER_RESPONSE_INVALID)
        if isinstance(raw_response, AdvisorProviderFailure):
            return _failure(AdvisorServiceFailureCode.ADVISOR_PROVIDER_FAILURE)
        if not isinstance(raw_response, AdvisorRawResponse):
            return _failure(AdvisorServiceFailureCode.ADVISOR_PROVIDER_RESPONSE_INVALID)

        if not context.sources:
            raw_response = normalize_no_source_response(raw_response)

        try:
            parse_advisor_response(raw_response)
        except AdvisorResponseParsingError as exception:
            self._observe_parse_failure(
                exception.diagnostic,
                request_id=request.requestId,
                provider_request_id=service_input.providerRequestId,
            )
            return _failure(AdvisorServiceFailureCode.ADVISOR_PARSE_FAILURE)
        except Exception:
            self._observe_parse_failure(
                ResponseContractDiagnostic(
                    validationCode=(
                        ResponseValidationCode.UNKNOWN_RESPONSE_CONTRACT_FAILURE
                    ),
                    topLevelType=ResponseTopLevelType.UNKNOWN,
                ),
                request_id=request.requestId,
                provider_request_id=service_input.providerRequestId,
            )
            return _failure(AdvisorServiceFailureCode.ADVISOR_PARSE_FAILURE)

        try:
            validation_outcome = validate_advisor_response_with_diagnostic(
                raw_response=raw_response,
                request=request,
                context=context,
                prompt_envelope=prompt,
            )
            response = validation_outcome.response
        except Exception:
            return _failure(AdvisorServiceFailureCode.ADVISOR_RESPONSE_INVALID)
        if response.status is AdvisorResponseStatus.REJECTED:
            try:
                self.responseSafetyObservationSink.observe(
                    project_response_safety_rejection(
                        response,
                        provider_request_id=service_input.providerRequestId,
                        integrity_diagnostic=(
                            validation_outcome.integrityDiagnostic
                        ),
                    )
                )
            except Exception:
                pass
        return AdvisorServiceResult(
            status=AdvisorServiceStatus.SUCCEEDED,
            response=response,
            failure=None,
        )
