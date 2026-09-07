import { useState } from "react";

import {
    OPERATION_PREPARATION_OPTIONS,
    createOperationPreparationSettings,
    deriveOperationReadiness,
    operationPreparationSummary,
} from "./operationPreparationModel";
import { deriveOperationBlockGuidance } from "./operationPreparationGuidance";


const percentage = (value) => `${Number(value).toFixed(2)}%`;
const wholePercentage = (value) => `${value}%`;
const leverage = (value) => `${value}x`;
const authoritativeLeverage = (value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? `${parsed}x` : "UNAVAILABLE";
};
const displayPercent = (value) => (
    Number.isFinite(Number(value)) ? `${Number(value)}%` : "UNAVAILABLE"
);

const sourceLabel = (source) => ({
    "UI PREVIEW": "PREVIEW",
    "UI FALLBACK": "PREVIEW",
    "UI REVIEW": "UI",
    OPERATOR: "UI",
    DERIVED: "UI",
}[source] || source);

const sourceBadge = (source) => (
    <span className={`operation-prep-source operation-prep-source--${source.toLowerCase().replace(/\s/g, "-")}`}>
        {sourceLabel(source)}
    </span>
);

function SegmentedControl({ disabled, label, onChange, options, value }) {
    return (
        <div aria-label={label} className="operation-prep-segmented" role="group">
            {options.map((option) => (
                <button
                    aria-pressed={value === option}
                    className={value === option ? "is-selected" : ""}
                    disabled={disabled}
                    key={option}
                    onClick={() => onChange(option)}
                    type="button"
                >
                    {option}
                </button>
            ))}
        </div>
    );
}

function ToggleControl({ disabled, label, onChange, value }) {
    return (
        <SegmentedControl
            disabled={disabled}
            label={label}
            onChange={(next) => onChange(next === "ON")}
            options={["OFF", "ON"]}
            value={value ? "ON" : "OFF"}
        />
    );
}

function SelectField({ disabled, id, label, onChange, options, value, format = String }) {
    return (
        <label className="operation-prep-field" htmlFor={id}>
            <span>{label}</span>
            <select
                disabled={disabled}
                id={id}
                onChange={(event) => onChange(event.target.value)}
                value={value}
            >
                {options.map((option) => (
                    <option key={option} value={option}>{format(option)}</option>
                ))}
            </select>
        </label>
    );
}

const provenanceBadge = (provenance) => {
    if (!provenance) return null;
    return (
        <span className={`operation-prep-provenance operation-prep-provenance--${provenance.toLowerCase()}`}>
            {provenance === "REQ" ? "REQUEST" : "CURRENT"}
        </span>
    );
};

function DerivedRow({ label, source = "AUTO", status = false, value, valueClass = "", provenance }) {
    const tone = String(value || "unknown").toLowerCase().replace(/[^a-z]+/g, "-");
    return (
        <div className="operation-prep-derived-row">
            <span>{label}</span>
            <strong className={status ? `operation-prep-status operation-prep-status--${tone}` : valueClass}>
                {status && <i aria-hidden="true" />}
                {value}
            </strong>
            {provenanceBadge(provenance)}
            {sourceBadge(source)}
        </div>
    );
}

const Section = ({ bodyClassName = "", children, number, title, testId }) => (
    <section className="operation-prep-section" data-testid={testId}>
        <header><span>{number}</span><h3>{title}</h3></header>
        <div className={`operation-prep-section__body ${bodyClassName}`.trim()}>{children}</div>
    </section>
);

// WF-1: block-reason + corrective guidance mapped externally in
// ./operationPreparationGuidance (presentation-only). The authoritative
// readiness values come from deriveOperationReadiness (the model).

