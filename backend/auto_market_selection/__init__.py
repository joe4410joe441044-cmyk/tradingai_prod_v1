"""Deterministic AUTO MARKET SELECTION contracts."""

from .market_scanner import (
    MarketScanner,
    ScannerCandidate,
    ScannerCycleResult,
    ScannerInput,
    ScannerRejectionReason,
    ScannerStatus,
    TickerSnapshot,
)
from .candidate_ranking import (
    CandidateRankingEngine, MarketScoreComparison, RANKING_CONTRACT_VERSION,
    EffectiveWeights,
    RankingCandidate,
    RankingCycleResult,
    RankingFeatures,
    RankingReason,
    RankingStatus,
)
from .selection_audit import (
    SELECTION_AUDIT_EVENT_TYPE, CandidateAuditEntry,
    RejectedCandidateAuditEntry, SelectionAuditEvent,
    build_selection_audit_event,
)
from .selection_proposal import (
    PendingOrderState, PositionState, ProposalStatus, SelectionMode,
    SelectionProposal, SelectionProposalReason, build_selection_proposal,
    snapshot_active_symbol_authority,
)
from .safe_switch import SafeSymbolSwitch, SwitchReason, SwitchResult, SwitchState
from .bot_manager_switch_runtime import BotManagerSwitchRuntime, PreparedFeed
from .dashboard_status import build_auto_market_selection_status
from .recorder_integration import (
    AMS_RANKING, AMS_RECORDER_PAYLOAD_VERSION, AMS_SCAN, AMS_SELECTION_AUDIT,
    AMS_SELECTION_PROPOSAL, AMS_SYMBOL_SWITCH, AMSRecorderIntegration,
    RecorderWriteResult, ranking_event, scanner_event, selection_audit_event,
    selection_proposal_event, symbol_switch_event,
)
from .auto_selection_runtime import (
    AutoMarketSelectionRuntime, AutoSelectionCycleResult,
    AutoSelectionCycleStatus, AutoSelectionRuntimeMode,
)
from .paper_e2e import (
    PaperAutoSelectionE2E, PaperAutoSelectionE2EResult,
    PaperAutoSelectionE2EStatus,
)
from .lifecycle import AutoSelectionLifecycleState, PaperAutoSelectionLifecycle
from .long_run_validation import (
    LongRunCycleRecord, LongRunPaperValidationHarness, LongRunValidationResult,
)
from .live_read_only import LiveReadOnlyObservation, LiveReadOnlyValidation
from .live_calibration import (
    CalibrationObservation, LiveCalibrationCampaign, analyze_calibration,
    distribution, simulate_hypothetical_switches, simulate_anti_flapping,
    simulate_anti_flapping_grid,
)
from .live_account_authority import (
    ExistingKucoinLiveAccountAuthority, LiveAccountAuthoritySnapshot,
)
from .live_auto_calibration import (
    LiveAutoActivationApproval, LiveAutoSelectionCalibration,
    LiveSwitchEligibility, LiveSwitchEligibilityTracker, LiveSwitchObservation,
)
from .live_auto_runtime import (
    LiveActivationBoundaryResult,
    LiveActivationProposal,
    LiveAutoRuntimeObservation,
    LiveAutoRuntimeState,
    LiveAutoSelectionRuntime,
    ValidationOnlySafeSwitchAdapter,
)
from .live_safe_switch import (
    LimitedLiveSafeSwitchAdapter, LiveSymbolSwitchPermission,
)
from .micro_edge_suitability import (
    MicroEdgeSuitabilityContract,
    MicroEdgeSuitabilityEvidence,
    MicroEdgeSuitabilityReason,
    MicroEdgeSuitabilityStatus,
    evaluate_micro_edge_suitability,
    revalidate_micro_edge_suitability,
)

__all__ = [
    "MarketScanner",
    "ScannerCandidate",
    "ScannerCycleResult",
    "ScannerInput",
    "ScannerRejectionReason",
    "ScannerStatus",
    "TickerSnapshot",
    "CandidateRankingEngine",
    "MarketScoreComparison",
    "RANKING_CONTRACT_VERSION",
    "EffectiveWeights",
    "RankingCandidate",
    "RankingCycleResult",
    "RankingFeatures",
    "RankingReason",
    "RankingStatus",
    "SELECTION_AUDIT_EVENT_TYPE",
    "CandidateAuditEntry",
    "RejectedCandidateAuditEntry",
    "SelectionAuditEvent",
    "build_selection_audit_event",
    "PendingOrderState",
    "PositionState",
    "ProposalStatus",
    "SelectionMode",
    "SelectionProposal",
    "SelectionProposalReason",
    "build_selection_proposal",
    "snapshot_active_symbol_authority",
    "SafeSymbolSwitch",
    "SwitchReason",
    "SwitchResult",
    "SwitchState",
    "BotManagerSwitchRuntime",
    "PreparedFeed",
    "build_auto_market_selection_status",
    "AMS_SCAN", "AMS_RANKING", "AMS_SELECTION_AUDIT",
    "AMS_SELECTION_PROPOSAL", "AMS_SYMBOL_SWITCH",
    "AMS_RECORDER_PAYLOAD_VERSION", "AMSRecorderIntegration",
    "RecorderWriteResult", "scanner_event", "ranking_event",
    "selection_audit_event", "selection_proposal_event", "symbol_switch_event",
    "AutoMarketSelectionRuntime", "AutoSelectionCycleResult",
    "AutoSelectionCycleStatus", "AutoSelectionRuntimeMode",
    "PaperAutoSelectionE2E", "PaperAutoSelectionE2EResult",
    "PaperAutoSelectionE2EStatus",
    "AutoSelectionLifecycleState", "PaperAutoSelectionLifecycle",
    "LongRunCycleRecord", "LongRunPaperValidationHarness",
    "LongRunValidationResult",
    "LiveReadOnlyObservation", "LiveReadOnlyValidation",
    "CalibrationObservation", "LiveCalibrationCampaign",
    "analyze_calibration", "distribution", "simulate_hypothetical_switches",
    "simulate_anti_flapping", "simulate_anti_flapping_grid",
    "ExistingKucoinLiveAccountAuthority", "LiveAccountAuthoritySnapshot",
    "LiveAutoActivationApproval", "LiveAutoSelectionCalibration",
    "LiveSwitchEligibility", "LiveSwitchEligibilityTracker",
    "LiveAutoRuntimeObservation", "LiveAutoRuntimeState",
    "LiveAutoSelectionRuntime", "LiveActivationProposal",
    "LiveActivationBoundaryResult", "ValidationOnlySafeSwitchAdapter",
    "LiveSwitchObservation",
    "LimitedLiveSafeSwitchAdapter", "LiveSymbolSwitchPermission",
    "MicroEdgeSuitabilityContract", "MicroEdgeSuitabilityEvidence",
    "MicroEdgeSuitabilityReason", "MicroEdgeSuitabilityStatus",
    "evaluate_micro_edge_suitability",
    "revalidate_micro_edge_suitability",
]
