import { useState } from "react";

import {
    OPERATION_PREPARATION_OPTIONS,
    createOperationPreparationSettings,
    deriveOperationReadiness,
    operationPreparationSummary,
} from "./operationPreparationModel";


const percentage = (value) => `${Number(value).toFixed(2)}%`;
const wholePercentage = (value) => `${value}%`;
const leverage = (value) => `${value}x`;
const authoritativeLeverage = (value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? `${parsed}x` : "UNAVAILABLE";
};

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

function DerivedRow({ label, source = "AUTO", status = false, value }) {
    const tone = String(value || "unknown").toLowerCase().replace(/[^a-z]+/g, "-");
    return (
        <div className="operation-prep-derived-row">
            <span>{label}</span>
            <strong className={status ? `operation-prep-status operation-prep-status--${tone}` : ""}>
                {status && <i aria-hidden="true" />}
                {value}
            </strong>
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
    loopStateTone,
    loopPending = false,
    loopDisabled,
    handleLoopChange,
    autoTradeChecked,
    autoTradeStateText,
    autoTradeDisabled,
    autoTradePending = false,
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
    mmDraft = null,
    mmConfiguration = null,
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
    const [settings, setSettings] = useState(() => (
        createOperationPreparationSettings(config)
    ));
     const changeSetting = (key, value) => {
        setSettings((current) => ({ ...current, [key]: value }));
        if (key === "tradingMode") onLegacyConfigChange({ mode: value });
        if (key === "selectionMode") onLegacyConfigChange({ selectionMode: value });
        if (key === "manualSymbol") onLegacyConfigChange({ symbol: value });
        if (key === "loopOnStart") onLegacyConfigChange({ loopOnStart: value });
        if (key === "autoTradeOnStart") onLegacyConfigChange({ autoTradeOnStart: value });
        if (key === "requestedLeverage") onLegacyConfigChange({ leverage: value });
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
        emergencyStateCode && emergencyStateCode !== "UNKNOWN"
            ? emergencyStateCopy[emergencyStateCode]
            : emergencyStateCopy.READY;

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

    const executionMode = config.executionMode
        || (settings.tradingMode === "PAPER" ? "PAPER / SIMULATION" : "NOT CONNECTED");
    const executionSource = config.executionMode ? "RUNTIME" : "UI FALLBACK";
    const realOrderSource = config.realOrderAuthorityKnown ? "RUNTIME" : "UI FALLBACK";

     const {
        reviewReadiness,
        startReady,
        startReadiness,
        entryReady,
        entryReadiness,
        selectionRuntime,
        selectedRuntimeSymbol,
        selectionReadiness,
        emergencyReadiness,
        positionState,
        orderAuthority,
        governanceReadiness,
        executionReadiness,
        mmEntryReadiness,
        mmReadiness,
        mmReadinessSource,
    } = deriveOperationReadiness({
        botRunning,
        tradingMode: settings.tradingMode,
        dryRun: settings.tradingMode === "PAPER",
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
        mmBlockReasons: [],
        mmRecoveryRequired: false,
        mmConfigurationError: Boolean(mmConfigurationError),
        allowLive: config.allowLive,
        tradeMode: config.tradeMode,
    });
    const summary = operationPreparationSummary(settings, selectedRuntimeSymbol, mmDraft?.riskPerTradePercent);
    const maximumLeverage = authoritativeLeverage(mmConfiguration?.maximumLeverage);
    const effectiveLeverage = authoritativeLeverage(
        leverageAuthority?.effectiveLeverage,
    );
    const leverageReason = String(leverageAuthority?.reason || "").trim();
    const effectiveLeverageDisplay = effectiveLeverage === "UNAVAILABLE"
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

    const mmDraftState = mmUpdating
        ? "SAVING"
        : mmConflict
            ? "CONFLICT"
            : mmUpdateError
                ? "UPDATE FAILED"
                : mmDirty
                    ? "UNSAVED CHANGES"
                    : mmAvailable
                        ? "SAVED"
                        : mmLoading
                            ? "LOADING"
                            : "UNAVAILABLE";
    const mmSaveDisabled = !mmAvailable
        || mmUpdating
        || Boolean(mmConflict)
        || Boolean(mmConfigurationError);

    {botRunning && <div className="operation-prep-running-indicator" />}

    const loopValue = loopState ? String(loopState) : summary.loop;
    const loopStatus = botRunning ? loopStateTone !== undefined : false;
    const autoTradeValue = botRunning ? autoTradeStateText : summary.autoTrade;
    const autoTradeStatus = botRunning ? autoTradeStateText.includes("ON") : false;

    return (
        <div className="operation-preparation" data-testid="operation-preparation">

            {/* 三列布局 */}
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
                        </div>
                        {mmUpdateError && <p className="operation-prep-error" role="alert">{mmUpdateError.message ?? "Money Management update failed."}</p>}
                        {mmConfigurationError && <p className="operation-prep-error" role="alert">{mmConfigurationError.message ?? "Money Management configuration unavailable."}</p>}
                        {mmConflict && <p className="operation-prep-error" role="alert">Configuration conflict. Review before saving.</p>}
                        <DerivedRow label="SIZING READINESS" source={mmReadinessSource} value={mmEntryReadiness.label} />
                        <DerivedRow label="MM RUNTIME" source={lifecycleState || mmRuntime || "NOT CONNECTED"} status value={lifecycleState || mmRuntime || "UNKNOWN"} />
                        <a className="operation-prep-link" href="/money-management">Money Management →</a>
                    </Section>
                </div>

                {/* 中列 */}
                <div className="operation-column-center">
                    <Section bodyClassName="operation-prep-section__body--automation" number="4" testId="trade-execution-section" title="TRADE / EXECUTION（取引 / 執行）">
                        <SelectField disabled={controlsDisabled} format={leverage} id="operation-prep-leverage" label="Requested Leverage（要求レバレッジ）" onChange={(value) => changeSetting("requestedLeverage", Number(value))} options={OPERATION_PREPARATION_OPTIONS.requestedLeverage} value={settings.requestedLeverage} />
                        <DerivedRow label="MM Leverage Limit（MMレバレッジ上限）" source={maximumLeverage === "UNAVAILABLE" ? "NOT CONNECTED" : "MM CONFIG"} value={maximumLeverage} />
                        <DerivedRow label="Effective Leverage（有効レバレッジ）" source={effectiveLeverage === "UNAVAILABLE" ? "NOT CONNECTED" : "MM START"} status value={effectiveLeverageDisplay} />
                        <DerivedRow label="Execution（執行）" source={executionSource} value={executionMode} />
                        <DerivedRow label="REAL ORDER" source={realOrderSource} status value={realOrderAllowed ? "BLOCKED" : "DISABLED"} />
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

                    <Section number="6" testId="safety-readiness-section" title="SAFETY / START READINESS（安全性 / 開始準備）">
                        <div className="operation-prep-derived-list operation-prep-derived-list--safety">
                            <DerivedRow label="Emergency（緊急停止）" source="RUNTIME" status value={emergencyReadiness} />
                            <DerivedRow label="Position（ポジション）" source="RUNTIME" status value={positionState} />
                            <DerivedRow label="Pending Order Authority（保留注文権限）" source="RUNTIME" status value={orderAuthority} />
                            <DerivedRow label="Market Selection（市場選択）" source={settings.selectionMode === "MANUAL" ? "OPERATOR" : "RUNTIME"} status value={selectionReadiness} />
                            <DerivedRow label="Money Management（資金管理）" source={mmReadinessSource} status value={mmReadiness} />
                            <DerivedRow label="Governance（ガバナンス）" source="RUNTIME" status value={governanceReadiness} />
                            <DerivedRow label="Execution（執行）" source="RUNTIME" status value={executionReadiness} />
                        </div>
                    </Section>
                </div>

                {/* 右列 */}
                <div className="operation-column-right">
                    <section className="operation-prep-final" data-testid="operation-preparation-summary">
                        <h3 data-testid="final-preparation-heading">FINAL PREPARATION</h3>
                        <div className="operation-prep-summary">
                            <DerivedRow label="MODE" source="OPERATOR" value={summary.mode} />
                            <DerivedRow label="MARKET" source="OPERATOR" value={summary.market} />
                            <DerivedRow label="SYMBOL" source={summary.symbol === "AUTO SELECT" ? "DERIVED" : "OPERATOR"} value={summary.symbol} />
                            <DerivedRow label="RISK / Trade（1取引リスク）" source={mmAvailable ? "MM CONFIG" : "NOT CONNECTED"} value={summary.riskPerTrade} />
                            <DerivedRow label="LEVERAGE" source="OPERATOR" value={summary.requestedLeverage} />
                            <DerivedRow label="LOOP" source={botRunning ? "RUNTIME" : "OPERATOR"} status={loopStatus} value={loopValue} />
                            <DerivedRow label="AUTO TRADE" source={botRunning ? "RUNTIME" : "OPERATOR"} status={autoTradeStatus} value={autoTradeValue} />
                            <DerivedRow label="READINESS" source="UI REVIEW" status value={reviewReadiness} />
                        </div>
                        <div className="operation-prep-start" data-testid="ready-to-start">
                            {botRunning ? null : (
                                <div><span className={`operation-prep-status operation-prep-status--${reviewReadiness}`}><i aria-hidden="true" /></span><strong>{reviewReadiness === "READY" ? "READY TO START" : reviewReadiness === "BLOCKED" ? "BLOCKED" : "WAITING"}</strong></div>
                            )}
                        </div>
                        {botRunning ? null : (
                            <small>Runtime guards remain authoritative. Preview settings are not sent to execution.</small>
                        )}
                        {children}
                    </section>
                </div>
            </div>
        </div>
    );
}
