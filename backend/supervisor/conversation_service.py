"""Provider-neutral, fail-closed conversation orchestration for SHADOW agents."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Callable, Mapping

from pydantic import BaseModel, ValidationError

from .agent_registry import Capability
from .contracts import HumanAttention, SupervisorAgentId, SupervisorMode
from .conversation_contracts import (
    ConversationStatus,
    SupervisorConversationProviderOutput,
    SupervisorConversationRequest,
    SupervisorConversationResponse,
)
from .failure_codes import SupervisorFailureCode
from .master_shadow_runtime import evaluate_master_shadow
from .mm_shadow_runtime import evaluate_mm_shadow
from .operator_constitution import TRADINGAI_OPERATOR_CONSTITUTION
from .provider import ProviderAvailability, ProviderResult, StructuredOutputProvider
from .runtime_snapshot_adapter import RuntimeSnapshotAdapter
from .security_boundary import validate_agent_capability
from .audit_store import SupervisorAuditStore
from .history_contracts import SupervisorEventType, SupervisorHistoryEvent


CONVERSATION_TIMEOUT_SECONDS = 8.0
_UNAVAILABLE_ANSWER = "Supervisor AI provider is not connected."
_FAILED_ANSWER = "Supervisor response is unavailable. No operational change was made."
_FORBIDDEN_CLAIMS = (
    "RISKを変更しました", "RISK CHANGED", "LOTを変更しました", "QUANTITY CHANGED",
    "BOTを停止しました", "BOT STOPPED", "注文しました", "ORDER SUBMITTED",
    "GOVERNANCEを解除しました", "GOVERNANCE CHANGED", "ACTIVEへ移行しました",
    "PROMOTED TO ACTIVE", "人間承認を得ました", "HUMAN APPROVAL OBTAINED",
    "AMS THRESHOLDを変更しました", "AMS THRESHOLD CHANGED",
)
_SECRET_MARKERS = ("API_KEY", "APIKEY", "SECRET", "TOKEN", "PASSWORD", "PRIVATE_KEY")


class SupervisorConversationService:
    def __init__(
        self,
        *,
        snapshot_adapter: RuntimeSnapshotAdapter | None = None,
        provider: StructuredOutputProvider | None = None,
        clock: Callable[[], datetime] | None = None,
        audit_store: SupervisorAuditStore | None = None,
    ) -> None:
        self._snapshot_adapter = snapshot_adapter or RuntimeSnapshotAdapter()
        self._provider = provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._audit_store = audit_store

    def _record(self, event):
        if self._audit_store is None: return None
        try: self._audit_store.append(event); return None
        except Exception: return "Supervisor audit record could not be stored."

    def _audit_events(self, request, snapshot, now, response, mm_result, master_result):
        warnings=[]
        common=dict(occurredAt=now,conversationId=request.conversationId,snapshotCapturedAt=snapshot.capturedAt,freshness=snapshot.overallFreshness.value,operationalEffect="NONE")
        mm=SupervisorHistoryEvent(eventId=mm_result.auditEvent.eventId,eventType=SupervisorEventType.MM_SHADOW_ASSESSMENT,agentId=SupervisorAgentId.MM_SUPERVISOR,sourceEvaluatedAt=mm_result.auditEvent.sourceEvaluatedAt,status=mm_result.status.value,failureCode=mm_result.failureCode,summary="MM SHADOW assessment completed." if mm_result.failureCode is None else "MM SHADOW assessment failed closed.",assessmentDigest=mm_result.auditEvent.assessmentDigest,providerIdentity=mm_result.providerIdentity,providerVersion=mm_result.providerVersion,**common)
        warning=self._record(mm)
        if warning: warnings.append(warning)
        if master_result is not None:
            master=SupervisorHistoryEvent(eventId=master_result.auditEvent.eventId,eventType=SupervisorEventType.MASTER_SHADOW_DECISION,agentId=SupervisorAgentId.MASTER_SUPERVISOR,status=master_result.status.value,failureCode=master_result.failureCode,humanAttention=getattr(master_result.decision,"humanAttention",None),summary="Master SHADOW decision completed." if master_result.failureCode is None else "Master SHADOW decision failed closed.",decisionDigest=master_result.auditEvent.decisionDigest,assessmentDigest=master_result.auditEvent.mmAssessmentDigest,providerIdentity=master_result.providerIdentity,providerVersion=master_result.providerVersion,**common)
            warning=self._record(master)
            if warning: warnings.append(warning)
        success=response.status is ConversationStatus.COMPLETED
        event_type={
            (SupervisorAgentId.MASTER_SUPERVISOR,True):SupervisorEventType.MASTER_CONVERSATION_SUCCESS,
            (SupervisorAgentId.MASTER_SUPERVISOR,False):SupervisorEventType.MASTER_CONVERSATION_FAILURE,
            (SupervisorAgentId.MM_SUPERVISOR,True):SupervisorEventType.MM_CONVERSATION_SUCCESS,
            (SupervisorAgentId.MM_SUPERVISOR,False):SupervisorEventType.MM_CONVERSATION_FAILURE,
        }[(request.agentId,success)]
        convo=SupervisorHistoryEvent(eventId=response.messageId,eventType=event_type,agentId=request.agentId,status=response.status.value,failureCode=response.failureCode,humanAttention=response.humanAttention,summary=response.answer[:300],decisionDigest=getattr(getattr(master_result,"auditEvent",None),"decisionDigest",None),assessmentDigest=mm_result.auditEvent.assessmentDigest,providerIdentity=(master_result or mm_result).providerIdentity,providerVersion=(master_result or mm_result).providerVersion,**common)
        warning=self._record(convo)
        if warning: warnings.append(warning)
        return response.model_copy(update={"warnings":tuple((*response.warnings,*warnings))}) if warnings else response

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("conversation clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _message_id(agent_id: SupervisorAgentId, conversation_id: str, now: datetime) -> str:
        return f"{agent_id.value.lower()}-{conversation_id[:24]}-{int(now.timestamp() * 1000)}"

    def _failure(self, request, snapshot, now, code, *, assessment=None, decision=None):
        unavailable = code is SupervisorFailureCode.PROVIDER_UNAVAILABLE
        return SupervisorConversationResponse(
            agentId=request.agentId,
            conversationId=request.conversationId,
            messageId=self._message_id(request.agentId, request.conversationId, now),
            status=ConversationStatus.UNAVAILABLE if unavailable else ConversationStatus.FAILED_CLOSED,
            answer=_UNAVAILABLE_ANSWER if unavailable else _FAILED_ANSWER,
            humanAttention=HumanAttention.REVIEW,
            snapshotCapturedAt=snapshot.capturedAt,
            decisionIdentity=getattr(getattr(decision, "auditEvent", None), "eventId", None),
            assessmentIdentity=getattr(getattr(assessment, "auditEvent", None), "eventId", None),
            warnings=(),
            failureCode=code,
            respondedAt=now,
        )

    @staticmethod
    def _safe_output(output: SupervisorConversationProviderOutput) -> None:
        text = " ".join((output.answer, *output.warnings)).upper().replace("_", " ")
        if any(claim.upper() in text for claim in _FORBIDDEN_CLAIMS):
            raise ValueError("prohibited operational claim")
        if any(marker in text for marker in _SECRET_MARKERS):
            raise ValueError("secret-like output")

    def respond(self, app: object, request: SupervisorConversationRequest) -> SupervisorConversationResponse:
        now = self._now()
        validate_agent_capability(request.agentId, Capability.ANSWER_CONVERSATION, SupervisorMode.SHADOW)
        snapshot = self._snapshot_adapter.build(app)
        mm_result = evaluate_mm_shadow(snapshot, self._provider, now)
        master_result = None
        if request.agentId is SupervisorAgentId.MASTER_SUPERVISOR:
            master_result = evaluate_master_shadow(
                snapshot, mm_result, self._provider, now, TRADINGAI_OPERATOR_CONSTITUTION
            )
            runtime_result = master_result
            identity = master_result.auditEvent.eventId
        else:
            runtime_result = mm_result
            identity = mm_result.auditEvent.eventId

        if runtime_result.failureCode is not None:
            failure_code = runtime_result.failureCode
            if (
                request.agentId is SupervisorAgentId.MASTER_SUPERVISOR
                and mm_result.failureCode is SupervisorFailureCode.PROVIDER_UNAVAILABLE
            ):
                failure_code = SupervisorFailureCode.PROVIDER_UNAVAILABLE
            response = self._failure(
                request, snapshot, now, failure_code,
                assessment=mm_result, decision=master_result,
            )
            return self._audit_events(request,snapshot,now,response,mm_result,master_result)
        if self._provider is None or self._provider.availability is not ProviderAvailability.AVAILABLE:
            response = self._failure(
                request, snapshot, now, SupervisorFailureCode.PROVIDER_UNAVAILABLE,
                assessment=mm_result, decision=master_result,
            )
            return self._audit_events(request,snapshot,now,response,mm_result,master_result)
        context: Mapping[str, object] = {
            "schemaVersion": 1,
            "agentId": request.agentId.value,
            "mode": "SHADOW",
            "message": request.message,
            "snapshotCapturedAt": snapshot.capturedAt.isoformat(),
            "runtimeIdentity": identity,
            "operationalEffect": "NONE",
            "prohibitedClaims": list(_FORBIDDEN_CLAIMS),
        }
        try:
            envelope = self._provider.generate_structured_output(
                context, SupervisorConversationProviderOutput, CONVERSATION_TIMEOUT_SECONDS
            )
            if not isinstance(envelope, ProviderResult):
                raise ValueError("invalid provider envelope")
            if envelope.failureCode is not None:
                code = (
                    envelope.failureCode
                    if envelope.failureCode in {
                        SupervisorFailureCode.PROVIDER_TIMEOUT,
                        SupervisorFailureCode.PROVIDER_UNAVAILABLE,
                    }
                    else SupervisorFailureCode.OUTPUT_INVALID
                )
                response=self._failure(request, snapshot, now, code, assessment=mm_result, decision=master_result)
                return self._audit_events(request,snapshot,now,response,mm_result,master_result)
            raw = envelope.output.model_dump(mode="python") if isinstance(envelope.output, BaseModel) else envelope.output
            if not isinstance(raw, Mapping):
                raise ValueError("invalid provider output")
            output = SupervisorConversationProviderOutput.model_validate(dict(raw))
            self._safe_output(output)
        except TimeoutError:
            response=self._failure(request, snapshot, now, SupervisorFailureCode.PROVIDER_TIMEOUT, assessment=mm_result, decision=master_result); return self._audit_events(request,snapshot,now,response,mm_result,master_result)
        except (ValidationError, ValueError, TypeError):
            response=self._failure(request, snapshot, now, SupervisorFailureCode.OUTPUT_INVALID, assessment=mm_result, decision=master_result); return self._audit_events(request,snapshot,now,response,mm_result,master_result)
        except Exception:
            response=self._failure(request, snapshot, now, SupervisorFailureCode.FAIL_CLOSED, assessment=mm_result, decision=master_result); return self._audit_events(request,snapshot,now,response,mm_result,master_result)

        attention = (
            master_result.decision.humanAttention
            if master_result is not None and master_result.decision is not None
            else HumanAttention.REVIEW
        )
        response = SupervisorConversationResponse(
            agentId=request.agentId,
            conversationId=request.conversationId,
            messageId=self._message_id(request.agentId, request.conversationId, now),
            status=ConversationStatus.COMPLETED,
            answer=output.answer,
            humanAttention=attention,
            snapshotCapturedAt=snapshot.capturedAt,
            decisionIdentity=master_result.auditEvent.eventId if master_result else None,
            assessmentIdentity=mm_result.auditEvent.eventId,
            warnings=output.warnings,
            respondedAt=now,
        )
        return self._audit_events(request,snapshot,now,response,mm_result,master_result)