export default function OperationPreparation({
    botRunning = false,
    children,
    config = {},
    emergencyState = "UNKNOWN",
    executionEnabled = false,
    governanceStatus = "UNKNOWN",
    onLegacyConfigChange = () => {},
    pendingOrder,
    position,
    realOrderAllowed = false,
    loopChecked,
    loopState,
    loopDisabled,
    handleLoopChange,
    autoTradeChecked,
    autoTradeStateText,
    autoTradeDisabled,
    handleAutoTradeChange,
    mmRuntime = "UNKNOWN",
    lifecycleState,
    capitalAuthorityStatus = "NOT CONNECTED",
    availableCapital = undefined,
    capitalBasis = undefined,
    riskBudget = undefined,
    executionEntryAllowed,
    recommendedAction,
    riskState,
    mmBlockReasons = [],
    mmRecoveryRequired = false,
    mmDraft = null,
    mmConfiguration = null,
    mmDraftInvalid = false,
    leverageAuthority = null,
    mmUpdating = false,
    mmLoading = false,
    mmConfigurationError = null,
    mmUpdateError = null,
    mmConflict = null,
    onMmDraftChange = () => {},
    onMmSave = () => {},
    onMmReset = () => {},
    lockedFacts = [],
    actionWarnings = [],
    emergencyPath = "",
    emergencyError,
    unlockError,
    lastResultMessage,
    emergencyLocked,
    emergencyConfirmOpen = false,
    emergencyPending = false,
    unlockPending = false,
    unlockAllowed,
    emergencyButtonDisabled,
    emergencyLockValue,
    emergencyLockClass,
    openEmergencyConfirm,
    cancelEmergencyConfirm,
    confirmEmergency,
    handleReturnToNormal,
}) {
    const settings = createOperationPreparationSettings(config);
    const [tradeSettingsOpen, setTradeSettingsOpen] = useState(false);
    const [safetyDetailsOpen, setSafetyDetailsOpen] = useState(false);
     const changeSetting = (key, value) => {
        if (key === "tradingMode") onLegacyConfigChange({ mode: value });
        if (key === "selectionMode") onLegacyConfigChange({ selectionMode: value });
        if (key === "manualSymbol") onLegacyConfigChange({ symbol: value });
        if (key === "loopOnStart") onLegacyConfigChange({ loopOnStart: value });
        if (key === "autoTradeOnStart") onLegacyConfigChange({ autoTradeOnStart: value });
        if (key === "requestedLeverage") onLegacyConfigChange({ leverage: value });
        if (key === "positionSize") onLegacyConfigChange({ positionSize: value });
        if (key === "stopLossPercent") onLegacyConfigChange({ sl: value });
        if (key === "takeProfitPercent") onLegacyConfigChange({ tp: value });
        if (key === "trailingStop") onLegacyConfigChange({ trailing: value });
        if (key === "timeframe") onLegacyConfigChange({ timeframe: value });
    };

    const emergencyStateCode = String(emergencyState ?? "UNKNOWN").trim().toUpperCase();

    const emergencyStateCopy = {
        READY: {
            label: "READY",
            text: "緊急停止は作動していません",
            tone: "ready",
        },
        PROCESSING: {
            label: "PROCESSING",
            text: "緊急停止処理を実行中です",
            tone: "processing",
        },
        LOCKED: {
            label: "STOPPED SAFELY",
            text: "緊急停止が正常に完了しました",
            tone: "locked",
        },
        ACTION_REQUIRED: {
            label: "ACTION REQUIRED",
            text: "緊急停止は一部完了、失敗、または確認不能です",
            tone: "action",
        },
        FAILED: {
            label: "FAILED",
            text: "緊急停止処理に失敗しました",
            tone: "action",
        },
        PARTIAL: {
            label: "PARTIAL",
            text: "緊急停止処理は一部完了しました",
            tone: "action",
        },
        STATE_UNKNOWN: {
            label: "STATE UNKNOWN",
            text: "緊急停止後の状態を確認できません",
            tone: "action",
        },
    };
    const emergencyStateDetails =
        emergencyStateCopy[emergencyStateCode] || emergencyStateCopy.STATE_UNKNOWN;

    const resolvedEmergencyLocked = (
        typeof emergencyLocked === "boolean"
            ? emergencyLocked
            : emergencyStateCode === "LOCKED"
    );
    const resolvedEmergencyLockClass = (
        emergencyLockClass
        || (
            emergencyStateCode === "LOCKED"
                ? "locked"
                : emergencyStateCode === "READY"
                    ? "unlocked"
                    : "unknown"
        )
    );
    const resolvedEmergencyLockValue = (
        emergencyLockValue
        || (resolvedEmergencyLocked ? "LOCKED" : "UNLOCKED")
    );
    const resolvedUnlockAllowed = (
        typeof unlockAllowed === "boolean"
            ? unlockAllowed
            : (
                emergencyStateCode !== "READY"
                && emergencyStateCode !== "PROCESSING"
            )
    );
    const resolvedEmergencyButtonDisabled = (
        typeof emergencyButtonDisabled === "boolean"
            ? emergencyButtonDisabled
            : emergencyStateCode !== "READY"
    );

    const executionMode = config.executionMode || "SIMULATION";
    const executionSource = config.executionMode ? "RUNTIME" : "NOT CONNECTED";
    const realOrderSource = config.realOrderAuthorityKnown ? "RUNTIME" : "NOT CONNECTED";
    // Problem 2/3: the START REQUEST (settings.tradingMode) is a distinct
    // semantic class from the CURRENT RUNTIME / AUTHORITY (executionMode,
    // realOrderAllowed, capital authority). Selecting LIVE in the UI must not
    // present current PAPER execution authority as if it were LIVE authority.
    const requestedMode = settings.tradingMode || "UNKNOWN";
    const currentExecutionMode = executionMode;
    const requestedModeDiffersFromExecution = (
        requestedMode === "LIVE"
        && currentExecutionMode !== "LIVE"
    );

     const {
        reviewReadiness,
        startReadiness,
        entryReadiness,
        readinessValues,
        selectionRuntime,
        selectedRuntimeSymbol,
        selectionReadiness,
        emergencyReadiness,
        positionState,
        orderAuthority,
        governanceReadiness,
        executionReadiness,
        mmEntryReadiness,
        startMmReadiness,
        mmReadinessSource,
        leverageReadiness,
    } = deriveOperationReadiness({
        botRunning,
        tradingMode: settings.tradingMode,
        dryRun: config.dryRun ?? config.dry_run ?? (
            settings.tradingMode === "PAPER"
        ),
        selectionMode: settings.selectionMode,
        autoMarketState: config.autoMarketState,
        displaySymbol: config.displaySymbol,
        emergencyState,
        position,
        pendingOrder,
        governanceStatus,
        realOrderAllowed,
        executionEnabled,
        executionEntryAllowed,
        recommendedAction,
        riskState,
        requestedLeverage: settings.requestedLeverage,
        maximumLeverage: mmConfiguration?.maximumLeverage,
        mmConfiguration,
        mmBlockReasons,
        mmRecoveryRequired,
        mmConfigurationError: Boolean(mmConfigurationError),
        allowLive: config.allowLive,
        tradeMode: config.tradeMode,
        paperBootstrapEligible: config.paperBootstrapEligible,
    });
    const summary = operationPreparationSummary(settings, selectedRuntimeSymbol, mmDraft?.riskPerTradePercent);
    const maximumLeverage = authoritativeLeverage(mmConfiguration?.maximumLeverage);
    const effectiveLeverage = authoritativeLeverage(
        leverageAuthority?.effectiveLeverage,
    );
    const leverageReason = String(leverageAuthority?.reason || "").trim();
    // WF-6: while STOPPED the Effective Leverage row reflects the last
    // completed start. If the operator has since requested an over-limit
    // leverage (front-end leverage authority BLOCKED) or the backend
    // authority reports the request not allowed, the stale prior-runtime
    // effective value is misleading and is suppressed. The fail-closed gate
    // remains authoritative. Presentation only.
    const leverageRequestBlocked = leverageReadiness === "BLOCKED"
        || leverageAuthority?.allowed === false;
    const effectiveLeverageDisplay = leverageRequestBlocked
        ? (
            leverageReason === "MAXIMUM_LEVERAGE"
                ? "— · MAXIMUM_LEVERAGE"
                : "— · leverage over MM limit"
        )
        : effectiveLeverage === "UNAVAILABLE"
            && leverageReason === "MAXIMUM_LEVERAGE"
            ? "— · MAXIMUM_LEVERAGE"
            : effectiveLeverage;
    const controlsDisabled = botRunning === true;

    const mmAvailable = Boolean(mmDraft);
    const mmRiskValue = mmDraft ? Number(mmDraft.riskPerTradePercent) : undefined;
    const mmExposureValue = mmDraft ? Number(mmDraft.totalExposurePercent) : undefined;
    const mmDrawdownValue = mmDraft ? Number(mmDraft.maximumDrawdownPercent) : undefined;
    const mmCompoundingValue = mmDraft?.compoundingEnabled === true;
    const savedCompounding = typeof mmConfiguration?.compoundingEnabled === "boolean"
        ? mmConfiguration.compoundingEnabled
        : null;
    const compoundingPolicy = savedCompounding === null
        ? "UNAVAILABLE"
        : savedCompounding
            ? "ON — CURRENT AVAILABLE CAPITAL"
            : "OFF — INITIAL REFERENCE CAPITAL";
    const mmControlsDisabled = controlsDisabled || !mmAvailable || mmUpdating;

    const MM_CONNECTED_FIELDS = [
        "riskPerTradePercent",
        "totalExposurePercent",
        "maximumDrawdownPercent",
        "compoundingEnabled",
    ];
    const mmDirty = mmAvailable
        && Boolean(mmConfiguration)
        && MM_CONNECTED_FIELDS.some(
            (key) => mmDraft[key] !== mmConfiguration[key],
        );

    const withCurrentOption = (options, value) => {
        const numeric = Number(value);
        if (Number.isFinite(numeric) && !options.includes(numeric)) {
            return [...options, numeric].sort((left, right) => left - right);
        }
        return options;
    };

    const mmRiskOptions = mmAvailable
        ? withCurrentOption(OPERATION_PREPARATION_OPTIONS.riskPerTrade, mmRiskValue)
        : OPERATION_PREPARATION_OPTIONS.riskPerTrade;
    const mmExposureOptions = mmAvailable
        ? withCurrentOption(OPERATION_PREPARATION_OPTIONS.maxExposure, mmExposureValue)
        : OPERATION_PREPARATION_OPTIONS.maxExposure;
    const mmDrawdownOptions = mmAvailable
        ? withCurrentOption(OPERATION_PREPARATION_OPTIONS.maxDrawdown, mmDrawdownValue)
        : OPERATION_PREPARATION_OPTIONS.maxDrawdown;

    // Problem 1/9: MM now auto-persists a valid draft (auto-reconcile) so the
    // operator no longer has to manually Save MM. An invalid draft is never
    // silently persisted; it is surfaced as an explicit invalid state.
    // mmDraftInvalid is computed upstream (BotControl) from the authoritative
    // validation so it stays test-friendly.
    const mmDraftInvalidState = Boolean(mmDraftInvalid);
    const mmDraftState = mmUpdating
        ? "AUTO-SAVING"
        : mmConflict
            ? "CONFLICT"
            : mmUpdateError
                ? "UPDATE FAILED"
                : mmDraftInvalidState
                    ? "INVALID (NOT SAVED)"
                    : mmDirty
                        ? "PENDING AUTO-SAVE"
                        : mmAvailable
                            ? "SAVED"
                            : mmLoading
                                ? "LOADING"
                                : "UNAVAILABLE";
    const mmSaveDisabled = !mmAvailable
        || mmUpdating
        || Boolean(mmConflict)
        || Boolean(mmConfigurationError)
        || mmDraftInvalidState;

    // WF-3: Final Preparation must distinguish the UNSAVED MM DRAFT from the
    // SAVED value that START actually sends. Presentation only.
    const savedRiskPercent = mmConfiguration
        ? String(mmConfiguration.riskPerTradePercent)
        : null;
    const mmRiskDivergence = mmAvailable
        && Boolean(mmConfiguration)
        && String(mmDraft.riskPerTradePercent) !== savedRiskPercent;

    // WF-1: explicit block-reason + corrective guidance (pre-start only).
    // Derives EVERY actionable blocker from the authoritative readiness
    // values. On recovery a corrected blocker no longer appears. gated on
    // reviewReadiness (=== startReadiness) so a READY start shows no stale
    // guidance and a RUNNING bot never shows a pre-start fault.
    const hasBlockedStart = (!botRunning && reviewReadiness !== "READY");
    const blockGuidance = hasBlockedStart
        ? deriveOperationBlockGuidance({
            settings,
            config,
            emergencyReadiness,
            positionState,
            orderAuthority,
            selectionReadiness,
            selectionRuntime,
            selectedRuntimeSymbol,
            startMmReadiness,
            mmEntryReadiness,
            governanceReadiness,
            executionReadiness,
            leverageReadiness,
            emergencyState,
            position,
            pendingOrder,
            governanceStatus,
            realOrderAllowed,
            executionEnabled,
            mmConfiguration,
            mmDraft,
        })
        : null;

    // WF-2: while RUNNING, pre-start readiness gates are N/A / ACTIVE, not
    // a fault. Presentation only — the underlying start gate is unchanged.
    const runningStartReadiness = botRunning
        ? "N/A — BOT ALREADY RUNNING"
        : startReadiness;
    const runningEntryReadiness = botRunning ? "ACTIVE（実行中）" : entryReadiness;
    const runningExecutionReadiness = (
        botRunning && executionEnabled ? "ACTIVE（実行中）" : executionReadiness
    );

    {botRunning && <div className="operation-prep-running-indicator" />}

    const autoTradeValue = botRunning ? autoTradeStateText : summary.autoTrade;
    const autoTradeStatus = botRunning ? String(autoTradeStateText || "").includes("ON") : false;

    // WF: FINAL PREPARATION mirrors TRADE SETTINGS ⑤ by separating the
    // start-time configured switches (LOOP ON START / AUTO TRADE ON START)
    // from the current runtime state (RUNTIME LOOP / RUNTIME AUTO TRADE).
    // Runtime is authoritative (loopState / autoTradeStateText); the
    // configured values come from settings (loopOnStart / autoTradeOnStart).
    const runtimeLoopValue = botRunning
        ? (loopState ? String(loopState) : (loopChecked ? "ON" : "OFF"))
        : "STOPPED";
    const mmExposureDisplay = displayPercent(mmExposureValue);
    const mmDrawdownDisplay = displayPercent(mmDrawdownValue);

    // START GUARDS: presentation-only aggregate over the authoritative
    // readiness values. Never re-derives or overrides the fail-closed START
    // gate — it only summarizes the existing model states.
    const startGuardsCounts = (() => {
        const states = readinessValues || [];
        const ready = states.filter((value) => ["READY", "SAFE", "FLAT", "ACTIVE", "NOT_RELEVANT"].includes(value)).length;
        const waiting = states.filter((value) => ["WAITING", "PENDING", "PROCESSING", "STARTING", "ON HOLD"].includes(value)).length;
        const blocked = states.filter((value) => ["BLOCKED", "ERROR", "FAILED", "LOCKED", "UNAVAILABLE", "UNKNOWN"].includes(value)).length;
        return { ready, waiting, blocked, total: states.length };
    })();
    const startGuardsState = reviewReadiness;
    const startGuardsLabel = botRunning
        ? "N/A — RUNNING"
        : startGuardsState === "READY"
            ? "READY"
            : startGuardsState === "BLOCKED"
                ? "BLOCKED"
                : "WAITING";
    const startGuardsTone = botRunning ? "na" : startGuardsLabel.toLowerCase();

    const safetyDetailRows = [
        { label: "Emergency（緊急停止）", source: "RUNTIME", value: emergencyReadiness },
        { label: "Position（ポジション）", source: "RUNTIME", value: positionState },
        { label: "Pending Order Authority（保留注文権限）", source: "RUNTIME", value: orderAuthority },
        { label: "Market Selection（市場選択）", source: settings.selectionMode === "MANUAL" ? "OPERATOR" : "RUNTIME", value: selectionReadiness },
        { label: "MM START CONFIG（開始設定）", source: "MM CONFIG", value: startMmReadiness },
        { label: "ENTRY PERMISSION（エントリー権限）", source: mmReadinessSource, value: runningEntryReadiness },
        { label: "Governance（ガバナンス）", source: "RUNTIME", value: governanceReadiness },
        { label: "Execution（執行）", source: "RUNTIME", value: runningExecutionReadiness },
        { label: "Leverage Authority（レバレッジ権限）", source: "MM CONFIG", value: leverageReadiness },
    ];

return (
        <div className="operation-preparation" data-testid="operation-preparation">
            {/* 顶部控制带：FINAL PREPARATION | EMERGENCY */}
            <div className="operation-top-band">
                <section className="operation-prep-final operation-prep-final--top" data-testid="operation-preparation-summary">
                    <h3 data-testid="final-preparation-heading">FINAL PREPARATION</h3>
                    <div className="operation-prep-summary">
                        <Section number="1" testId="final-prep-trading-mode" title="TRADING MODE">
                            <DerivedRow label="MODE" source="OPERATOR" value={summary.mode} valueClass="operation-prep-value--setting" provenance="REQ" />
                            {requestedModeDiffersFromExecution && (
                                <div className="operation-prep-mode-divergence" data-testid="mode-divergence">
                                    <span>START REQUEST = {requestedMode}</span>
                                    <strong>CURRENT EXECUTION AUTHORITY = {currentExecutionMode}</strong>
                                    <small>LIVE / REAL-ORDER authority is NOT granted by selecting LIVE（LIVE選択だけでは実注文権限は付与されません）</small>
                                </div>
                            )}
                        </Section>

                        <Section number="2" testId="final-prep-market-selection" title="MARKET SELECTION">
                            <DerivedRow label="MARKET" source="OPERATOR" value={summary.market} valueClass="operation-prep-value--setting" provenance="REQ" />
                            <DerivedRow label="SYMBOL" source={summary.symbol === "AUTO SELECT" ? "DERIVED" : "OPERATOR"} value={summary.symbol} valueClass="operation-prep-value--setting" provenance="REQ" />
                            <DerivedRow label="SELECTION RUNTIME" source="RUNTIME" status value={selectionRuntime} provenance="CUR" />
                        </Section>

                        <Section number="3" testId="final-prep-money-management" title="MONEY MANAGEMENT">
                            <DerivedRow label="RISK / Trade（1取引リスク）" source={mmRiskDivergence ? "MM DRAFT" : (mmAvailable ? "MM CONFIG" : "NOT CONNECTED")} value={mmRiskDivergence ? `${summary.riskPerTrade} DRAFT → START ${savedRiskPercent}%` : summary.riskPerTrade} valueClass="operation-prep-value--setting" provenance="REQ" />
                            <DerivedRow label="CAPITAL AUTHORITY" source={capitalAuthorityStatus || "NOT CONNECTED"} value={capitalAuthorityStatus || "UNKNOWN"} provenance="CUR" />
                            <DerivedRow label="AVAILABLE CAPITAL" source={availableCapital !== undefined ? "RUNTIME" : "SETTINGS"} value={availableCapital !== undefined ? String(availableCapital) : "UNAVAILABLE"} provenance="CUR" />
                            <DerivedRow label="COMPOUNDING POLICY" source={savedCompounding === null ? "NOT CONNECTED" : "MM CONFIG"} value={compoundingPolicy} provenance="CUR" />
                            <DerivedRow label="CAPITAL BASIS" source={capitalBasis !== undefined ? "MM RUNTIME" : "NOT CONNECTED"} value={capitalBasis !== undefined ? String(capitalBasis) : "UNAVAILABLE"} provenance="CUR" />
                            <DerivedRow label="MAX EXPOSURE" source={mmAvailable ? "MM CONFIG" : "NOT CONNECTED"} value={mmExposureDisplay} provenance="CUR" />
                            <DerivedRow label="MAX DRAWDOWN" source={mmAvailable ? "MM CONFIG" : "NOT CONNECTED"} value={mmDrawdownDisplay} provenance="CUR" />
                            <DerivedRow label="RISK BUDGET" source={riskBudget !== undefined ? "RUNTIME" : "MAX_DRAWDOWN"} value={riskBudget !== undefined ? String(riskBudget) : "UNAVAILABLE"} provenance="CUR" />
                            <DerivedRow label="SIZING READINESS" source={mmReadinessSource} value={mmEntryReadiness.label} provenance="CUR" />
                            <DerivedRow label="MM RUNTIME" source={lifecycleState || mmRuntime || "NOT CONNECTED"} status value={lifecycleState || mmRuntime || "UNKNOWN"} provenance="CUR" />
                        </Section>

                        <Section number="4" testId="final-prep-trade-execution" title="TRADE / EXECUTION">
                            <DerivedRow label="REQUESTED LEVERAGE" source="OPERATOR" value={summary.requestedLeverage} valueClass="operation-prep-value--setting" provenance="REQ" />
                            <DerivedRow label="MM LEVERAGE LIMIT" source={maximumLeverage === "UNAVAILABLE" ? "NOT CONNECTED" : "MM CONFIG"} value={maximumLeverage} provenance="CUR" />
                            <DerivedRow label="EFFECTIVE LEVERAGE" source={effectiveLeverage === "UNAVAILABLE" ? "NOT CONNECTED" : "MM START"} status value={effectiveLeverageDisplay} provenance="CUR" />
                            <DerivedRow label="POSITION SIZE CAP" source={botRunning ? "RUNTIME" : "OPERATOR"} value={summary.positionSize} valueClass="operation-prep-value--setting" provenance={botRunning ? "CUR" : "REQ"} />
                            <DerivedRow label="STOP LOSS" source={botRunning ? "RUNTIME" : "OPERATOR"} value={summary.stopLoss} valueClass="operation-prep-value--setting" provenance={botRunning ? "CUR" : "REQ"} />
                            <DerivedRow label="TAKE PROFIT" source={botRunning ? "RUNTIME" : "OPERATOR"} value={summary.takeProfit} valueClass="operation-prep-value--setting" provenance={botRunning ? "CUR" : "REQ"} />
                            <DerivedRow label="TRAILING STOP" source={botRunning ? "RUNTIME" : "OPERATOR"} value={summary.trailingStop} valueClass="operation-prep-value--setting" provenance={botRunning ? "CUR" : "REQ"} />
                            <DerivedRow label="TIMEFRAME" source={botRunning ? "RUNTIME" : "OPERATOR"} value={summary.timeframe} valueClass="operation-prep-value--setting" provenance={botRunning ? "CUR" : "REQ"} />
                            <DerivedRow label="EXECUTION" source={executionSource} value={executionMode} provenance="CUR" />
                            <DerivedRow label="REAL ORDER" source={realOrderSource} status value={realOrderAllowed ? "ALLOWED" : "DISABLED"} provenance="CUR" />
                        </Section>

                        <Section number="5" testId="final-prep-automation" title="AUTOMATION">
                            <DerivedRow label="LOOP ON START" source="OPERATOR" value={settings.loopOnStart ? "ON" : "OFF"} valueClass="operation-prep-value--setting" provenance="REQ" />
                            <DerivedRow label="AUTO TRADE ON START" source="OPERATOR" value={settings.autoTradeOnStart ? "ON" : "OFF"} valueClass="operation-prep-value--setting" provenance="REQ" />
                            <DerivedRow label="RUNTIME LOOP" source="RUNTIME" status={botRunning} value={runtimeLoopValue} provenance="CUR" />
                            <DerivedRow label="RUNTIME AUTO TRADE" source="RUNTIME" status={autoTradeStatus} value={autoTradeValue} provenance="CUR" />
                            <DerivedRow label="AUTO SELECTION START" source="DERIVED" value={settings.selectionMode === "AUTO" ? "AUTO MODE → ON START" : "MANUAL MODE"} provenance="REQ" />
                        </Section>

                        <section className="operation-prep-section operation-prep-section--final-readiness" data-testid="final-prep-start-readiness">
                            <header><h3>START / READINESS（開始 / 準備状態）</h3></header>
                            <div className="operation-prep-section__body">
                                <DerivedRow label="START READINESS" source="UI REVIEW" status value={runningStartReadiness} provenance="CUR" />
                                <DerivedRow label="ENTRY READINESS" source="RUNTIME" status value={runningEntryReadiness} provenance="CUR" />
                            </div>
                            <div className="operation-prep-start-guards" data-testid="start-guards">
                                <span className="operation-prep-start-guards__label">START GUARDS</span>
                                <strong className={`operation-prep-status operation-prep-status--${startGuardsTone}`} data-testid="start-guards-state">
                                    <i aria-hidden="true" />
                                    {startGuardsLabel}
                                </strong>
                                {!botRunning && startGuardsLabel !== "READY" && (
                                    <span className="operation-prep-start-guards__count" data-testid="start-guards-count">
                                        {startGuardsCounts.ready} READY / {startGuardsCounts.waiting} WAITING / {startGuardsCounts.blocked} BLOCKED
                                        <small className="operation-prep-start-guards__scope">
                                            (START gate only — runtime ENTRY / Governance gates are separate, see SAFETY / READINESS DETAILS)
                                        </small>
                                    </span>
                                )}
                            </div>
                            {blockGuidance && (
                                <div className="operation-prep-abnormal" data-testid="abnormal-guidance">
                                    <span className="operation-prep-abnormal__title">START not ready（開始不可）</span>
                                    {blockGuidance.map((item) => (
                                        <div className="operation-prep-abnormal__row" data-testid={`abnormal-${item.id}`} key={item.id}>
                                            <span>{item.label}</span>
                                            <strong>{item.status}</strong>
                                        </div>
                                    ))}
                                </div>
                            )}
                            <div className="operation-prep-details" data-testid="safety-readiness-details">
                                <button
                                    aria-expanded={safetyDetailsOpen}
                                    className="operation-prep-details__toggle"
                                    data-testid="safety-details-toggle"
                                    onClick={() => setSafetyDetailsOpen((open) => !open)}
                                    type="button"
                                >
                                    <span aria-hidden="true">{safetyDetailsOpen ? "▲" : "▼"}</span>
                                    SAFETY / READINESS DETAILS — RUNTIME &amp; ENTRY GUARDS
                                </button>
                                {safetyDetailsOpen && (
                                    <div className="operation-prep-details__body" data-testid="safety-readiness-details-body">
                                        <p className="operation-prep-details__intro">
                                            These are CURRENT runtime / entry guards. They are fail-closed <em>after</em> START and are not pre-START prerequisites.
                                        </p>
                                        <div className="operation-prep-derived-list operation-prep-derived-list--safety">
                                            {safetyDetailRows.map((row) => (
                                                <DerivedRow key={row.label} label={row.label} source={row.source} status value={row.value} provenance="CUR" />
                                            ))}
                                        </div>
                                        {!botRunning && (
                                            <div className="operation-prep-workflow" data-testid="operation-workflow">
                                                <span className="operation-prep-workflow__title">WORKFLOW / 作業手順</span>
                                                <span>①–⑤ CONFIGURE（構成）</span>
                                                <span className="operation-prep-workflow__arrow">↓</span>
                                                <span>FINAL PREPARATION VALIDATION（最終確認）</span>
                                                <span className="operation-prep-workflow__arrow">↓</span>
                                                <span>Resolve BLOCKED / WAITING items（BLOCKED/WAITINGの解消）</span>
                                                <span className="operation-prep-workflow__arrow">↓</span>
                                                <span>START when READY（READY時に開始）</span>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                            {mmRiskDivergence && (
                                <small className="operation-prep-draft-note" data-testid="mm-risk-draft-note">
                                    RISK shown is the MM DRAFT; START sends the authoritative saved value（表示はMMドラフト。STARTには権威ある保存済み値を送信します）. A valid draft auto-reconciles to the saved configuration.
                                </small>
                            )}
                        </section>
                    </div>
                </section>

                <div className="operation-emergency-controls">
                    <div className="operation-emergency-block">
                        <button
                            className="emergency-stop-button operation-emergency-button"
                            disabled={resolvedEmergencyButtonDisabled}
                            onClick={openEmergencyConfirm}
                            aria-busy={emergencyPending ? "true" : "false"}
                            type="button"
                        >
                            {emergencyPending
                                ? "EMERGENCY IN PROGRESS..."
                                : "EMERGENCY STOP"
                            }
                        </button>
                        <div className="operation-emergency-lock">
                            <span className="operation-state-label">
                                LOCK
                            </span>
                            <strong className={resolvedEmergencyLockClass}>
                                ● {resolvedEmergencyLockValue}
                            </strong>
                        </div>
                    </div>
                    <div className="operation-start-controls">
                        <div className="operation-prep-start operation-prep-start--right" data-testid="ready-to-start">
                            {botRunning ? (
                                <div><span className="operation-prep-status operation-prep-status--running"><i aria-hidden="true" /></span><strong>N/A — BOT ALREADY RUNNING / 実行中 — START判定対象外</strong></div>
                            ) : null}
                            {!botRunning && (
                                <div><span className={`operation-prep-status operation-prep-status--${reviewReadiness}`}><i aria-hidden="true" /></span><strong>{reviewReadiness === "READY" ? "READY TO START" : reviewReadiness === "BLOCKED" ? "BLOCKED" : "WAITING"}</strong></div>
                            )}
                            {blockGuidance && (
                                <div className="operation-prep-block-guidance" data-testid="block-guidance">
                                    <span className="operation-prep-block-guidance__title">START NOT READY — resolve the following（開始不可 — 以下を解消）:</span>
                                    <ul>
                                        {blockGuidance.map((item) => (
                                            <li key={item.id} data-testid={`block-guidance-${item.id}`}>
                                                <strong>{item.label}</strong> — {item.status}
                                                <div className="operation-prep-block-guidance__values">
                                                    <span>current / 現在値: {item.current}</span>
                                                    <span>required / 必要値: {item.required}</span>
                                                </div>
                                                <div className="operation-prep-block-guidance__fix">
                                                    <span>{item.en}</span>
                                                    <span>{item.ja}</span>
                                                    <span>Fix / 修正: {item.fix}</span>
                                                </div>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </div>
                        {botRunning ? null : (
                            <small>Runtime guards remain authoritative. Preview settings are not sent to execution.</small>
                        )}
                        {children}
                    </div>
                </div>
            </div>

            {/* 紧急状态详细信息（仅在非READY状态显示） */}
            {emergencyStateCode !== "READY" && (
                <div className="operation-emergency-details">
                    <div
                        className={
                            "operation-emergency-status "
                            + `operation-emergency-status--${emergencyStateDetails.tone}`
                        }
                    >
                        <span className="operation-emergency-status__eyebrow">
                            EMERGENCY STATUS
                        </span>

                        <strong className="operation-emergency-status__state">
                            {emergencyStateDetails.label}
                        </strong>

                        <span className="operation-emergency-status__message">
                            {emergencyStateDetails.text}
                        </span>

                        {emergencyStateCode === "PROCESSING" && (
                            <span className="operation-emergency-status__pending">
                                PROCESSING
                            </span>
                        )}

                        {emergencyStateCode === "LOCKED" && lockedFacts.length > 0 && (
                            <div className="operation-emergency-facts">
                                {lockedFacts.map((fact) => (
                                    <span key={fact}>
                                        {fact}
                                    </span>
                                ))}
                            </div>
                        )}

                        {emergencyStateCode === "ACTION_REQUIRED"
                            && actionWarnings.length > 0 && (
                            <div className="operation-emergency-warnings">
                                {actionWarnings.map((warning) => (
                                    <span key={warning}>
                                        {warning}
                                    </span>
                                ))}
                            </div>
                        )}

                        {lastResultMessage && (
                            <span className="operation-emergency-status__message">
                                {lastResultMessage}
                            </span>
                        )}
                    </div>

                    {emergencyStateCode === "LOCKED" && (
                        <div className="operation-emergency-note">
                            Emergency Lock is active.（Emergency Lockが有効です）
                        </div>
                    )}

                    {emergencyStateCode !== "READY" && (
                        <button
                            className="operation-emergency-unlock"
                            disabled={unlockPending || !resolvedUnlockAllowed}
                            onClick={handleReturnToNormal}
                            type="button"
                        >
                            {unlockPending ? "復帰中..." : "通常に戻す"}
                        </button>
                    )}

                    {emergencyStateCode !== "READY" && (
                        <div className="operation-emergency-detail">
                            Execution path: {String(emergencyPath).toUpperCase()}
                        </div>
                    )}

                    {emergencyError && (
                        <div
                            className="operation-emergency-error"
                            data-testid="emergency-error"
                            role="alert"
                        >
                            {emergencyError}
                        </div>
                    )}

                    {unlockError && (
                        <div
                            className="operation-emergency-error"
                            data-testid="emergency-unlock-error"
                            role="alert"
                        >
                            {unlockError}
                        </div>
                    )}
                </div>
            )}

            {emergencyConfirmOpen && (
                <div
                    aria-label="Confirm emergency stop"
                    aria-modal="false"
                    className="operation-emergency-confirm"
                    role="dialog"
                >
                    <div className="operation-emergency-confirm__title">EMERGENCY STOP</div>
                    <div className="operation-emergency-confirm__body">
                        This action will activate Emergency Lock, disable Auto Trade,
                        cancel eligible open orders, and flatten eligible positions.
                    </div>
                    <div className="operation-emergency-confirm__actions">
                        <button
                            className="operation-emergency-confirm__cancel"
                            disabled={emergencyPending}
                            onClick={cancelEmergencyConfirm}
                            type="button"
                        >
                            CANCEL
                        </button>
                        <button
                            className="operation-emergency-confirm__confirm"
                            disabled={emergencyPending}
                            onClick={confirmEmergency}
                            type="button"
                        >
                            CONFIRM EMERGENCY
                        </button>
                    </div>
                </div>
            )}

            {/* TRADE SETTINGS（取引設定）— collapsible disclosure wrapping the ①–⑤ detail cards.
                Presentation-only: collapse/expand never resets or mutates any setting value. */}
            <section className="operation-trade-settings" data-testid="trade-settings-disclosure">
                <button
                    aria-controls="trade-settings-body"
                    aria-expanded={tradeSettingsOpen}
                    className="operation-trade-settings__toggle"
                    data-testid="trade-settings-toggle"
                    onClick={() => setTradeSettingsOpen((open) => !open)}
                    type="button"
                >
                    <span className="operation-trade-settings__title">TRADE SETTINGS（取引設定）</span>
                    <span aria-hidden="true" className="operation-trade-settings__indicator">
                        {tradeSettingsOpen ? "▲" : "▼"}
                    </span>
                </button>
                <div
                    className={
                        "operation-trade-settings__body"
                        + (tradeSettingsOpen ? "" : " operation-trade-settings__body--collapsed")
                    }
                    data-testid="trade-settings-body"
                    id="trade-settings-body"
                >
                <div className="operation-main-grid">
                {/* 左列 */}
                <div className="operation-column-left">
                    <Section number="1" testId="trading-mode-section" title="TRADING MODE（取引モード）">
                        <span className="operation-prep-label">Mode（モード）</span>
                        <SegmentedControl
                            disabled={controlsDisabled}
                            label="Trading mode"
                            onChange={(value) => changeSetting("tradingMode", value)}
                            options={OPERATION_PREPARATION_OPTIONS.tradingModes}
                            value={settings.tradingMode}
                        />
                        {settings.tradingMode === "LIVE" && (
                            <p className="operation-prep-warning">LIVE request selected. Existing backend and Governance guards remain authoritative.</p>
                        )}
                    </Section>

                    <Section number="2" testId="market-selection-section" title="MARKET SELECTION（市場選択）">
                        <span className="operation-prep-label">SELECTION MODE</span>
                        <SegmentedControl
                            disabled={controlsDisabled}
                            label="Market selection mode"
                            onChange={(value) => changeSetting("selectionMode", value)}
                            options={OPERATION_PREPARATION_OPTIONS.selectionModes}
                            value={settings.selectionMode}
                        />
                        {settings.selectionMode === "MANUAL" ? (
                            <SelectField
                                disabled={controlsDisabled}
                                id="operation-prep-symbol"
                                label="SYMBOL"
                                onChange={(value) => changeSetting("manualSymbol", value)}
                                options={OPERATION_PREPARATION_OPTIONS.symbols}
                                value={settings.manualSymbol}
                            />
                        ) : (
                            <div className="operation-prep-derived-list">
                                <DerivedRow label="SELECTION RUNTIME" source="RUNTIME" status value={selectionRuntime} />
                                <DerivedRow label="SELECTION" source="RUNTIME" value={selectedRuntimeSymbol || "WAITING"} />
                            </div>
                        )}
                        <a className="operation-prep-link" href="/market-intelligence">Market Intelligence →</a>
                    </Section>

                    <Section bodyClassName="operation-prep-section__body--dense" number="3" testId="money-management-section" title="MONEY MANAGEMENT（資金管理）">
                        <SelectField
                            disabled={mmControlsDisabled}
                            format={percentage}
                            id="operation-prep-risk"
                            label="RISK / Trade（1取引リスク）"
                            onChange={(value) => onMmDraftChange({ riskPerTradePercent: String(value) })}
                            options={mmRiskOptions}
                            value={mmAvailable ? mmRiskValue : ""}
                        />
                        <DerivedRow label="CAPITAL AUTHORITY" source={capitalAuthorityStatus || "NOT CONNECTED"} value={capitalAuthorityStatus || "UNKNOWN"} />
                        <DerivedRow label="AVAILABLE CAPITAL" source={availableCapital !== undefined ? "RUNTIME" : "SETTINGS"} value={availableCapital !== undefined ? String(availableCapital) : "UNAVAILABLE"} />
                        <DerivedRow label="COMPOUNDING POLICY" source={savedCompounding === null ? "NOT CONNECTED" : "MM CONFIG"} value={compoundingPolicy} />
                        <ToggleControl disabled={mmControlsDisabled} label="Compounding" onChange={(value) => onMmDraftChange({ compoundingEnabled: value })} value={mmCompoundingValue} />
                        <DerivedRow label="CAPITAL BASIS" source={capitalBasis !== undefined ? "MM RUNTIME" : "NOT CONNECTED"} value={capitalBasis !== undefined ? String(capitalBasis) : "UNAVAILABLE"} />
                        <SelectField disabled={mmControlsDisabled} format={wholePercentage} id="operation-prep-exposure" label="MAX Exposure（最大エクスポージャー）" onChange={(value) => onMmDraftChange({ totalExposurePercent: String(value) })} options={mmExposureOptions} value={mmAvailable ? mmExposureValue : ""} />
                        <SelectField disabled={mmControlsDisabled} format={wholePercentage} id="operation-prep-drawdown" label="MAX Drawdown（最大ドローダウン）" onChange={(value) => onMmDraftChange({ maximumDrawdownPercent: String(value) })} options={mmDrawdownOptions} value={mmAvailable ? mmDrawdownValue : ""} />
                        <DerivedRow label="RISK BUDGET" source={riskBudget !== undefined ? "RUNTIME" : "MAX_DRAWDOWN"} value={riskBudget !== undefined ? String(riskBudget) : "UNAVAILABLE"} />
                        <div className="operation-prep-mm-save" data-testid="mm-save-controls">
                            <span className="operation-prep-mm-state" data-testid="mm-save-state">{mmDraftState}</span>
                            <button disabled={mmSaveDisabled} onClick={onMmReset} type="button">Reset MM</button>
                            <button disabled={mmSaveDisabled} onClick={onMmSave} type="button">Save MM</button>
                            <small className="operation-prep-mm-save__hint">A valid edit auto-persists; manual Save is optional.（有効な編集は自動保存されます）</small>
                        </div>
                        {mmUpdateError && <p className="operation-prep-error" role="alert">{mmUpdateError.message ?? "Money Management update failed."}</p>}
                        {mmConfigurationError && <p className="operation-prep-error" role="alert">{mmConfigurationError.message ?? "Money Management configuration unavailable."}</p>}
                        {mmConflict && <p className="operation-prep-error" role="alert">Configuration conflict. Review before saving.</p>}
                        <DerivedRow label="SIZING READINESS" source={mmReadinessSource} value={mmEntryReadiness.label} />
                        <DerivedRow label="MM RUNTIME" source={lifecycleState || mmRuntime || "NOT CONNECTED"} status value={lifecycleState || mmRuntime || "UNKNOWN"} />
                        <a className="operation-prep-link" href="/money-management">Money Management →</a>
                    </Section>
                </div>

                {/* 右列 */}
                <div className="operation-column-center">
                    <Section bodyClassName="operation-prep-section__body--automation" number="4" testId="trade-execution-section" title="TRADE / EXECUTION（取引 / 執行）">
                        <SelectField disabled={controlsDisabled} format={leverage} id="operation-prep-leverage" label="Requested Leverage（要求レバレッジ）" onChange={(value) => changeSetting("requestedLeverage", Number(value))} options={OPERATION_PREPARATION_OPTIONS.requestedLeverage} value={settings.requestedLeverage} />
                        <DerivedRow label="MM Leverage Limit（MMレバレッジ上限）" source={maximumLeverage === "UNAVAILABLE" ? "NOT CONNECTED" : "MM CONFIG"} value={maximumLeverage} />
                        <DerivedRow label="Effective Leverage（有効レバレッジ）" source={effectiveLeverage === "UNAVAILABLE" ? "NOT CONNECTED" : "MM START"} status value={effectiveLeverageDisplay} />
                        <SelectField disabled={controlsDisabled} id="operation-prep-position-size" label="Position Size Cap（ポジション上限）" onChange={(value) => changeSetting("positionSize", Number(value))} options={OPERATION_PREPARATION_OPTIONS.positionSize} value={settings.positionSize} />
                        <SelectField disabled={controlsDisabled} format={percentage} id="operation-prep-stop-loss" label="Stop Loss（損切り）" onChange={(value) => changeSetting("stopLossPercent", Number(value))} options={OPERATION_PREPARATION_OPTIONS.stopLossPercent} value={settings.stopLossPercent} />
                        <SelectField disabled={controlsDisabled} format={percentage} id="operation-prep-take-profit" label="Take Profit（利確）" onChange={(value) => changeSetting("takeProfitPercent", Number(value))} options={OPERATION_PREPARATION_OPTIONS.takeProfitPercent} value={settings.takeProfitPercent} />
                        <span className="operation-prep-label">TRAILING STOP</span>
                        <ToggleControl disabled={controlsDisabled} label="Trailing stop" onChange={(value) => changeSetting("trailingStop", value)} value={settings.trailingStop} />
                        <SelectField disabled={controlsDisabled} id="operation-prep-timeframe" label="Timeframe（時間足）" onChange={(value) => changeSetting("timeframe", value)} options={OPERATION_PREPARATION_OPTIONS.timeframes} value={settings.timeframe} />
                        <DerivedRow label="Execution（執行）" source={executionSource} value={executionMode} />
                        <DerivedRow label="REAL ORDER" source={realOrderSource} status value={realOrderAllowed ? "ALLOWED" : "DISABLED"} />
                    </Section>

                    <Section bodyClassName="operation-prep-section__body--automation" number="5" testId="automation-section" title="AUTOMATION（自動化）">
                        <span className="operation-prep-label">LOOP ON START</span>
                        <ToggleControl disabled={controlsDisabled} label="Loop on start" onChange={(value) => changeSetting("loopOnStart", value)} value={settings.loopOnStart} />
                        <span className="operation-prep-label">AUTO TRADE ON START</span>
                        <ToggleControl disabled={controlsDisabled} label="Auto Trade on start" onChange={(value) => changeSetting("autoTradeOnStart", value)} value={settings.autoTradeOnStart} />
                        {botRunning && (
                            <div className="operation-prep-runtime-controls">
                                <span className="operation-prep-label">RUNTIME LOOP（実行中ループ）</span>
                                <ToggleControl disabled={loopDisabled} label="Runtime loop" onChange={handleLoopChange} value={loopChecked} />
                                <span className="operation-prep-label">RUNTIME AUTO TRADE（実行中自動取引）</span>
                                <ToggleControl disabled={autoTradeDisabled} label="Runtime auto trade" onChange={handleAutoTradeChange} value={autoTradeChecked} />
                            </div>
                        )}
                        <DerivedRow label="AUTO SELECTION START" source="DERIVED" value={settings.selectionMode === "AUTO" ? "AUTO MODE → ON START" : "MANUAL MODE"} />
                    </Section>
                </div>
            </div>
                </div>
            </section>
        </div>
    );
}
