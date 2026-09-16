import { useEffect, useRef, useState } from "react";

import usePolling from "../hooks/usePolling";
import { fetchBotStatus } from "../components/runtime/accountRuntimeModel";
import {
    LEGACY_RAW_PARAMETERS,
    PARAMETER_SETTINGS_SCOPE,
    buildAdvancedGroups,
    buildEffectiveRevisionModel,
    buildPrimaryRows,
    buildRuntimeContext,
    guideFor,
    isLiveScope,
    liveMigrationLabel,
    relatedLabel,
    useParameterSettings,
} from "../features/parameter-settings";

/* =================================================
   PARAMETER SETTINGS（パラメーター設定）

   Operator-facing configuration surface on top of the canonical strategy
   parameter authority.

   Visual language reuses the completed Account Status surface:
   - the page carries the account-runtime-overview token scope and the
     account-status-page card scope, so semantic-card / semantic-metric /
     semantic-badge / as-page-header / as-details-toggle / as-fin-icon are
     inherited rather than re-invented.
   - Primary Parameters are the first content block and the dominant task.
   - Advanced Parameters stay collapsed by default.
   - Runtime Context is READ-ONLY and lives below the editable parameters.
   - AI is READ-ONLY (never fabricated as active).
   - The scope selector changes the configuration scope being viewed/edited;
     it NEVER switches the running bot mode.
   - Exactly one write path: PUT /api/parameter-settings/configuration.
   - Explanations / authority metadata live in a collapsed bottom section.

   This page does not start/stop the bot, arm orders, change leverage,
   quantity, symbol or mode.
================================================= */

const LOCK_LABEL = "LOCKED — LIVE legacy / unmigrated (read-only)";

const CONTEXT_ITEMS = [
    { key: "symbol", label: "Symbol（銘柄）" },
    { key: "timeframe", label: "Timeframe（時間足）" },
    { key: "mode", label: "Mode（モード）" },
    { key: "scope", label: "Scope（スコープ）" },
    { key: "sl", label: "SL（損切り）" },
    { key: "tp", label: "TP（利確）" },
    { key: "trailingStop", label: "Trailing Stop（トレーリング）" },
];

const CONTEXT_META_ITEMS = [
    { key: "parameterSetId", label: "Parameter Authority（パラメーター権限）" },
    { key: "source", label: "Source（ソース）" },
    { key: "featureContract", label: "Feature Contract（特徴契約）" },
];

/* Short unit token for the compact input row. The canonical unit string
   stays available in the row title / constraint; the visible badge stays
   small so the input remains the focus. Normalized percentile ranks carry no
   suffix (0.90 is the 90th percentile, never 0.90 %). */
const shortUnit = (row) => {
    if (row.unitSymbol) return row.unitSymbol;
    const unit = String(row.unit ?? "").toLowerCase();
    if (unit.includes("percentile")) return "";
    if (unit.includes("score")) return "score";
    return "";
};

/* A locked LIVE parameter whose legacy runtime semantic is not proven
   equivalent to the canonical unit must not be shown with a canonical
   suffix. It is presented as legacy raw instead. */
const isLegacyRawRow = (row, scope) => (
    isLiveScope(scope)
    && row.liveLocked
    && LEGACY_RAW_PARAMETERS.includes(row.name)
);

const formatRawValue = (value) => (
    value === null || value === undefined || value === "" ? "—" : String(value)
);

const rowValueDisplay = (row, scope, field) => {
    if (isLegacyRawRow(row, scope)) {
        const raw = field === "effective"
            ? row.effectiveValue
            : field === "runtime"
                ? row.runtimeValue
                : row.configuredValue;
        return formatRawValue(raw);
    }
    if (field === "effective") return row.effectiveDisplay;
    if (field === "runtime") return row.runtimeDisplay;
    return row.configuredDisplay;
};

const rowUnitDisplay = (row, scope) => (
    isLegacyRawRow(row, scope) ? "" : shortUnit(row)
);

