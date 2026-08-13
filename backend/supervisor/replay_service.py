from .history_contracts import SupervisorReplay
class SupervisorReplayService:
    def __init__(self,store): self.store=store
    def replay(self,event_id):
        event=self.store.get(event_id)
        return SupervisorReplay(sourceEventId=event.eventId,eventType=event.eventType,agentId=event.agentId,occurredAt=event.occurredAt,status=event.status,summary=event.summary,humanAttention=event.humanAttention,failureCode=event.failureCode,snapshotCapturedAt=event.snapshotCapturedAt,freshness=event.freshness,decisionIdentity=event.decisionDigest,assessmentIdentity=event.assessmentDigest)
