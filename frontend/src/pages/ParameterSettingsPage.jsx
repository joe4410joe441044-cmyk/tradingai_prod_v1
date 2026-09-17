import { useEffect, useRef, useState } from "react";

import usePolling from "../hooks/usePolling";
import { fetchBotStatus } from "../components/runtime/accountRuntimeModel";
import {
    IMPACT_CLASS_LABELS,
    IMPACT_LEGEND,
    IMPACT_TYPE_LABELS,
    LEGACY_RAW_NOTE,
    LEGACY_RAW_PARAMETERS,
    PARAMETER_GROUPS,
    PARAMETER_MAP_FLOW,
    PARAMETER_MAP_NOTES,
    PARAMETER_MAP_OUTSIDE,
    PARAMETER_SETTINGS_SCOPE,
    RELATED_NOTE,
    TUNING_GOALS,
    buildEffectiveRevisionModel,
    buildParameterRows,
    buildRuntimeContext,
    cycleStageLabel,
    guideFor,
    isLiveScope,
    liveMigrationLabel,
    liveMigrationLabelJa,
    presentationFor,
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
    if (!row) return { en: "", ja: "" };
    const guide = guideFor(row.name);
    if (!isLiveScope(scope)) {
        return {
            en: "PAPER — editable on this surface (scope configuration only).",
            ja: "PAPER — この画面で編集可能です（設定スコープのみ）。",
        };
    }
    if (!row.liveLocked) {
        return {
            en: "LIVE — editable on this surface (proven legacy equivalent).",
            ja: "LIVE — この画面で編集可能です（旧実装との等価性が確認済み）。",
        };
    }
    return {
        en: `LIVE — locked / read-only. ${liveMigrationLabel(guide?.liveMigration)}.`,
        ja: `LIVE — ロック中／参照専用。${liveMigrationLabelJa(guide?.liveMigration)}。`,
    };
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
    minimumHoldMs: (
        <>
            <path d="M7 3h10" />
            <path d="M7 21h10" />
            <path d="M8 3c0 4 4 5 4 9s-4 5-4 9" />
            <path d="M16 3c0 4-4 5-4 9s4 5 4 9" />
        </>
    ),
    exitMomentumMinimum: (
        <>
            <polyline points="3 7 9 13 13 10 21 18" />
            <polyline points="15 18 21 18 21 12" />
        </>
    ),
    exitLiquidityQualityMinimum: (
        <>
            <path d="M12 3c3 4 5 6.5 5 9.5A5 5 0 0 1 7 12.5C7 9.5 9 7 12 3z" />
            <line x1="5" y1="20" x2="19" y2="20" />
        </>
    ),
    exitSpreadQualityMinimum: (
        <>
            <path d="M12 4v6" />
            <polyline points="8 10 12 6 16 10" />
            <path d="M5 20l5-6" />
            <path d="M19 20l-5-6" />
        </>
    ),
    momentumMinimumWarmupSeconds: (
        <>
            <path d="M12 3c2 3 4 4 4 7a4 4 0 0 1-8 0c0-1.5.7-2.6 1.6-3.6" />
            <path d="M12 14v7" />
            <path d="M9 21h6" />
        </>
    ),
    absorptionVolumePercentile: (
        <>
            <line x1="5" y1="20" x2="5" y2="12" />
            <line x1="10" y1="20" x2="10" y2="7" />
            <line x1="15" y1="20" x2="15" y2="10" />
            <line x1="20" y1="20" x2="20" y2="4" />
            <line x1="3" y1="20" x2="21" y2="20" />
        </>
    ),
    liquidityQualityPercentile: (
        <>
            <path d="M3 9c3 0 3 2 6 2s3-2 6-2 3 2 6 2" />
            <path d="M3 15c3 0 3 2 6 2s3-2 6-2 3 2 6 2" />
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

const SNAPSHOT_NOTE = {
    en: "Snapshot-at-entry applies to the exit thresholds.",
    ja: "エントリー時スナップショット（snapshot-at-entry）が決済しきい値に適用されます。",
};

function BilingualText({ value, testId, tone }) {
    return (
        <>
            <p
                className={`ps-guide-text ps-guide-text--en${tone ? ` ${tone}` : ""}`}
                data-testid={testId ? `${testId}-en` : undefined}
            >
                <span className="ps-guide-lang" aria-hidden="true">EN</span>
                {value.en}
            </p>
            <p
                className={`ps-guide-text ps-guide-text--ja${tone ? ` ${tone}` : ""}`}
                data-testid={testId ? `${testId}-ja` : undefined}
            >
                <span className="ps-guide-lang" aria-hidden="true">JP</span>
                {value.ja}
            </p>
        </>
    );
}

function GuideField({ title, value, tone }) {
    return (
        <section
            className={`ps-guide-section${tone ? ` ps-guide-section--${tone}` : ""}`}
        >
            <h3>{title}</h3>
            <BilingualText value={value} />
        </section>
    );
}

function ParameterGuideModal({ row, scope, onClose, dialogRef }) {
    if (!row) return null;
    const guide = guideFor(row.name);
    if (!guide) return null;

    const unit = rowUnitDisplay(row, scope);
    const withUnit = (value) => (unit ? `${value} ${unit}` : value);
    const legacyRaw = isLegacyRawRow(row, scope);
    const authority = guideAuthorityText(row, scope);
    const applicationTiming = guide.snapshotAtEntry
        ? {
            en: `${guide.applicationTiming.en} ${SNAPSHOT_NOTE.en}`,
            ja: `${guide.applicationTiming.ja} ${SNAPSHOT_NOTE.ja}`,
        }
        : guide.applicationTiming;

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
                        aria-label="Close parameter guide（パラメーターガイドを閉じる）"
                        onClick={onClose}
                    >
                        ×
                    </button>
                </header>
                <div className="ps-guide-modal__body">
                    <GuideField
                        title="What it controls / 何を設定するか"
                        value={guide.controls}
                    />

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
                            <div
                                className="ps-guide-note"
                                data-testid="guide-legacy-note"
                            >
                                <BilingualText
                                    value={LEGACY_RAW_NOTE}
                                    testId="guide-legacy"
                                />
                            </div>
                        )}
                    </section>

                    <GuideField
                        title="Value meaning / 設定値の意味"
                        value={guide.valueMeaning}
                    />
                    <GuideField
                        title="Increase / 値を上げると"
                        value={guide.increase}
                    />
                    <GuideField
                        title="Decrease / 値を下げると"
                        value={guide.decrease}
                    />
                    <GuideField
                        title="Direct effect / 直接影響"
                        value={guide.directEffect}
                        tone="direct"
                    />
                    <GuideField
                        title="Possible trading effect / 起こり得るトレードへの影響"
                        value={guide.possibleTradingEffect}
                        tone="possible"
                    />

                    <section className="ps-guide-section">
                        <h3>Related parameters / 関連パラメーター</h3>
                        <p className="ps-guide-related">
                            {guide.related.map(relatedLabel).join(" / ")}
                        </p>
                        <BilingualText value={RELATED_NOTE} />
                    </section>

                    <section className="ps-guide-section">
                        <h3>Trading cycle / トレーディングサイクル</h3>
                        <ul className="ps-guide-cycle">
                            {guide.cycleStages.map((stage) => {
                                const label = cycleStageLabel(stage);
                                return (
                                    <li key={stage}>
                                        <strong>Stage {stage}</strong>
                                        <span className="ps-guide-text--en">
                                            {label.en}
                                        </span>
                                        <span className="ps-guide-text--ja">
                                            {label.ja}
                                        </span>
                                    </li>
                                );
                            })}
                        </ul>
                    </section>

                    <GuideField
                        title="Application timing / 適用タイミング"
                        value={applicationTiming}
                    />

                    <section className="ps-guide-section">
                        <h3>Authority / 権限・状態</h3>
                        <BilingualText
                            value={authority}
                            testId="guide-authority"
                        />
                        <div className="ps-guide-note">
                            <BilingualText value={guide.liveAuthorityNote} />
                        </div>
                    </section>
                </div>
            </div>
        </div>
    );
}