const guideAuthorityText = (row, scope) => {
    if (!row) return "";
    const guide = guideFor(row.name);
    if (!isLiveScope(scope)) {
        return "PAPER — editable on this surface (scope configuration only).";
    }
    if (!row.liveLocked) {
        return "LIVE — editable on this surface (proven legacy equivalent).";
    }
    return `LIVE — locked / read-only. ${liveMigrationLabel(guide?.liveMigration)}.`;
};

/* =================================================
   Parameter icons — small inline SVGs, no external asset,
   no emoji, no new dependency. The container reuses the
   Account Status as-fin-icon treatment (blue outline).
================================================= */
const PARAMETER_GLYPHS = {
    minimumCompositeScore: (
        <>
            <circle cx="12" cy="12" r="7" />
            <line x1="12" y1="2" x2="12" y2="6" />
            <line x1="12" y1="18" x2="12" y2="22" />
            <line x1="2" y1="12" x2="6" y2="12" />
            <line x1="18" y1="12" x2="22" y2="12" />
            <circle cx="12" cy="12" r="1.6" />
        </>
    ),
    maximumStrategySpreadPct: (
        <>
            <line x1="4" y1="12" x2="20" y2="12" />
            <polyline points="8 8 4 12 8 16" />
            <polyline points="16 8 20 12 16 16" />
        </>
    ),
    momentumWindowSeconds: (
        <>
            <polyline points="3 17 9 11 13 14 21 6" />
            <polyline points="15 6 21 6 21 12" />
        </>
    ),
    minimumStrategyConfidence: (
        <>
            <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z" />
            <polyline points="9 12 11 14 15 10" />
        </>
    ),
    maximumHoldMs: (
        <>
            <circle cx="12" cy="13" r="8" />
            <polyline points="12 9 12 13 15 15" />
            <line x1="9" y1="2" x2="15" y2="2" />
        </>
    ),
    __fallback: (
        <>
            <circle cx="12" cy="12" r="7" />
            <circle cx="12" cy="12" r="1.6" />
        </>
    ),
};

function ParameterIcon({ name }) {
    return (
        <span
            className="as-fin-icon"
            data-testid={`parameter-icon-${name}`}
        >
            <svg
                viewBox="0 0 24 24"
                width="16"
                height="16"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
            >
                {PARAMETER_GLYPHS[name] ?? PARAMETER_GLYPHS.__fallback}
            </svg>
        </span>
    );
}

function ContextMetric({ label, value, testId }) {
    return (
        <div className="semantic-metric">
            <span className="semantic-metric-label">{label}</span>
            <span
                className="semantic-metric-value tone-connection"
                data-testid={testId}
            >
                {value}
            </span>
        </div>
    );
}

