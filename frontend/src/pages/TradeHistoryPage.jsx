import { useEffect, useState } from "react";

import {
    CONTROL_SOURCE_OPTIONS,
    RESULT_OPTIONS,
    SORT_OPTIONS,
    TRADE_HISTORY_PATH,
    buildParameterSettingsDeeplink,
    buildTradeHistoryQuery,
    buildTradeHistoryViewModel,
    dateInputToEpoch,
    epochToDateInput,
    useTradeHistory,
} from "../features/trade-history";
import { formatTradeTimestamp, formatHoldingDuration } from "../features/parameter-settings/parameterPerformanceModel.js";
import { navigateTo } from "../utils/appNavigation";

const SIDES = ["BUY", "SELL"];
const MODES = ["paper", "live"];

const formatMetric = (value, digits = 2) => (
    typeof value === "number" && Number.isFinite(value)
        ? value.toFixed(digits)
        : "—"
);

function FilterSelect({
    id,
    labelEn,
    labelJa,
    value,
    options,
    onChange,
    testId,
    allowAll = true,
    allLabel = "ALL（すべて）",
}) {
    return (
        <label className="th-filter" htmlFor={id}>
            <span className="th-filter__label">
                {labelEn}
                <small>{labelJa}</small>
            </span>
            <select
                id={id}
                data-testid={testId}
                value={value ?? ""}
                onChange={(event) => onChange(event.target.value)}
            >
                {allowAll && <option value="">{allLabel}</option>}
                {options.map((option) => {
                    const optionValue = (
                        typeof option === "object" ? option.value : option
                    );
                    const optionLabel = (
                        typeof option === "object"
                            ? `${option.labelEn}（${option.labelJa}）`
                            : String(option)
                    );
                    return (
                        <option key={String(optionValue)} value={optionValue}>
                            {optionLabel}
                        </option>
                    );
                })}
            </select>
        </label>
    );
}

function MetricsBar({ metrics }) {
    if (!metrics) return null;
    return (
        <div className="th-metrics" data-testid="trade-history-metrics">
            <span>
                <strong>{metrics.tradeCount ?? 0}</strong>
                Trades（取引数）
            </span>
            <span>
                <strong>{metrics.winCount ?? 0}</strong>
                Win（勝ち）
            </span>
            <span>
                <strong>{metrics.lossCount ?? 0}</strong>
                Loss（負け）
            </span>
            <span>
                <strong>{metrics.breakevenCount ?? 0}</strong>
                Breakeven（損益ゼロ）
            </span>
            <span>
                <strong>{formatMetric(metrics.realizedPnl)}</strong>
                Realized PnL（実現損益）
            </span>
        </div>
    );
}

