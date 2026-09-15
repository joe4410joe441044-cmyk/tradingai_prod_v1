import { useState } from "react";

import usePolling from "../hooks/usePolling";
import { fetchBotStatus } from "../components/runtime/accountRuntimeModel";
import {
    PARAMETER_SETTINGS_SCOPE,
    buildAdvancedGroups,
    buildEffectiveRevisionModel,
    buildPrimaryRows,
    buildRuntimeContext,
    isLiveScope,
    useParameterSettings,
} from "../features/parameter-settings";

/* =================================================
   PARAMETER SETTINGS（パラメーター設定）

   Operator-facing configuration surface on top of the canonical strategy
   parameter authority.

   - Runtime Context is READ-ONLY (symbol / timeframe / mode / SL / TP /
     trailing stop are context mirrors only; this page does not own them).
   - AI is READ-ONLY (never fabricated as active).
   - The scope selector changes the configuration scope being viewed/edited;
     it NEVER switches the running bot mode.
   - Exactly one write path: PUT /api/parameter-settings/configuration.

   This page does not start/stop the bot, arm orders, change leverage,
   quantity, symbol or mode.
================================================= */

const CONTEXT_ITEMS = [
    { key: "symbol", label: "Symbol（銘柄）" },
    { key: "timeframe", label: "Timeframe（時間足）" },
    { key: "mode", label: "Mode（モード）" },
    { key: "parameterSetId", label: "Parameter Authority（パラメーター権限）" },
    { key: "scope", label: "Scope（スコープ）" },
    { key: "source", label: "Source（ソース）" },
    { key: "featureContract", label: "Feature Contract（特徴契約）" },
    { key: "sl", label: "SL（損切り）" },
    { key: "tp", label: "TP（利確）" },
    { key: "trailingStop", label: "Trailing Stop（トレーリング）" },
];

function ContextItem({ label, value, testId }) {
    return (
        <div className="ps-context-item" data-testid={testId}>
            <span className="ps-context-item__label">{label}</span>
            <strong className="ps-context-item__value">{value}</strong>
        </div>
    );
}

function ParameterRow({
    row,
    scope,
    draftValue,
    onDraftChange,
    disabled,
    showDetail,
    error,
}) {
    const liveLocked = isLiveScope(scope) && row.liveLocked;
    const editable = row.editable && !disabled && !liveLocked;
    return (
        <div
            className="ps-parameter-row"
            data-testid={`parameter-row-${row.name}`}
        >
            <div className="ps-parameter-row__identity">
                <span className="ps-parameter-row__label">{row.labelEn}</span>
                <span className="ps-parameter-row__label-ja">{row.labelJa}</span>
                {liveLocked && (
                    <span
                        className="ps-parameter-row__lock"
                        data-testid={`parameter-lock-${row.name}`}
                    >
                        LOCKED — LIVE legacy / unmigrated (read-only)
                    </span>
                )}
            </div>
            <div className="ps-parameter-row__configured">
                <input
                    aria-label={`${row.labelEn} configured value`}
                    className="ps-parameter-row__input"
                    data-testid={`parameter-configured-${row.name}`}
                    disabled={!editable}
                    readOnly={!editable}
                    onChange={(event) => (
                        onDraftChange(row.name, event.target.value)
                    )}
                    step="any"
                    type="number"
                    value={draftValue ?? ""}
                />
                <span className="ps-parameter-row__unit">
                    {row.unitSymbol || row.unit}
                </span>
            </div>
            <div
                className="ps-parameter-row__effective"
                data-testid={`parameter-effective-${row.name}`}
            >
                {row.effectiveDisplay}
            </div>
            <div
                className="ps-parameter-row__runtime"
                data-testid={`parameter-runtime-${row.name}`}
            >
                {row.runtimeDisplay}
            </div>
            <div className="ps-parameter-row__status">
                <span
                    className={`ps-status ps-status--${String(row.status).toLowerCase()}`}
                    data-testid={`parameter-status-${row.name}`}
                >
                    {row.status}
                </span>
                <span
                    className="ps-parameter-row__source"
                    data-testid={`parameter-source-${row.name}`}
                >
                    {row.source ?? "—"}
                </span>
            </div>
            {error && (
                <span
                    className="ps-parameter-row__error"
                    data-testid={`parameter-error-${row.name}`}
                >
                    {error}
                </span>
            )}
            {showDetail && (
                <div className="ps-parameter-row__detail">
                    <span>{row.description}</span>
                    <span className="ps-parameter-row__constraint">
                        Range: {row.constraint}
                    </span>
                </div>
            )}
        </div>
    );
}