function ParameterGuideModal({ row, scope, onClose, dialogRef }) {
    if (!row) return null;
    const guide = guideFor(row.name);
    if (!guide) return null;

    const unit = rowUnitDisplay(row, scope);
    const withUnit = (value) => (unit ? `${value} ${unit}` : value);
    const legacyRaw = isLegacyRawRow(row, scope);

    return (
        <div
            className="ps-guide-backdrop"
            data-testid="guide-backdrop"
            onClick={onClose}
        >
            <div
                className="ps-guide-modal"
                data-testid="guide-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="ps-guide-title"
                tabIndex={-1}
                ref={dialogRef}
                onClick={(event) => event.stopPropagation()}
            >
                <header className="ps-guide-modal__header">
                    <div>
                        <span className="ps-guide-modal__kicker">
                            Parameter Guide（パラメーターガイド）
                        </span>
                        <h2 id="ps-guide-title" data-testid="guide-title">
                            {guide.labelEn}（{guide.labelJa}）
                        </h2>
                    </div>
                    <button
                        type="button"
                        className="ps-guide-modal__close"
                        data-testid="guide-close"
                        aria-label="Close parameter guide"
                        onClick={onClose}
                    >
                        ×
                    </button>
                </header>
                <div className="ps-guide-modal__body">
                    <section className="ps-guide-section">
                        <h3>What it controls / 何を設定するか</h3>
                        <p>{guide.controls}</p>
                    </section>
                    <section
                        className="ps-guide-section"
                        data-testid="guide-current-values"
                    >
                        <h3>Current values / 現在値</h3>
                        <div className="ps-guide-values">
                            <div data-testid="guide-configured">
                                <span>Configured</span>
                                <strong>
                                    {withUnit(rowValueDisplay(row, scope, "configured"))}
                                </strong>
                            </div>
                            <div data-testid="guide-effective">
                                <span>Effective</span>
                                <strong>
                                    {withUnit(rowValueDisplay(row, scope, "effective"))}
                                </strong>
                            </div>
                            <div data-testid="guide-runtime">
                                <span>Runtime</span>
                                <strong>
                                    {withUnit(rowValueDisplay(row, scope, "runtime"))}
                                </strong>
                            </div>
                        </div>
                        {legacyRaw && (
                            <p
                                className="ps-guide-note"
                                data-testid="guide-legacy-note"
                            >
                                This LIVE value is legacy raw and is not a
                                canonical percent. No unit conversion is
                                applied.
                            </p>
                        )}
                    </section>
                    <section className="ps-guide-section">
                        <h3>Value meaning / 設定値の意味</h3>
                        <p>{guide.valueMeaning}</p>
                    </section>
                    <section className="ps-guide-section">
                        <h3>Increase / 値を上げると</h3>
                        <p>{guide.increase}</p>
                    </section>
                    <section className="ps-guide-section">
                        <h3>Decrease / 値を下げると</h3>
                        <p>{guide.decrease}</p>
                    </section>
                    <section className="ps-guide-section ps-guide-section--direct">
                        <h3>Direct effect / 直接影響</h3>
                        <p>{guide.directEffect}</p>
                    </section>
                    <section className="ps-guide-section ps-guide-section--possible">
                        <h3>Possible trading effect / 起こり得るトレードへの影響</h3>
                        <p>{guide.possibleTradingEffect}</p>
                    </section>
                    <section className="ps-guide-section">
                        <h3>Related parameters / 関連パラメーター</h3>
                        <p>{guide.related.map(relatedLabel).join(" / ")}</p>
                    </section>
                    <section className="ps-guide-section">
                        <h3>Trading cycle / トレーディングサイクル</h3>
                        <p>
                            {guide.cycleStages
                                .map((stage) => `Stage ${stage}`)
                                .join(" · ")}
                        </p>
                    </section>
                    <section className="ps-guide-section">
                        <h3>Application timing / 適用タイミング</h3>
                        <p>
                            {guide.applicationTiming}
                            {guide.snapshotAtEntry
                                ? " Snapshot-at-entry applies to the exit thresholds."
                                : ""}
                        </p>
                    </section>
                    <section className="ps-guide-section">
                        <h3>Authority / 権限・状態</h3>
                        <p data-testid="guide-authority">
                            {guideAuthorityText(row, scope)}
                        </p>
                        <p className="ps-guide-note">
                            {guide.liveAuthorityNote}
                        </p>
                    </section>
                </div>
            </div>
        </div>
    );
}

