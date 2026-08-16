import { useState } from "react";

import {
    OPERATION_PREPARATION_OPTIONS,
    createOperationPreparationSettings,
    normalizeReadiness,
    operationPreparationSummary,
    pendingOrderReadiness,
    positionReadiness,
} from "./operationPreparationModel";

const percentage = (value) => `${Number(value).toFixed(2)}%`;
const wholePercentage = (value) => `${value}%`;
const leverage = (value) => `${value}x`;

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
}) {
    const [settings, setSettings] = useState(() => (
        createOperationPreparationSettings(config)
    ));
    const changeSetting = (key, value) => {
        setSettings((current) => ({ ...current, [key]: value }));
        if (key === "tradingMode") onLegacyConfigChange({ mode: value });
        if (key === "manualSymbol") onLegacyConfigChange({ symbol: value });
    };

    const selectedRuntimeSymbol = settings.selectionMode === "AUTO"
        && config.displaySymbol
        && !["UNKNOWN", "NOT AVAILABLE"].includes(String(config.displaySymbol).toUpperCase())
        ? config.displaySymbol
        : null;
    const summary = operationPreparationSummary(settings, selectedRuntimeSymbol);
    const selectionRuntime = normalizeReadiness(
        config.autoMarketState,
        ["READY", "RUNNING", "AVAILABLE"],
    );
    const selectionReadiness = settings.selectionMode === "MANUAL"
        ? "READY"
        : selectedRuntimeSymbol
            ? "READY"
            : selectionRuntime === "READY" ? "WAITING" : selectionRuntime;
    const emergencyReadiness = normalizeReadiness(emergencyState, ["READY"]);
    const positionState = positionReadiness(position);
    const orderAuthority = pendingOrderReadiness(pendingOrder);
    const governanceReadiness = normalizeReadiness(
        governanceStatus,
        ["READY", "OK", "ALLOWED", "PASS"],
    );
    const executionReadiness = realOrderAllowed || executionEnabled
        ? "BLOCKED"
        : "SAFE";
    const executionMode = config.executionMode
        || (settings.tradingMode === "PAPER" ? "PAPER / SIMULATION" : "NOT CONNECTED");
    const executionSource = config.executionMode ? "RUNTIME" : "UI FALLBACK";
    const realOrderSource = config.realOrderAuthorityKnown ? "RUNTIME" : "UI FALLBACK";
    const mmReadiness = "WAITING";
    const readinessValues = [
        emergencyReadiness,
        positionState,
        orderAuthority,
        selectionReadiness,
        mmReadiness,
        governanceReadiness,
        executionReadiness,
    ];
    const reviewReadiness = readinessValues.includes("BLOCKED")
        || readinessValues.includes("ERROR")
        ? "BLOCKED"
        : "UI REVIEW READY";
    const controlsDisabled = botRunning === true;

    return (
        <div className="operation-preparation" data-testid="operation-preparation">
            <div className="operation-prep-card-grid">
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
                        disabled={controlsDisabled}
                        format={percentage}
                        id="operation-prep-risk"
                        label="RISK / Trade（1取引リスク）"
                        onChange={(value) => changeSetting("riskPerTrade", Number(value))}
                        options={OPERATION_PREPARATION_OPTIONS.riskPerTrade}
                        value={settings.riskPerTrade}
                    />
                    <DerivedRow label="CAPITAL AUTHORITY" source="UI PREVIEW" value={settings.tradingMode === "PAPER" ? "PAPER ACCOUNT" : "NOT CONNECTED"} />
                    <DerivedRow label="AVAILABLE CAPITAL" source="UI PREVIEW" value="$10,000" />
                    <span className="operation-prep-label">COMPOUNDING</span>
                    <ToggleControl disabled={controlsDisabled} label="Compounding" onChange={(value) => changeSetting("compounding", value)} value={settings.compounding} />
                    <SelectField disabled={controlsDisabled} format={wholePercentage} id="operation-prep-exposure" label="MAX Exposure（最大エクスポージャー）" onChange={(value) => changeSetting("maxExposure", Number(value))} options={OPERATION_PREPARATION_OPTIONS.maxExposure} value={settings.maxExposure} />
                    <SelectField disabled={controlsDisabled} format={wholePercentage} id="operation-prep-drawdown" label="MAX Drawdown（最大ドローダウン）" onChange={(value) => changeSetting("maxDrawdown", Number(value))} options={OPERATION_PREPARATION_OPTIONS.maxDrawdown} value={settings.maxDrawdown} />
                    <DerivedRow label="RISK BUDGET" source="UI PREVIEW" value="$50" />
                    <DerivedRow label="SIZING READINESS" source="UI FALLBACK" status value="WAITING" />
                    <DerivedRow label="MM RUNTIME" source="RUNTIME" status value="UNKNOWN" />
                    <a className="operation-prep-link" href="/money-management">Money Management →</a>
                </Section>

                <Section bodyClassName="operation-prep-section__body--dense" number="4" testId="trade-execution-section" title="TRADE / EXECUTION（取引 / 執行）">
                    <SelectField disabled={controlsDisabled} format={leverage} id="operation-prep-leverage" label="Requested Leverage（要求レバレッジ）" onChange={(value) => changeSetting("requestedLeverage", Number(value))} options={OPERATION_PREPARATION_OPTIONS.requestedLeverage} value={settings.requestedLeverage} />
                    <DerivedRow label="MM Leverage Limit（MMレバレッジ上限）" source="UI PREVIEW" value="5x" />
                    <DerivedRow label="Effective Leverage（有効レバレッジ）" source="UI FALLBACK" value="NOT CONNECTED" />
                    <DerivedRow label="Execution（執行）" source={executionSource} value={executionMode} />
                    <DerivedRow label="REAL ORDER" source={realOrderSource} status value={realOrderAllowed ? "BLOCKED" : "DISABLED"} />
                </Section>

                <Section bodyClassName="operation-prep-section__body--automation" number="5" testId="automation-section" title="AUTOMATION（自動化）">
                    <span className="operation-prep-label">LOOP ON START</span>
                    <ToggleControl disabled={controlsDisabled} label="Loop on start" onChange={(value) => changeSetting("loopOnStart", value)} value={settings.loopOnStart} />
                    <span className="operation-prep-label">AUTO TRADE ON START</span>
                    <ToggleControl disabled={controlsDisabled} label="Auto Trade on start" onChange={(value) => changeSetting("autoTradeOnStart", value)} value={settings.autoTradeOnStart} />
                    <DerivedRow label="AUTO SELECTION START" source="DERIVED" value={settings.selectionMode === "AUTO" ? "AUTO MODE → ON START" : "MANUAL MODE"} />
                </Section>

                <Section number="6" testId="safety-readiness-section" title="SAFETY / START READINESS（安全性 / 開始準備）">
                    <div className="operation-prep-derived-list operation-prep-derived-list--safety">
                        <DerivedRow label="Emergency（緊急停止）" source="RUNTIME" status value={emergencyReadiness} />
                        <DerivedRow label="Position（ポジション）" source="RUNTIME" status value={positionState} />
                        <DerivedRow label="Pending Order Authority（保留注文権限）" source="RUNTIME" status value={orderAuthority} />
                        <DerivedRow label="Market Selection（市場選択）" source={settings.selectionMode === "MANUAL" ? "OPERATOR" : "RUNTIME"} status value={selectionReadiness} />
                        <DerivedRow label="Money Management（資金管理）" source="UI FALLBACK" status value={mmReadiness} />
                        <DerivedRow label="Governance（ガバナンス）" source="RUNTIME" status value={governanceReadiness} />
                        <DerivedRow label="Execution（執行）" source="RUNTIME" status value={executionReadiness} />
                    </div>
                </Section>
            </div>

            <section className="operation-prep-final" data-testid="operation-preparation-summary">
                <h3 data-testid="final-preparation-heading">FINAL PREPARATION</h3>
                <div className="operation-prep-summary">
                    <DerivedRow label="MODE" source="OPERATOR" value={summary.mode} />
                    <DerivedRow label="MARKET" source="OPERATOR" value={summary.market} />
                    <DerivedRow label="SYMBOL" source={summary.symbol === "AUTO SELECT" ? "DERIVED" : "OPERATOR"} value={summary.symbol} />
                    <DerivedRow label="RISK / Trade（1取引リスク）" source="OPERATOR" value={summary.riskPerTrade} />
                    <DerivedRow label="LEVERAGE" source="OPERATOR" value={summary.requestedLeverage} />
                    <DerivedRow label="LOOP" source="OPERATOR" value={summary.loop} />
                    <DerivedRow label="AUTO TRADE" source="OPERATOR" value={summary.autoTrade} />
                    <DerivedRow label="READINESS" source="UI REVIEW" status value={reviewReadiness} />
                </div>
                <div className="operation-prep-start" data-testid="ready-to-start">
                    <div><span className={`operation-prep-status operation-prep-status--${reviewReadiness === "BLOCKED" ? "blocked" : "ready"}`}><i aria-hidden="true" /></span><strong>READY TO START</strong></div>
                    <small>Runtime guards remain authoritative. Preview settings are not sent to execution.</small>
                    {children}
                </div>
            </section>
        </div>
    );
}