export function ParameterSettingsView({
    scope = PARAMETER_SETTINGS_SCOPE.PAPER,
    onScopeChange = () => {},
    schema = null,
    configuration = null,
    effective = null,
    runtime = null,
    status = null,
    botStatus = {},
    draft = {},
    onDraftChange = () => {},
    advancedExpanded = false,
    onAdvancedToggle = () => {},
    loading = false,
    saveState = { phase: "IDLE" },
    conflict = null,
    onSave = () => {},
    liveConfirmationOpen = false,
    onRequestLiveSave = () => {},
    onConfirmLive = () => {},
    onCancelLive = () => {},
}) {
    const sources = { configured: configuration, effective, runtime };
    const primaryRows = buildPrimaryRows(schema, sources);
    const advancedGroups = buildAdvancedGroups(schema, sources);
    const context = buildRuntimeContext(botStatus, configuration, runtime);
    const revision = buildEffectiveRevisionModel(
        configuration,
        effective,
        runtime,
    );
    const validation = effective?.validation ?? null;
    const liveScope = isLiveScope(scope);
    const saving = saveState?.phase === "SAVING";
    const fieldErrors = saveState?.fieldErrors ?? {};

    return (
        <main className="mi-page ps-page" data-testid="parameter-settings-page">
            <header className="ps-page__header">
                <div>
                    <span className="ps-page__kicker">
                        Strategy Parameter Authority（戦略パラメーター権限）
                    </span>
                    <h1>PARAMETER SETTINGS（パラメーター設定）</h1>
                </div>
                <span className="ps-page__badge">CONFIGURATION</span>
            </header>

            {/* SCOPE SELECTOR — configuration scope only, never bot mode */}
            <section className="mi-panel ps-scope" data-testid="scope-selector">
                <div className="ps-scope__buttons">
                    {[PARAMETER_SETTINGS_SCOPE.PAPER, PARAMETER_SETTINGS_SCOPE.LIVE].map((value) => (
                        <button
                            key={value}
                            type="button"
                            aria-pressed={scope === value}
                            className={[
                                "ps-scope__button",
                                scope === value ? "ps-scope__button--active" : "",
                            ].filter(Boolean).join(" ")}
                            data-testid={`scope-${value}`}
                            onClick={() => onScopeChange(value)}
                        >
                            {value}
                        </button>
                    ))}
                </div>
                <p className="ps-scope__note" data-testid="scope-note">
                    Scope selector changes which parameter configuration is viewed or edited.
                    It does NOT change the running bot mode.
                    {" "}（このスコープ選択は設定の表示・編集対象を切り替えるだけで、稼働中のボットモードは変更しません。）
                </p>
            </section>

            {/* SECTION A — RUNTIME CONTEXT (READ ONLY) */}
            <section className="mi-panel ps-section" data-testid="runtime-context-section">
                <header className="ps-section__header">
                    <h2>Runtime Context（実行コンテキスト）</h2>
                    <span className="ps-badge ps-badge--readonly">READ ONLY</span>
                </header>
                <div className="ps-context-grid">
                    {CONTEXT_ITEMS.map((item) => (
                        <ContextItem
                            key={item.key}
                            label={item.label}
                            testId={`context-${item.key}`}
                            value={context[item.key]}
                        />
                    ))}
                    <ContextItem
                        label="AI Decision / Review（AI判定/レビュー）"
                        testId="context-ai"
                        value={`${context.aiDecision} / ${context.aiStatus} / ${context.aiAuthority}`}
                    />
                </div>
            </section>

            {/* SECTION B — PRIMARY PARAMETERS */}
            <section className="mi-panel ps-section" data-testid="primary-parameters-section">
                <header className="ps-section__header">
                    <h2>Primary Parameters（主要パラメーター）</h2>
                    <span className="ps-badge" data-testid="primary-count">
                        {primaryRows.length}
                    </span>
                </header>
                <div className="ps-parameter-table" data-testid="primary-parameter-table">
                    <div className="ps-parameter-table__head">
                        <span>Parameter</span>
                        <span>Configured</span>
                        <span>Effective</span>
                        <span>Runtime</span>
                        <span>Status</span>
                    </div>
                    {primaryRows.map((row) => (
                        <ParameterRow
                            key={row.name}
                            row={row}
                            scope={scope}
                            draftValue={draft[row.name]}
                            onDraftChange={onDraftChange}
                            disabled={loading}
                            showDetail={false}
                            error={fieldErrors[row.name]}
                        />
                    ))}
                </div>
            </section>

            {/* SECTION C — ADVANCED PARAMETERS (COLLAPSED BY DEFAULT) */}
            <section className="mi-panel ps-section" data-testid="advanced-parameters-section">
                <header className="ps-section__header">
                    <h2>Advanced Parameters（詳細パラメーター）</h2>
                    <span className="ps-badge" data-testid="advanced-count">
                        {advancedGroups.reduce((total, group) => total + group.rows.length, 0)}
                    </span>
                    <button
                        type="button"
                        className="ps-toggle"
                        data-testid="advanced-toggle"
                        aria-expanded={advancedExpanded}
                        onClick={onAdvancedToggle}
                    >
                        {advancedExpanded ? "COLLAPSE ▲" : "EXPAND ▼"}
                    </button>
                </header>
                {advancedExpanded && (
                    <div className="ps-advanced" data-testid="advanced-parameters-content">
                        {advancedGroups.map((group) => (
                            <div
                                key={group.id}
                                className="ps-advanced-group"
                                data-testid={`advanced-group-${group.id}`}
                            >
                                <h3>
                                    {group.labelEn}（{group.labelJa}）
                                </h3>
                                {group.rows.map((row) => (
                                    <ParameterRow
                                        key={row.name}
                                        row={row}
                                        scope={scope}
                                        draftValue={draft[row.name]}
                                        onDraftChange={onDraftChange}
                                        disabled={loading}
                                        showDetail
                                        error={fieldErrors[row.name]}
                                    />
                                ))}
                            </div>
                        ))}
                    </div>
                )}
            </section>

            {/* SECTION D — EFFECTIVE / REVISION */}
            <section className="mi-panel ps-section" data-testid="effective-revision-section">
                <header className="ps-section__header">
                    <h2>Effective / Revision（有効値・リビジョン）</h2>
                    <span className="ps-badge ps-badge--readonly">READ ONLY</span>
                </header>
                <div className="ps-revision-grid">
                    <div data-testid="revision-configured">
                        <span>Configured revision</span>
                        <strong>{revision.configuredRevision ?? "—"}</strong>
                    </div>
                    <div data-testid="revision-effective">
                        <span>Effective revision</span>
                        <strong>{revision.effectiveRevision ?? "—"}</strong>
                    </div>
                    <div data-testid="revision-runtime">
                        <span>Runtime revision</span>
                        <strong>
                            {revision.runtimeAvailable
                                ? (revision.runtimeRevision ?? "—")
                                : "NO_RUNTIME_SNAPSHOT"}
                        </strong>
                    </div>
                    <div data-testid="revision-scope">
                        <span>Scope</span>
                        <strong>{revision.scope ?? "—"}</strong>
                    </div>
                    <div data-testid="revision-source">
                        <span>Source</span>
                        <strong>{revision.source ?? "—"}</strong>
                    </div>
                    <div data-testid="revision-status">
                        <span>Status</span>
                        <strong>{revision.status ?? "—"}</strong>
                    </div>
                </div>
                {revision.pending && (
                    <p className="ps-pending" data-testid="configured-effective-pending">
                        Configured differs from Effective — status PENDING.
                        The new revision is not yet runtime-effective.
                    </p>
                )}
                {revision.warnings.length > 0 && (
                    <ul className="ps-warnings" data-testid="validation-warnings">
                        {revision.warnings.map((warning, index) => (
                            <li key={`${warning.code}-${index}`}>
                                {warning.parameter ? `${warning.parameter}: ` : ""}
                                {warning.message}
                            </li>
                        ))}
                    </ul>
                )}
                {validation && validation.isValid === false && (
                    <div className="ps-errors" data-testid="validation-errors">
                        {validation.errors.map((error, index) => (
                            <div key={`${error.code}-${index}`}>{error.message}</div>
                        ))}
                    </div>
                )}
            </section>

            {/* SAVE */}
            <section className="mi-panel ps-save" data-testid="save-section">
                <button
                    type="button"
                    className="ps-save__button"
                    data-testid="save-button"
                    disabled={loading || saving}
                    onClick={liveScope ? onRequestLiveSave : onSave}
                >
                    {liveScope ? "SAVE LIVE CONFIGURATION" : "SAVE PAPER CONFIGURATION"}
                </button>
                {saveState?.phase === "SAVING" && (
                    <span data-testid="save-saving">Saving…</span>
                )}
                {saveState?.phase === "SAVED" && (
                    <span data-testid="save-saved">Saved (revision pending).</span>
                )}
                {saveState?.phase === "INVALID" && (
                    <span className="ps-save__error" data-testid="save-invalid">
                        {saveState?.backend?.message
                            ?? "Validation failed. Fix the highlighted values."}
                    </span>
                )}
                {saveState?.phase === "ERROR" && (
                    <span className="ps-save__error" data-testid="save-error">
                        {saveState?.message ?? "Save failed."}
                    </span>
                )}
                {conflict && (
                    <span className="ps-save__error" data-testid="save-conflict">
                        Stale revision ({conflict.configuredRevision}). Reload before saving again.
                    </span>
                )}
                {status && (
                    <span className="ps-save__health" data-testid="authority-health">
                        Authority: {status.status} / {status.scopes?.[scope]?.health ?? "—"}
                    </span>
                )}
            </section>

            {/* LIVE CONFIRMATION */}
            {liveConfirmationOpen && (
                <div className="ps-confirm" data-testid="live-confirmation">
                    <p>
                        Save the LIVE parameter configuration?
                        This changes configuration only. It does not start the bot,
                        arm orders, or change leverage / quantity / symbol / mode.
                    </p>
                    <button
                        type="button"
                        data-testid="live-confirm-button"
                        onClick={onConfirmLive}
                    >
                        CONFIRM LIVE SAVE
                    </button>
                    <button
                        type="button"
                        data-testid="live-cancel-button"
                        onClick={onCancelLive}
                    >
                        CANCEL
                    </button>
                </div>
            )}
        </main>
    );
}