function PrimaryParameterCard({
    row,
    scope,
    draftValue,
    onDraftChange,
    disabled,
    error,
    onOpenGuide = () => {},
}) {
    const liveLocked = isLiveScope(scope) && row.liveLocked;
    const editable = row.editable && !disabled && !liveLocked;
    const unit = rowUnitDisplay(row, scope);
    const legacyRaw = isLegacyRawRow(row, scope);
    return (
        <article
            className="ps-param-card"
            data-testid={`parameter-row-${row.name}`}
        >
            <header className="ps-param-card__head">
                <ParameterIcon name={row.name} />
                <div className="ps-param-card__titles">
                    <span className="ps-param-card__label">{row.labelEn}</span>
                    <span className="ps-param-card__label-ja">{row.labelJa}</span>
                </div>
                <span
                    className={`ps-status ps-status--${String(row.status).toLowerCase()}`}
                    data-testid={`parameter-status-${row.name}`}
                >
                    {row.status}
                </span>
                <button
                    type="button"
                    className="ps-guide-trigger"
                    data-testid={`parameter-guide-${row.name}`}
                    aria-label={`Open parameter guide for ${row.labelEn}`}
                    onClick={(event) => onOpenGuide(row.name, event.currentTarget)}
                >
                    ? GUIDE
                </button>
            </header>

            <div className="ps-param-card__configured">
                <label
                    className="ps-param-card__field-label"
                    htmlFor={`configured-${row.name}`}
                >
                    Configured
                </label>
                <div className="ps-param-card__input-row">
                    <input
                        aria-label={`${row.labelEn} configured value`}
                        className="ps-param-input"
                        data-testid={`parameter-configured-${row.name}`}
                        disabled={!editable}
                        id={`configured-${row.name}`}
                        readOnly={!editable}
                        onChange={(event) => (
                            onDraftChange(row.name, event.target.value)
                        )}
                        step="any"
                        type="number"
                        value={draftValue ?? ""}
                    />
                    {unit && (
                        <span className="ps-param-card__unit">{unit}</span>
                    )}
                </div>
                {legacyRaw && (
                    <span
                        className="ps-param-card__legacy"
                        data-testid={`parameter-legacy-${row.name}`}
                    >
                        LEGACY RAW — not a canonical percent
                    </span>
                )}
                {liveLocked && (
                    <span
                        className="ps-param-card__lock"
                        data-testid={`parameter-lock-${row.name}`}
                    >
                        {LOCK_LABEL}
                    </span>
                )}
            </div>

            <div className="ps-param-card__readouts">
                <div
                    className="ps-readout"
                    data-testid={`parameter-effective-${row.name}`}
                >
                    <span className="ps-readout__label">Effective</span>
                    <strong className="ps-readout__value">
                        {rowValueDisplay(row, scope, "effective")}
                    </strong>
                </div>
                <div
                    className="ps-readout"
                    data-testid={`parameter-runtime-${row.name}`}
                >
                    <span className="ps-readout__label">Runtime</span>
                    <strong className="ps-readout__value">
                        {rowValueDisplay(row, scope, "runtime")}
                    </strong>
                </div>
            </div>

            {row.source && (
                <span
                    className="ps-param-card__source"
                    data-testid={`parameter-source-${row.name}`}
                >
                    {row.source}
                </span>
            )}
            {error && (
                <span
                    className="ps-param-card__error"
                    data-testid={`parameter-error-${row.name}`}
                >
                    {error}
                </span>
            )}
        </article>
    );
}