function ImpactBadges({ name }) {
    const presentation = presentationFor(name);
    if (!presentation) return null;
    const type = IMPACT_TYPE_LABELS[presentation.impactType];
    const impact = IMPACT_CLASS_LABELS[presentation.impactClass];
    return (
        <div className="ps-card-meta" data-testid={`parameter-impact-${name}`}>
            <span
                className={`ps-meta-badge ps-meta-badge--type ps-meta-badge--${presentation.impactType.toLowerCase()}`}
            >
                {type.en} / {type.ja}
            </span>
            <span
                className={`ps-meta-badge ps-meta-badge--impact ps-meta-badge--${presentation.impactClass.toLowerCase()}`}
            >
                {impact.en} / {impact.ja}
            </span>
            <span
                className="ps-card-meta__direction"
                data-testid={`parameter-direction-${name}`}
            >
                {presentation.directionHint.en} — {presentation.directionHint.ja}
            </span>
        </div>
    );
}

function ParameterCard({
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

            <ImpactBadges name={row.name} />

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

function ParameterChip({ name, onOpenParameter }) {
    const guide = guideFor(name);
    const presentation = presentationFor(name);
    const label = guide ? `${guide.labelEn}（${guide.labelJa}）` : name;
    const type = presentation?.impactType?.toLowerCase() ?? "direct_gate";
    return (
        <button
            type="button"
            className={`ps-map-chip ps-map-chip--${type}`}
            data-testid={`map-chip-${name}`}
            onClick={() => onOpenParameter(name)}
        >
            {label}
        </button>
    );
}

function GroupSection({
    group,
    rows,
    scope,
    draft,
    onDraftChange,
    disabled,
    fieldErrors,
    onOpenGuide,
}) {
    const renderGrid = (parameterNames) => {
        const columns = parameterNames.length <= 2 ? 2 : 3;
        return (
            <div
                className={`ps-param-grid ps-param-grid--cols-${columns}`}
                data-testid={`group-grid-${group.id}`}
            >
                {parameterNames.map((name) => {
                    const row = rows.find((entry) => entry.name === name);
                    if (!row) return null;
                    return (
                        <ParameterCard
                            key={name}
                            row={row}
                            scope={scope}
                            draftValue={draft[name]}
                            onDraftChange={onDraftChange}
                            disabled={disabled}
                            error={fieldErrors[name]}
                            onOpenGuide={onOpenGuide}
                        />
                    );
                })}
            </div>
        );
    };

    const count = group.subgroups
        ? group.subgroups.reduce(
            (total, subgroup) => total + subgroup.parameters.length,
            0,
        )
        : group.parameters.length;

    return (
        <section
            className="semantic-card ps-group"
            data-testid={`group-${group.id}`}
        >
            <header className="semantic-card-header">
                <div>
                    <span className="semantic-card-kicker">
                        Parameter Group（パラメーターグループ）
                    </span>
                    <h2>
                        {group.labelEn}（{group.labelJa}）
                    </h2>
                </div>
                <span
                    className="semantic-badge"
                    data-testid={`group-count-${group.id}`}
                >
                    {count}
                </span>
            </header>
            <p className="ps-group__description">
                <span className="ps-group__desc-en">{group.description.en}</span>
                <span className="ps-group__desc-ja">{group.description.ja}</span>
            </p>
            {group.subgroups
                ? group.subgroups.map((subgroup) => (
                    <div
                        key={subgroup.id}
                        className="ps-subgroup"
                        data-testid={`subgroup-${subgroup.id}`}
                    >
                        <h3 className="ps-subgroup__title">
                            {subgroup.labelEn}（{subgroup.labelJa}）
                        </h3>
                        {renderGrid(subgroup.parameters)}
                    </div>
                ))
                : renderGrid(group.parameters)}
        </section>
    );
}

function ParameterMapModal({ open, onClose, dialogRef, onOpenParameter }) {
    if (!open) return null;
    return (
        <div
            className="ps-guide-backdrop"
            data-testid="map-backdrop"
            onClick={onClose}
        >
            <div
                className="ps-guide-modal ps-map-modal"
                data-testid="map-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="ps-map-title"
                tabIndex={-1}
                ref={dialogRef}
                onClick={(event) => event.stopPropagation()}
            >
                <header className="ps-guide-modal__header">
                    <div>
                        <span className="ps-guide-modal__kicker">
                            Parameter Map（パラメーター全体像）
                        </span>
                        <h2 id="ps-map-title">
                            PARAMETER MAP / パラメーター全体像
                        </h2>
                    </div>
                    <button
                        type="button"
                        className="ps-guide-modal__close"
                        data-testid="map-close"
                        aria-label="Close parameter map（パラメーター全体像を閉じる）"
                        onClick={onClose}
                    >
                        ×
                    </button>
                </header>
                <div className="ps-guide-modal__body">
                    <ol className="ps-map-flow">
                        {PARAMETER_MAP_FLOW.map((step) => (
                            <li
                                key={step.id}
                                className="ps-map-step"
                                data-testid={`map-step-${step.id}`}
                            >
                                <div className="ps-map-step__head">
                                    <strong>{step.labelEn}</strong>
                                    <span className="ps-map-step__ja">
                                        {step.labelJa}
                                    </span>
                                </div>
                                <p className="ps-guide-text ps-guide-text--en">
                                    <span className="ps-guide-lang" aria-hidden="true">EN</span>
                                    {step.note.en}
                                </p>
                                <p className="ps-guide-text ps-guide-text--ja">
                                    <span className="ps-guide-lang" aria-hidden="true">JP</span>
                                    {step.note.ja}
                                </p>
                                {step.chips.length > 0 && (
                                    <div className="ps-map-chips">
                                        {step.chips.map((name) => (
                                            <ParameterChip
                                                key={name}
                                                name={name}
                                                onOpenParameter={onOpenParameter}
                                            />
                                        ))}
                                    </div>
                                )}
                            </li>
                        ))}
                    </ol>

                    <section className="ps-map-notes">
                        <h3>Key relationships / 重要な関係</h3>
                        {PARAMETER_MAP_NOTES.map((note) => (
                            <div
                                key={note.id}
                                className="ps-map-note"
                                data-testid={`map-note-${note.id}`}
                            >
                                <h4>
                                    {note.labelEn} / {note.labelJa}
                                </h4>
                                <p className="ps-guide-text ps-guide-text--en">
                                    <span className="ps-guide-lang" aria-hidden="true">EN</span>
                                    {note.en}
                                </p>
                                <p className="ps-guide-text ps-guide-text--ja">
                                    <span className="ps-guide-lang" aria-hidden="true">JP</span>
                                    {note.ja}
                                </p>
                            </div>
                        ))}
                    </section>

                    <section className="ps-map-outside" data-testid="map-outside">
                        <h3>Not controlled here / ここでは制御しないもの</h3>
                        <ul>
                            {PARAMETER_MAP_OUTSIDE.map((item) => (
                                <li key={item.en}>
                                    <span className="ps-map-outside__en">
                                        {item.en}
                                    </span>
                                    <span className="ps-map-outside__ja">
                                        {item.ja}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    </section>
                </div>
            </div>
        </div>
    );
}

function HowToTuneModal({ open, onClose, dialogRef, onOpenParameter }) {
    if (!open) return null;
    return (
        <div
            className="ps-guide-backdrop"
            data-testid="tune-backdrop"
            onClick={onClose}
        >
            <div
                className="ps-guide-modal ps-tune-modal"
                data-testid="tune-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="ps-tune-title"
                tabIndex={-1}
                ref={dialogRef}
                onClick={(event) => event.stopPropagation()}
            >
                <header className="ps-guide-modal__header">
                    <div>
                        <span className="ps-guide-modal__kicker">
                            How To Tune（目的から調整）
                        </span>
                        <h2 id="ps-tune-title">
                            HOW TO TUNE / 目的から調整
                        </h2>
                    </div>
                    <button
                        type="button"
                        className="ps-guide-modal__close"
                        data-testid="tune-close"
                        aria-label="Close how to tune（目的から調整を閉じる）"
                        onClick={onClose}
                    >
                        ×
                    </button>
                </header>
                <div className="ps-guide-modal__body">
                    <p className="ps-guide-text ps-guide-text--en">
                        <span className="ps-guide-lang" aria-hidden="true">EN</span>
                        Choose a goal to see the affected parameters and direction.
                        These are behavioural directions, not numeric
                        recommendations.
                    </p>
                    <p className="ps-guide-text ps-guide-text--ja">
                        <span className="ps-guide-lang" aria-hidden="true">JP</span>
                        目的を選ぶと、影響するパラメーターと方向が表示されます。
                        これは挙動の方向であり、数値の推奨ではありません。
                    </p>
                    {TUNING_GOALS.map((goal) => (
                        <section
                            key={goal.id}
                            className="ps-tune-goal"
                            data-testid={`tune-goal-${goal.id}`}
                        >
                            <h3>
                                {goal.id}. {goal.titleEn}（{goal.titleJa}）
                            </h3>
                            <p className="ps-guide-text ps-guide-text--en">
                                <span className="ps-guide-lang" aria-hidden="true">EN</span>
                                When to use: {goal.whenEn}
                            </p>
                            <p className="ps-guide-text ps-guide-text--ja">
                                <span className="ps-guide-lang" aria-hidden="true">JP</span>
                                使う場面: {goal.whenJa}
                            </p>
                            <div className="ps-tune-goal__params">
                                <span className="ps-tune-goal__label">
                                    Primary / 主要
                                </span>
                                <div className="ps-map-chips">
                                    {goal.primary.map((name) => (
                                        <ParameterChip
                                            key={name}
                                            name={name}
                                            onOpenParameter={onOpenParameter}
                                        />
                                    ))}
                                </div>
                            </div>
                            {goal.secondary.length > 0 && (
                                <div className="ps-tune-goal__params">
                                    <span className="ps-tune-goal__label">
                                        Secondary / 補助
                                    </span>
                                    <div className="ps-map-chips">
                                        {goal.secondary.map((name) => (
                                            <ParameterChip
                                                key={name}
                                                name={name}
                                                onOpenParameter={onOpenParameter}
                                            />
                                        ))}
                                    </div>
                                </div>
                            )}
                            <p className="ps-guide-text ps-guide-text--en">
                                <span className="ps-guide-lang" aria-hidden="true">EN</span>
                                Direct effect: {goal.directEffect.en}
                            </p>
                            <p className="ps-guide-text ps-guide-text--ja">
                                <span className="ps-guide-lang" aria-hidden="true">JP</span>
                                直接影響: {goal.directEffect.ja}
                            </p>
                            <p className="ps-guide-text ps-guide-text--en">
                                <span className="ps-guide-lang" aria-hidden="true">EN</span>
                                Possible consequence: {goal.possibleConsequence.en}
                            </p>
                            <p className="ps-guide-text ps-guide-text--ja">
                                <span className="ps-guide-lang" aria-hidden="true">JP</span>
                                起こり得る結果: {goal.possibleConsequence.ja}
                            </p>
                            <p className="ps-guide-text ps-guide-text--en">
                                <span className="ps-guide-lang" aria-hidden="true">EN</span>
                                Watch out: {goal.watchOut.en}
                            </p>
                            <p className="ps-guide-text ps-guide-text--ja">
                                <span className="ps-guide-lang" aria-hidden="true">JP</span>
                                注意: {goal.watchOut.ja}
                            </p>
                        </section>
                    ))}
                </div>
            </div>
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
    mapOpen = false,
    tuneOpen = false,
    onOpenMap = () => {},
    onCloseMap = () => {},
    onOpenTune = () => {},
    onCloseTune = () => {},
    onOpenParameter = () => {},
    mapDialogRef = null,
    tuneDialogRef = null,
}) {
    const sources = { configured: configuration, effective, runtime };
    const rows = buildParameterRows(schema, sources);
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
    const aiSummary = `${context.aiDecision} / ${context.aiStatus} / ${context.aiAuthority}`;
    const runtimeRevision = revision.runtimeAvailable
        ? (revision.runtimeRevision ?? "—")
        : "NO_RUNTIME_SNAPSHOT";
    const guideRow = guideKey
        ? (rows.find((row) => row.name === guideKey) ?? null)
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

            {/* TOOLS — compact entry controls for Parameter Map / How To Tune */}
            <section className="ps-tools" data-testid="ps-tools">
                <button
                    type="button"
                    className="ps-tools__button"
                    data-testid="open-parameter-map"
                    onClick={onOpenMap}
                >
                    <span className="ps-tools__title">PARAMETER MAP</span>
                    <span className="ps-tools__sub">パラメーター全体像</span>
                </button>
                <button
                    type="button"
                    className="ps-tools__button"
                    data-testid="open-how-to-tune"
                    onClick={onOpenTune}
                >
                    <span className="ps-tools__title">HOW TO TUNE</span>
                    <span className="ps-tools__sub">目的から調整</span>
                </button>
                <span className="ps-tools__legend" data-testid="impact-legend">
                    <span className="ps-tools__legend-en">
                        {IMPACT_LEGEND.en}
                    </span>
                    <span className="ps-tools__legend-ja">
                        {IMPACT_LEGEND.ja}
                    </span>
                </span>
            </section>

            {/* FUNCTIONAL GROUPS — ENTRY first, then MOMENTUM, EXIT, DETECTOR */}
            {PARAMETER_GROUPS.map((group) => (
                <GroupSection
                    key={group.id}
                    group={group}
                    rows={rows}
                    scope={scope}
                    draft={draft}
                    onDraftChange={onDraftChange}
                    disabled={loading}
                    fieldErrors={fieldErrors}
                    onOpenGuide={onOpenGuide}
                />
            ))}

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
                            <div
                                className="ps-save__error"
                                data-testid="save-invalid"
                            >
                                <span>
                                    {saveState?.backend?.message
                                        ?? "Validation failed. Fix the highlighted values."}
                                </span>
                                {Array.isArray(
                                    saveState?.backend?.validation?.errors,
                                )
                                    && saveState.backend.validation.errors.length > 0 && (
                                    <ul
                                        className="ps-save__validation"
                                        data-testid="save-invalid-details"
                                    >
                                        {saveState.backend.validation.errors.map(
                                            (error, index) => (
                                                <li
                                                    key={`${error?.code ?? "ERROR"}-${error?.parameter ?? index}`}
                                                >
                                                    {error?.parameter
                                                        ? `${error.parameter}: `
                                                        : ""}
                                                    {error?.message
                                                        ?? error?.code
                                                        ?? "invalid value"}
                                                </li>
                                            ),
                                        )}
                                    </ul>
                                )}
                            </div>
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

            {/* PARAMETER MAP MODAL */}
            <ParameterMapModal
                open={mapOpen}
                onClose={onCloseMap}
                dialogRef={mapDialogRef}
                onOpenParameter={onOpenParameter}
            />

            {/* HOW TO TUNE MODAL */}
            <HowToTuneModal
                open={tuneOpen}
                onClose={onCloseTune}
                dialogRef={tuneDialogRef}
                onOpenParameter={onOpenParameter}
            />
        </main>
    );
}

export default function ParameterSettingsPage() {
    const controller = useParameterSettings(PARAMETER_SETTINGS_SCOPE.PAPER);
    const { data } = usePolling(fetchBotStatus, 5000);
    const [liveConfirmationOpen, setLiveConfirmationOpen] = useState(false);
    const [authorityExpanded, setAuthorityExpanded] = useState(false);
    const [guideKey, setGuideKey] = useState(null);
    const [mapOpen, setMapOpen] = useState(false);
    const [tuneOpen, setTuneOpen] = useState(false);
    const guideDialogRef = useRef(null);
    const guideReturnFocusRef = useRef(null);
    const mapDialogRef = useRef(null);
    const tuneDialogRef = useRef(null);

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
    const handleOpenMap = () => setMapOpen(true);
    const handleCloseMap = () => setMapOpen(false);
    const handleOpenTune = () => setTuneOpen(true);
    const handleCloseTune = () => setTuneOpen(false);
    const handleOpenParameter = (name) => {
        // From the Parameter Map / How-To-Tune panels: close them and open
        // the corresponding Guide. Never writes configuration.
        setMapOpen(false);
        setTuneOpen(false);
        setGuideKey(name);
    };

    const anyOverlayOpen = Boolean(guideKey) || mapOpen || tuneOpen;

    // Escape close + focus handling for the Guide / Map / Tune dialogs.
    // Opening or closing them never writes configuration.
    useEffect(() => {
        if (!anyOverlayOpen) return undefined;
        const onKeyDown = (event) => {
            if (event.key === "Escape") {
                event.stopPropagation();
                setGuideKey(null);
                setMapOpen(false);
                setTuneOpen(false);
            }
        };
        document.addEventListener("keydown", onKeyDown);
        const focusTimer = window.setTimeout(() => {
            (
                guideDialogRef.current
                || mapDialogRef.current
                || tuneDialogRef.current
            )?.focus?.();
        }, 0);
        return () => {
            document.removeEventListener("keydown", onKeyDown);
            window.clearTimeout(focusTimer);
            guideReturnFocusRef.current?.focus?.();
        };
    }, [anyOverlayOpen]);

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
            mapOpen={mapOpen}
            tuneOpen={tuneOpen}
            onOpenMap={handleOpenMap}
            onCloseMap={handleCloseMap}
            onOpenTune={handleOpenTune}
            onCloseTune={handleCloseTune}
            onOpenParameter={handleOpenParameter}
            mapDialogRef={mapDialogRef}
            tuneDialogRef={tuneDialogRef}
        />
    );
}