export default function ParameterSettingsPage() {
    const controller = useParameterSettings(PARAMETER_SETTINGS_SCOPE.PAPER);
    const { data } = usePolling(fetchBotStatus, 5000);
    const [advancedExpanded, setAdvancedExpanded] = useState(false);
    const [liveConfirmationOpen, setLiveConfirmationOpen] = useState(false);

    const handleRequestLiveSave = () => setLiveConfirmationOpen(true);
    const handleCancelLive = () => setLiveConfirmationOpen(false);
    const handleConfirmLive = async () => {
        setLiveConfirmationOpen(false);
        await controller.save({ confirmLive: true });
    };

    return (
        <ParameterSettingsView
            scope={controller.scope}
            onScopeChange={controller.setScope}
            schema={controller.schema}
            configuration={controller.configuration}
            effective={controller.effective}
            runtime={controller.runtime}
            status={controller.status}
            botStatus={data?.data}
            draft={controller.draft}
            onDraftChange={controller.changeDraft}
            advancedExpanded={advancedExpanded}
            onAdvancedToggle={() => setAdvancedExpanded((value) => !value)}
            loading={controller.loading}
            saveState={controller.saveState}
            conflict={controller.conflict}
            onSave={() => controller.save()}
            liveConfirmationOpen={liveConfirmationOpen}
            onRequestLiveSave={handleRequestLiveSave}
            onConfirmLive={handleConfirmLive}
            onCancelLive={handleCancelLive}
        />
    );
}