function AdvancedParameterRow({
    row,
    scope,
    draftValue,
    onDraftChange,
    disabled,
    error,
    onOpenGuide = () => {},
}) {
    const liveLocked = isLiveScope(scope) && row.liveLocked;
    const editable = row.editable && !disabled && !liveLocked;
    const unit = rowUnitDisplay(row, scope);
    return (
        <div
            className="ps-adv-row"
            data-testid={`parameter-row-${row.name}`}
        >
            <div className="ps-adv-row__identity">
                <span className="ps-adv-row__label">{row.labelEn}</span>
                <span className="ps-adv-row__label-ja">{row.labelJa}</span>
                <span className="ps-adv-row__detail">
                    {row.description} · Range: {row.constraint}
                </span>
                {liveLocked && (
                    <span
                        className="ps-adv-row__lock"
                        data-testid={`parameter-lock-${row.name}`}
                    >
                        {LOCK_LABEL}
                    </span>
                )}
            </div>
            <div className="ps-adv-row__configured">
                <input
                    aria-label={`${row.labelEn} configured value`}
                    className="ps-param-input ps-param-input--sm"
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
                {unit && (
                    <span className="ps-param-card__unit">{unit}</span>
                )}
            </div>
            <div
                className="ps-adv-row__value"
                data-testid={`parameter-effective-${row.name}`}
            >
                {rowValueDisplay(row, scope, "effective")}
            </div>
            <div
                className="ps-adv-row__value"
                data-testid={`parameter-runtime-${row.name}`}
            >
                {rowValueDisplay(row, scope, "runtime")}
            </div>
            <div className="ps-adv-row__status">
                <span
                    className={`ps-status ps-status--${String(row.status).toLowerCase()}`}
                    data-testid={`parameter-status-${row.name}`}
                >
                    {row.status}
                </span>
                <button
                    type="button"
                    className="ps-guide-trigger ps-guide-trigger--sm"
                    data-testid={`parameter-guide-${row.name}`}
                    aria-label={`Open parameter guide for ${row.labelEn}`}
                    onClick={(event) => onOpenGuide(row.name, event.currentTarget)}
                >
                    ? GUIDE
                </button>
            </div>
            {error && (
                <span
                    className="ps-param-card__error"
                    data-testid={`parameter-error-${row.name}`}
                >
                    {error}
                </span>
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
    authorityExpanded = false,
    onAuthorityToggle = () => {},
    guideKey = null,
    onOpenGuide = () => {},
    onCloseGuide = () => {},
    guideDialogRef = null,
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
    const advancedCount = advancedGroups.reduce(
        (total, group) => total + group.rows.length,
        0,
    );
    const aiSummary = `${context.aiDecision} / ${context.aiStatus} / ${context.aiAuthority}`;
    const runtimeRevision = revision.runtimeAvailable
        ? (revision.runtimeRevision ?? "—")
        : "NO_RUNTIME_SNAPSHOT";
    const guideRow = guideKey
        ? (
            [...primaryRows, ...advancedGroups.flatMap((group) => group.rows)]
                .find((row) => row.name === guideKey) ?? null
        )
        : null;

    return (
        <main
            className="mi-page ps-page account-status-page account-runtime-overview"
            data-testid="parameter-settings-page"
        >
            {/* COMPACT HEADER */}
            <header className="as-page-header ps-page__header">
                <div>
                    <span className="as-page-kicker">
                        Strategy Parameter Authority（戦略パラメーター権限）
                    </span>
                    <h1>PARAMETER SETTINGS（パラメーター設定）</h1>
                </div>
                <span className="as-page-badge">CONFIGURATION</span>
            </header>

            {/* SCOPE SELECTOR — configuration scope only, never bot mode */}
            <section className="ps-scope" data-testid="scope-selector">
                <span className="ps-scope__hint">
                    Configuration Scope（設定スコープ）
                </span>
                <div
                    className="ps-scope__buttons"
                    role="group"
                    aria-label="Configuration scope"
                >
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
                <span className="ps-scope__note" data-testid="scope-note">
                    Configuration scope only — does not change the running bot
                    mode.
                </span>
            </section>

            {/* PRIMARY PARAMETERS — dominant task */}
            <section
                className="semantic-card semantic-card-paper ps-section"
                data-testid="primary-parameters-section"
            >
                <header className="semantic-card-header">
                    <div>
                        <span className="semantic-card-kicker">
                            Core strategy thresholds（中核戦略しきい値）
                        </span>
                        <h2>Primary Parameters（主要パラメーター）</h2>
                    </div>
                    <span
                        className="semantic-badge"
                        data-testid="primary-count"
                    >
                        {primaryRows.length}
                    </span>
                </header>
                <div
                    className="ps-param-grid"
                    data-testid="primary-parameter-table"
                >
                    {primaryRows.map((row) => (
                        <PrimaryParameterCard
                            key={row.name}
                            row={row}
                            scope={scope}
                            draftValue={draft[row.name]}
                            onDraftChange={onDraftChange}
                            disabled={loading}
                            error={fieldErrors[row.name]}
                            onOpenGuide={onOpenGuide}
                        />
                    ))}
                </div>
            </section>

            {/* ADVANCED PARAMETERS — collapsed by default */}
            <section
                className="semantic-card ps-section"
                data-testid="advanced-parameters-section"
            >
                <header className="semantic-card-header">
                    <div>
                        <span className="semantic-card-kicker">
                            Secondary tuning（補助チューニング）
                        </span>
                        <h2>Advanced Parameters（詳細パラメーター）</h2>
                    </div>
                    <span
                        className="semantic-badge"
                        data-testid="advanced-count"
                    >
                        {advancedCount}
                    </span>
                    <button
                        type="button"
                        className="as-details-toggle"
                        data-testid="advanced-toggle"
                        aria-expanded={advancedExpanded}
                        onClick={onAdvancedToggle}
                    >
                        {advancedExpanded ? "COLLAPSE ▲" : "EXPAND ▼"}
                    </button>
                </header>
                {advancedExpanded && (
                    <div
                        className="ps-advanced"
                        data-testid="advanced-parameters-content"
                    >
                        <div className="ps-adv-head" aria-hidden="true">
                            <span>Parameter</span>
                            <span>Configured</span>
                            <span>Effective</span>
                            <span>Runtime</span>
                            <span>Status</span>
                        </div>
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
                                    <AdvancedParameterRow
                                        key={row.name}
                                        row={row}
                                        scope={scope}
                                        draftValue={draft[row.name]}
                                        onDraftChange={onDraftChange}
                                        disabled={loading}
                                        error={fieldErrors[row.name]}
                                        onOpenGuide={onOpenGuide}
                                    />
                                ))}
                            </div>
                        ))}
                    </div>
                )}
            </section>

            {/* LOWER: EFFECTIVE / REVISION + RUNTIME CONTEXT (READ ONLY) */}
            <div className="ps-lower-grid">
                <section
                    className="semantic-card semantic-card-execution ps-section"
                    data-testid="effective-revision-section"
                >
                    <header className="semantic-card-header">
                        <div>
                            <span className="semantic-card-kicker">
                                Promotion state（昇格状態）
                            </span>
                            <h2>Effective / Revision（有効値・リビジョン）</h2>
                        </div>
                        <span className="semantic-badge">READ ONLY</span>
                    </header>
                    <div className="semantic-metric-grid three-columns ps-revision-grid">
                        <div
                            className="semantic-metric"
                            data-testid="revision-configured"
                        >
                            <span className="semantic-metric-label">
                                Configured revision
                            </span>
                            <span className="semantic-metric-value">
                                {revision.configuredRevision ?? "—"}
                            </span>
                        </div>
                        <div
                            className="semantic-metric"
                            data-testid="revision-effective"
                        >
                            <span className="semantic-metric-label">
                                Effective revision
                            </span>
                            <span className="semantic-metric-value">
                                {revision.effectiveRevision ?? "—"}
                            </span>
                        </div>
                        <div
                            className="semantic-metric"
                            data-testid="revision-runtime"
                        >
                            <span className="semantic-metric-label">
                                Runtime revision
                            </span>
                            <span className="semantic-metric-value">
                                {runtimeRevision}
                            </span>
                        </div>
                        <div
                            className="semantic-metric"
                            data-testid="revision-scope"
                        >
                            <span className="semantic-metric-label">Scope</span>
                            <span className="semantic-metric-value tone-paper">
                                {revision.scope ?? "—"}
                            </span>
                        </div>
                        <div
                            className="semantic-metric"
                            data-testid="revision-source"
                        >
                            <span className="semantic-metric-label">Source</span>
                            <span className="semantic-metric-value">
                                {revision.source ?? "—"}
                            </span>
                        </div>
                        <div
                            className="semantic-metric"
                            data-testid="revision-status"
                        >
                            <span className="semantic-metric-label">Status</span>
                            <span className="semantic-metric-value">
                                {revision.status ?? "—"}
                            </span>
                        </div>
                    </div>
                    {revision.pending && (
                        <p
                            className="ps-pending"
                            data-testid="configured-effective-pending"
                        >
                            Configured differs from Effective — status PENDING.
                            The new revision is not yet runtime-effective.
                        </p>
                    )}
                    {revision.warnings.length > 0 && (
                        <ul
                            className="ps-warnings"
                            data-testid="validation-warnings"
                        >
                            {revision.warnings.map((warning, index) => (
                                <li key={`${warning.code}-${index}`}>
                                    {warning.parameter ? `${warning.parameter}: ` : ""}
                                    {warning.message}
                                </li>
                            ))}
                        </ul>
                    )}
                    {validation && validation.isValid === false && (
                        <div
                            className="ps-errors"
                            data-testid="validation-errors"
                        >
                            {validation.errors.map((error, index) => (
                                <div key={`${error.code}-${index}`}>
                                    {error.message}
                                </div>
                            ))}
                        </div>
                    )}
                </section>

                <section
                    className="semantic-card semantic-card-connection ps-section"
                    data-testid="runtime-context-section"
                >
                    <header className="semantic-card-header">
                        <div>
                            <span className="semantic-card-kicker">
                                Read-only mirror（参照専用ミラー）
                            </span>
                            <h2>Runtime Context（実行コンテキスト）</h2>
                        </div>
                        <span className="semantic-badge">READ ONLY</span>
                    </header>
                    <div className="semantic-metric-grid ps-context-grid">
                        {CONTEXT_ITEMS.map((item) => (
                            <ContextMetric
                                key={item.key}
                                label={item.label}
                                testId={`context-${item.key}`}
                                value={context[item.key]}
                            />
                        ))}
                        <ContextMetric
                            label="AI Decision / Review（AI判定/レビュー）"
                            testId="context-ai"
                            value={aiSummary}
                        />
                    </div>
                    <div className="ps-context-meta">
                        {CONTEXT_META_ITEMS.map((item) => (
                            <div
                                key={item.key}
                                className="ps-context-meta__item"
                                data-testid={`context-${item.key}`}
                            >
                                <span className="ps-context-meta__label">
                                    {item.label}
                                </span>
                                <span className="ps-context-meta__value">
                                    {context[item.key]}
                                </span>
                            </div>
                        ))}
                    </div>
                    <p className="ps-context-note">
                        Runtime Context is a read-only mirror. This page does
                        not own symbol, timeframe, mode, SL, TP or trailing
                        stop.
                        {" "}（実行コンテキストは参照専用です。この画面は銘柄・時間足・モード・SL・TP・トレーリングを所有しません。）
                    </p>
                </section>
            </div>

            {/* SAVE ACTION */}
            <section
                className="semantic-card ps-save"
                data-testid="save-section"
            >
                <div className="ps-save__body">
                    <div className="ps-save__info">
                        {saveState?.phase === "SAVING" && (
                            <span data-testid="save-saving">Saving…</span>
                        )}
                        {saveState?.phase === "SAVED" && (
                            <span data-testid="save-saved">
                                Saved (revision pending).
                            </span>
                        )}
                        {saveState?.phase === "INVALID" && (
                            <span
                                className="ps-save__error"
                                data-testid="save-invalid"
                            >
                                {saveState?.backend?.message
                                    ?? "Validation failed. Fix the highlighted values."}
                            </span>
                        )}
                        {saveState?.phase === "ERROR" && (
                            <span
                                className="ps-save__error"
                                data-testid="save-error"
                            >
                                {saveState?.message ?? "Save failed."}
                            </span>
                        )}
                        {conflict && (
                            <span
                                className="ps-save__error"
                                data-testid="save-conflict"
                            >
                                {`Stale revision (${conflict.configuredRevision}). Reload before saving again.`}
                            </span>
                        )}
                        {status && (
                            <span
                                className="ps-save__health"
                                data-testid="authority-health"
                            >
                                Authority: {status.status} / {status.scopes?.[scope]?.health ?? "—"}
                            </span>
                        )}
                    </div>
                    <button
                        type="button"
                        className="ps-save__button"
                        data-testid="save-button"
                        disabled={loading || saving}
                        onClick={liveScope ? onRequestLiveSave : onSave}
                    >
                        {liveScope
                            ? "SAVE LIVE CONFIGURATION"
                            : "SAVE PAPER CONFIGURATION"}
                    </button>
                </div>
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
                        className="ps-confirm__primary"
                        data-testid="live-confirm-button"
                        onClick={onConfirmLive}
                    >
                        CONFIRM LIVE SAVE
                    </button>
                    <button
                        type="button"
                        className="ps-confirm__secondary"
                        data-testid="live-cancel-button"
                        onClick={onCancelLive}
                    >
                        CANCEL
                    </button>
                </div>
            )}

            {/* AUTHORITY / EXPLANATIONS — collapsed by default, bottom */}
            <section
                className="semantic-card ps-authority"
                data-testid="authority-details-section"
            >
                <header className="semantic-card-header">
                    <div>
                        <span className="semantic-card-kicker">
                            Reference（参照）
                        </span>
                        <h2>Parameter Authority（この画面について）</h2>
                    </div>
                    <button
                        type="button"
                        className="as-details-toggle"
                        data-testid="authority-details-toggle"
                        aria-expanded={authorityExpanded}
                        onClick={onAuthorityToggle}
                    >
                        {authorityExpanded ? "CLOSE ▲" : "DETAILS ▼"}
                    </button>
                </header>
                {authorityExpanded && (
                    <div
                        className="ps-authority__content"
                        data-testid="authority-details-content"
                    >
                        <section>
                            <h3>Configuration scope（設定スコープ）</h3>
                            <p>
                                PAPER / LIVE selects which parameter
                                configuration is viewed or edited. It does NOT
                                change the running bot mode.
                            </p>
                        </section>
                        <section>
                            <h3>Configured / Effective / Runtime</h3>
                            <ul>
                                <li>
                                    Configured — the editable operator value
                                    written by Save.
                                </li>
                                <li>
                                    Effective — the currently promoted
                                    parameter value from the canonical
                                    authority.
                                </li>
                                <li>
                                    Runtime — the actual snapshot captured when
                                    a position was entered. When no snapshot
                                    exists it shows an explicit unavailable
                                    state; it is never fabricated from
                                    Configured.
                                </li>
                            </ul>
                        </section>
                        <section>
                            <h3>Promotion（昇格）</h3>
                            <p>
                                Save writes a new configured revision. The
                                effective revision is promoted by the backend
                                authority; until promotion completes the status
                                is PENDING and the value is not yet
                                runtime-effective.
                            </p>
                        </section>
                        <section>
                            <h3>Snapshot-at-entry（エントリー時スナップショット）</h3>
                            <p>
                                Runtime parameters are captured at entry.
                                Changing a parameter while a position is open
                                does not alter that position's captured runtime
                                values.
                            </p>
                        </section>
                        <section>
                            <h3>Technical authority（技術的権限）</h3>
                            <p>
                                Parameter Authority, Source and Feature
                                Contract identify the canonical parameter set
                                and the feature contract version. They are
                                read-only references for this surface.
                            </p>
                        </section>
                    </div>
                )}
            </section>

            {/* PARAMETER GUIDE MODAL — one reusable component for all 12 */}
            <ParameterGuideModal
                row={guideRow}
                scope={scope}
                onClose={onCloseGuide}
                dialogRef={guideDialogRef}
            />
        </main>
    );
}