function TradeDetailPanel({ detail, loading, error, onClose }) {
    const scope = detail?.scope ?? null;
    const revision = (
        Number.isInteger(detail?.effectiveRevision) ? detail.effectiveRevision : null
    );
    const values = detail?.parameterSnapshot;
    return (
        <div
            className="th-detail"
            data-testid="trade-history-detail"
            role="dialog"
            aria-label="Trade detail"
        >
            <header className="th-detail__header">
                <h2>TRADE DETAIL（取引詳細）</h2>
                <button
                    type="button"
                    data-testid="trade-history-detail-close"
                    onClick={onClose}
                >
                    CLOSE（閉じる）
                </button>
            </header>
            {loading && (
                <p data-testid="trade-history-detail-loading">
                    Loading…（読み込み中…）
                </p>
            )}
            {!loading && error && (
                <p
                    className="th-detail__error"
                    data-testid="trade-history-detail-error"
                >
                    Trade detail is unavailable.（取引詳細を取得できません。）
                </p>
            )}
            {!loading && !error && detail && (
                <>
                    <dl className="th-detail__grid">
                        <div><dt>Trade ID</dt><dd>{detail.tradeId ?? "—"}</dd></div>
                        <div><dt>Position</dt><dd>{detail.positionId ?? "—"}</dd></div>
                        <div><dt>Origin / Provenance（由来）</dt><dd>{detail.origin ?? "UNKNOWN"}</dd></div>
                        <div><dt>Entry Time（エントリー時刻）</dt><dd>{formatTradeTimestamp(detail.entryTimestamp)}</dd></div>
                        <div><dt>Entry Price（建値）</dt><dd>{detail.entryPrice ?? "—"}</dd></div>
                        <div><dt>Exit Price（決済価格）</dt><dd>{detail.exitPrice ?? "—"}</dd></div>
                        <div><dt>Quantity（数量）</dt><dd>{detail.quantity ?? "—"}</dd></div>
                        <div><dt>Holding Time（保有時間）</dt><dd>{formatHoldingDuration(detail.holdingMs)}</dd></div>
                        <div><dt>Parameter Context Available（パラメーター情報）</dt><dd>{detail.parameterContextAvailable === true ? "YES" : "NO"}</dd></div>
                        <div><dt>Symbol</dt><dd>{detail.symbol ?? "—"}</dd></div>
                        <div><dt>Side</dt><dd>{detail.side ?? "—"}</dd></div>
                        <div><dt>Scope</dt><dd>{scope ?? "—"}</dd></div>
                        <div><dt>Mode</dt><dd>{detail.mode ?? "—"}</dd></div>
                        <div>
                            <dt>Parameter Revision</dt>
                            <dd>
                                {revision === null || revision === undefined
                                    ? "—"
                                    : `${scope ?? ""} R${revision}`}
                            </dd>
                        </div>
                        <div>
                            <dt>Control Source</dt>
                            <dd>{detail.controlSource ?? "UNKNOWN"}</dd>
                        </div>
                        <div>
                            <dt>Result</dt>
                            <dd data-testid="trade-history-detail-result">
                                {detail.result ?? "UNKNOWN"}
                            </dd>
                        </div>
                        <div>
                            <dt>Realized PnL</dt>
                            <dd>{formatMetric(detail.realizedPnl)}</dd>
                        </div>
                        <div><dt>Exit Reason</dt><dd>{detail.exitReason ?? "—"}</dd></div>
                        <div>
                            <dt>Exit Time</dt>
                            <dd>{formatTradeTimestamp(detail.exitTimestamp)}</dd>
                        </div>
                    </dl>
                    {scope && revision !== null && revision !== undefined && (
                        <button
                            type="button"
                            className="th-detail__link"
                            data-testid="trade-history-open-revision"
                            onClick={() => navigateTo(
                                buildParameterSettingsDeeplink(scope, revision),
                            )}
                        >
                            VIEW PARAMETER REVISION（パラメーターRevisionを表示）
                        </button>
                    )}
                    <section className="th-detail__params">
                        <h3>PARAMETER SNAPSHOT（パラメータースナップショット）</h3>
                        {values && typeof values === "object"
                            && Object.keys(values).length > 0 ? (
                            <ul>
                                {Object.keys(values).sort().map((name) => (
                                    <li key={name}>
                                        <span>{name}</span>
                                        <strong>{String(values[name])}</strong>
                                    </li>
                                ))}
                            </ul>
                        ) : (
                            <p data-testid="trade-history-detail-params-empty">
                                Parameter context unavailable.
                                （パラメーター情報はありません。）
                            </p>
                        )}
                    </section>
                </>
            )}
        </div>
    );
}