export default function ParameterSettingsPage() {
    const controller = useParameterSettings(PARAMETER_SETTINGS_SCOPE.PAPER);
    const { data } = usePolling(fetchBotStatus, 5000);
    const [advancedExpanded, setAdvancedExpanded] = useState(false);
    const [liveConfirmationOpen, setLiveConfirmationOpen] = useState(false);
    const [authorityExpanded, setAuthorityExpanded] = useState(false);
    const [guideKey, setGuideKey] = useState(null);
    const guideDialogRef = useRef(null);
    const guideReturnFocusRef = useRef(null);

    const handleRequestLiveSave = () => setLiveConfirmationOpen(true);
    const handleCancelLive = () => setLiveConfirmationOpen(false);
    const handleConfirmLive = async () => {
        setLiveConfirmationOpen(false);
        await controller.save({ confirmLive: true });
    };

    const handleOpenGuide = (name, trigger) => {
        guideReturnFocusRef.current = trigger ?? null;
        setGuideKey(name);
    };
    const handleCloseGuide = () => setGuideKey(null);

    // Escape close + focus handling for the Parameter Guide dialog. Opening or
    // closing the guide never writes configuration.
    useEffect(() => {
        if (!guideKey) return undefined;
        const onKeyDown = (event) => {
            if (event.key === "Escape") {
                event.stopPropagation();
                setGuideKey(null);
            }
        };
        document.addEventListener("keydown", onKeyDown);
        const focusTimer = window.setTimeout(() => {
            guideDialogRef.current?.focus?.();
        }, 0);
        return () => {
            document.removeEventListener("keydown", onKeyDown);
            window.clearTimeout(focusTimer);
            guideReturnFocusRef.current?.focus?.();
        };
    }, [guideKey]);

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
            authorityExpanded={authorityExpanded}
            onAuthorityToggle={() => setAuthorityExpanded((value) => !value)}
            guideKey={guideKey}
            onOpenGuide={handleOpenGuide}
            onCloseGuide={handleCloseGuide}
            guideDialogRef={guideDialogRef}
        />
    );
}