export default function TradeHistoryPage() {
    const controller = useTradeHistory(
        typeof window !== "undefined" ? window.location.search : "",
    );
    const view = buildTradeHistoryViewModel({
        data: controller.data,
        loading: controller.loading,
        error: controller.error,
    });
    const [detailRecordId, setDetailRecordId] = useState(null);

    // Deeplink contract: the current filter state is always reflected in the
    // URL so a Trade History view can be shared and reopened.
    useEffect(() => {
        if (typeof window === "undefined") return;
        const query = buildTradeHistoryQuery(controller.filters);
        const url = query ? `${TRADE_HISTORY_PATH}?${query}` : TRADE_HISTORY_PATH;
        window.history.replaceState({}, "", url);
    }, [controller.filters]);

    const handleOpenDetail = (recordId) => {
        if (!recordId) return;
        setDetailRecordId(recordId);
        controller.openDetail(recordId);
    };
    const handleCloseDetail = () => {
        setDetailRecordId(null);
        controller.closeDetail();
    };

    const { filters } = controller;
    const options = controller.data?.options ?? {};
    const revisions = [...new Set([
        ...(options?.revision ?? view.options.revisions),
        ...(Number.isInteger(filters.revision) ? [filters.revision] : []),
    ])].sort((a, b) => a - b);
    const symbols = options?.symbol ?? view.options.symbols;
    const exitReasons = options?.exitReason ?? view.options.exitReasons;

    return (
        <main
            className="mi-page th-page"
            data-testid="trade-history-page"
        >
            <header className="as-page-header th-page__header">
                <div>
                    <span className="as-page-kicker">
                        Canonical Completed Trades（確定した取引）
                    </span>
                    <h1>TRADE HISTORY（取引履歴）</h1>
                </div>
                <button
                    type="button"
                    className="th-page__cross-link"
                    data-testid="trade-history-to-parameter-settings"
                    onClick={() => navigateTo(
                        buildParameterSettingsDeeplink(filters.scope ?? filters.mode?.toUpperCase(), null),
                    )}
                >
                    PARAMETER SETTINGS（パラメーター設定）
                </button>
            </header>

            <p className="th-page__note" data-testid="trade-history-time-authority">
                Period is decided by the EXIT time.
                （期間は決済時刻で判定します。）
                Only Production-eligible canonical trades are shown.
                （本番対象の正規取引のみ表示します。）
            </p>

            <section
                className="th-filters semantic-card"
                data-testid="trade-history-filters"
            >
                <div className="th-filters__row">
                    <FilterSelect
                        id="th-period" labelEn="Period" labelJa="期間（Today: UTC）"
                        value={filters.period} allowAll={false}
                        options={[{value:"today",labelEn:"Today",labelJa:"今日"}, ...["7d","30d","90d"].map(value=>({value,labelEn:value,labelJa:"直近"})), {value:"all",labelEn:"All",labelJa:"全期間"}, {value:"custom",labelEn:"Custom",labelJa:"指定期間"}]}
                        onChange={value => controller.updateFilter("period", value)}
                        testId="th-filter-period"
                    />
                    <FilterSelect
                        id="th-mode"
                        labelEn="Mode"
                        labelJa="モード"
                        value={filters.mode ?? filters.scope?.toLowerCase()}
                        options={MODES}
                        onChange={(value) => controller.updateFilter(
                            "mode", value || null,
                        )}
                        testId="th-filter-mode"
                    />
                    <FilterSelect
                        id="th-symbol"
                        labelEn="Symbol"
                        labelJa="銘柄"
                        value={filters.symbol}
                        options={symbols}
                        onChange={(value) => controller.updateFilter(
                            "symbol", value || null,
                        )}
                        testId="th-filter-symbol"
                    />
                    <FilterSelect
                        id="th-side"
                        labelEn="Side"
                        labelJa="売買"
                        value={filters.side}
                        options={SIDES}
                        onChange={(value) => controller.updateFilter(
                            "side", value || null,
                        )}
                        testId="th-filter-side"
                    />
                    <FilterSelect
                        id="th-result"
                        labelEn="Result"
                        labelJa="結果"
                        value={filters.result}
                        options={RESULT_OPTIONS}
                        onChange={(value) => controller.updateFilter(
                            "result", value || null,
                        )}
                        testId="th-filter-result"
                    />
                    <FilterSelect
                        id="th-revision"
                        labelEn="Revision"
                        labelJa="改訂"
                        value={filters.revision}
                        options={revisions.map((revision) => ({
                            value: revision,
                            labelEn: `R${revision}`,
                            labelJa: `改訂${revision}`,
                        }))}
                        onChange={(value) => controller.updateFilter(
                            "revision", value === "" ? null : Number(value),
                        )}
                        testId="th-filter-revision"
                    />
                    <FilterSelect
                        id="th-exit-reason"
                        labelEn="Exit reason"
                        labelJa="決済理由"
                        value={filters.exitReason}
                        options={exitReasons}
                        onChange={(value) => controller.updateFilter(
                            "exitReason", value || null,
                        )}
                        testId="th-filter-exit-reason"
                    />
                    <FilterSelect
                        id="th-control"
                        labelEn="Control"
                        labelJa="制御"
                        value={filters.controlSource}
                        options={CONTROL_SOURCE_OPTIONS}
                        onChange={(value) => controller.updateFilter(
                            "controlSource", value || null,
                        )}
                        testId="th-filter-control"
                    />
                    {filters.period === "custom" && <>
                    <label className="th-filter" htmlFor="th-from">
                        <span className="th-filter__label">
                            From
                            <small>開始日</small>
                        </span>
                        <input
                            id="th-from"
                            type="date"
                            data-testid="th-filter-from"
                            value={epochToDateInput(filters.fromTimestamp)}
                            onChange={(event) => controller.updateFilter(
                                "fromTimestamp",
                                dateInputToEpoch(event.target.value, false),
                            )}
                        />
                    </label>
                    <label className="th-filter" htmlFor="th-to">
                        <span className="th-filter__label">
                            To
                            <small>終了日</small>
                        </span>
                        <input
                            id="th-to"
                            type="date"
                            data-testid="th-filter-to"
                            value={epochToDateInput(filters.toTimestamp)}
                            onChange={(event) => controller.updateFilter(
                                "toTimestamp",
                                dateInputToEpoch(event.target.value, true),
                            )}
                        />
                    </label>
                    </>}
                    <FilterSelect
                        id="th-sort"
                        labelEn="Sort"
                        labelJa="並び替え"
                        value={filters.sort}
                        options={SORT_OPTIONS}
                        onChange={(value) => controller.setSort(value)}
                        testId="th-filter-sort"
                        allowAll={false}
                    />
                    <label className="th-filter" htmlFor="th-direction">
                        <span className="th-filter__label">
                            Direction
                            <small>順序</small>
                        </span>
                        <select
                            id="th-direction"
                            data-testid="th-filter-direction"
                            value={filters.direction}
                            onChange={(event) => controller.setSort(
                                filters.sort, event.target.value,
                            )}
                        >
                            <option value="desc">DESC（降順）</option>
                            <option value="asc">ASC（昇順）</option>
                        </select>
                    </label>
                    <button
                        type="button"
                        className="th-filters__reset"
                        data-testid="th-filter-reset"
                        onClick={controller.resetFilters}
                    >
                        RESET（リセット）
                    </button>
                </div>
            </section>

            <MetricsBar metrics={view.metrics} />

            {view.loading && (
                <p className="th-state" data-testid="trade-history-loading">
                    Loading…（読み込み中…）
                </p>
            )}

            {!view.loading && view.error && (
                <p
                    className="th-state th-state--error"
                    data-testid="trade-history-error"
                >
                    Trade history is unavailable.（取引履歴を取得できません。）
                </p>
            )}

            {!view.loading && !view.error && !view.available && (
                <p className="th-state" data-testid="trade-history-empty">
                    NO TRADE HISTORY（取引履歴はまだありません）
                </p>
            )}

            {!view.loading && !view.error && view.available && (
                <section className="th-table-wrap semantic-card">
                    <div className="th-table-scroll">
                        <table
                            className="th-table"
                            data-testid="trade-history-table"
                        >
                            <thead>
                                <tr>
                                    <th>Exit Time（決済時刻）</th>
                                    <th>Entry Time（エントリー）</th>
                                    <th>Symbol（銘柄）</th>
                                    <th>Side（売買）</th>
                                    <th>Mode（モード）</th>
                                    <th>Entry Price（建値）</th>
                                    <th>Exit Price（決済価格）</th>
                                    <th>Quantity（数量）</th>
                                    <th>Revision（改訂）</th>
                                    <th>Control（制御）</th>
                                    <th>Result（結果）</th>
                                    <th>PnL（損益）</th>
                                    <th>Holding（保有）</th>
                                    <th>Exit Reason（決済理由）</th>
                                    <th>Detail（詳細）</th>
                                </tr>
                            </thead>
                            <tbody>
                                {view.records.map((row) => (
                                    <tr
                                        key={row.key}
                                        data-testid={`trade-history-row-${row.recordId ?? row.key}`}
                                    >
                                        <td>{row.exitTimeDisplay}</td>
                                        <td>{row.entryTimeDisplay}</td>
                                        <td>{row.symbol}</td>
                                        <td>{row.side}</td>
                                        <td>{row.mode}</td>
                                        <td>{row.entryDisplay}</td>
                                        <td>{row.exitDisplay}</td>
                                        <td>{row.quantityDisplay}</td>
                                        <td>
                                            {row.effectiveRevision === "—"
                                                ? "—"
                                                : `${row.scope} R${row.effectiveRevision}`}
                                        </td>
                                        <td>{row.controlSource}</td>
                                        <td
                                            className={`th-result th-result--${String(row.result).toLowerCase()}`}
                                        >
                                            {row.resultLabel}
                                        </td>
                                        <td>{row.pnlDisplay}</td>
                                        <td>{row.holdingDisplay}</td>
                                        <td>{row.exitReason}</td>
                                        <td>
                                            <button
                                                type="button"
                                                data-testid={`trade-history-open-${row.recordId ?? row.key}`}
                                                onClick={() => handleOpenDetail(
                                                    row.recordId,
                                                )}
                                            >
                                                VIEW（表示）
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>

                    <div
                        className="th-pagination"
                        data-testid="trade-history-pagination"
                    >
                        <span>
                            {view.pagination.rangeStart}–{view.pagination.rangeEnd}
                            {" / "}
                            {view.pagination.total}
                        </span>
                        <button
                            type="button"
                            data-testid="trade-history-prev"
                            disabled={!view.pagination.hasPrevious}
                            onClick={() => controller.setPage(
                                view.pagination.page - 1,
                            )}
                        >
                            PREV（前へ）
                        </button>
                        <span>
                            PAGE {view.pagination.page}
                            {" / "}
                            {Math.max(view.pagination.pageCount, 1)}
                        </span>
                        <button
                            type="button"
                            data-testid="trade-history-next"
                            disabled={!view.pagination.hasNext}
                            onClick={() => controller.setPage(
                                view.pagination.page + 1,
                            )}
                        >
                            NEXT（次へ）
                        </button>
                    </div>
                </section>
            )}

            {detailRecordId && (
                <TradeDetailPanel
                    detail={controller.detail}
                    loading={controller.detailLoading}
                    error={controller.detailError}
                    onClose={handleCloseDetail}
                />
            )}
        </main>
    );
}
