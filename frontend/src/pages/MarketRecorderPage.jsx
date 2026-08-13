import { useState } from "react";
import {
    useRecorderStatus,
    useRecorderStorage,
    useRecorderArchives,
    useRecorderControl,
    RECORDER_STATUS_STATE,
    RECORDER_CONTROL_STATE,
} from "../features/market-recorder";

var UNKNOWN = "\u2014";

function metricValue(val, fallback) {
    var f = fallback !== undefined ? fallback : UNKNOWN;
    if (val === null || val === undefined) {
        return f;
    }
    return val;
}

export default function MarketRecorderPage() {
    var recorderStatus = useRecorderStatus();
    var recorderStorage = useRecorderStorage();
    var recorderArchives = useRecorderArchives();
    var recorderControl = useRecorderControl(recorderStatus, [recorderStorage, recorderArchives]);

    var status = recorderStatus.data;
    var storage = recorderStorage.data;
    var archives = recorderArchives.data;

    var [diagnosticsOpen, setDiagnosticsOpen] = useState(false);

    var statusClass = status && status.status === RECORDER_STATUS_STATE.RUNNING
        ? "mr-status-badge--running"
        : "mr-status-badge--stopped";

    var renderStatusCard = function () {
        if (recorderStatus.isLoading) {
            return (
                <article className="mi-panel mr-card">
                    <h2 className="mi-panel__title">Recorder Status</h2>
                    <div className="mi-panel__content mr-card__body">
                        <p className="mr-card__placeholder">Loading...</p>
                    </div>
                </article>
            );
        }

        if (recorderStatus.isUnavailable || (recorderStatus.isError && recorderStatus.error?.code === "RECORDER_UNSUPPORTED_SOURCE")) {
            return (
                <article className="mi-panel mr-card">
                    <h2 className="mi-panel__title">Recorder Status</h2>
                    <div className="mi-panel__content mr-card__body">
                        <p className="mr-card__placeholder">Unavailable</p>
                    </div>
                </article>
            );
        }

        if (recorderStatus.isError) {
            return (
                <article className="mi-panel mr-card">
                    <h2 className="mi-panel__title">Recorder Status</h2>
                    <div className="mi-panel__content mr-card__body">
                        <p className="mr-card__placeholder">Error</p>
                    </div>
                </article>
            );
        }

        return (
            <article className="mi-panel mr-card">
                <h2 className="mi-panel__title">Recorder Status</h2>
                <div className="mi-panel__content mr-card__body mr-card__body--content">
                    <span
                        className={[
                            "mi-status-label",
                            "mr-status-badge",
                            statusClass,
                        ].join(" ")}
                    >
                        {status ? status.status : "--"}
                    </span>
                    <dl className="mr-metric-list">
                        <div className="mr-metric-row">
                            <dt>Recording Time</dt>
                            <dd>{metricValue(status?.recordingTime)}</dd>
                        </div>
                        <div className="mr-metric-row">
                            <dt>Exchange</dt>
                            <dd>{metricValue(status?.exchange, "Unknown")}</dd>
                        </div>
                        <div className="mr-metric-row">
                            <dt>Trading Symbols</dt>
                            <dd>{metricValue(status?.symbols, "Not exposed")}</dd>
                        </div>
                        <div className="mr-metric-row">
                            <dt>Event Families</dt>
                            <dd>{metricValue(status?.eventFamilies, "Not exposed")}</dd>
                        </div>
                        <div className="mr-metric-row">
                            <dt>Events/sec</dt>
                            <dd>{metricValue(status?.eventsPerSecond, "Unavailable")}</dd>
                        </div>
                        <div className="mr-metric-row">
                            <dt>Current File</dt>
                            <dd>{metricValue(status?.currentFile)}</dd>
                        </div>
                        <div className="mr-metric-row">
                            <dt>Current File Size</dt>
                            <dd>{metricValue(status?.currentFileSize, "Unavailable")}</dd>
                        </div>
                    </dl>
                </div>
            </article>
        );
    };

    var renderStorageCard = function () {
        if (recorderStorage.isLoading) {
            return (
                <article className="mi-panel mr-card">
                    <h2 className="mi-panel__title">Storage</h2>
                    <div className="mi-panel__content mr-card__body">
                        <p className="mr-card__placeholder">Loading...</p>
                    </div>
                </article>
            );
        }

        if (recorderStorage.isUnavailable || (recorderStorage.isError && recorderStorage.error?.code === "RECORDER_UNSUPPORTED_SOURCE")) {
            return (
                <article className="mi-panel mr-card">
                    <h2 className="mi-panel__title">Storage</h2>
                    <div className="mi-panel__content mr-card__body">
                        <p className="mr-card__placeholder">Unavailable</p>
                    </div>
                </article>
            );
        }

        if (recorderStorage.isError) {
            return (
                <article className="mi-panel mr-card">
                    <h2 className="mi-panel__title">Storage</h2>
                    <div className="mi-panel__content mr-card__body">
                        <p className="mr-card__placeholder">Error</p>
                    </div>
                </article>
            );
        }

        var pct = storage?.usagePercent;
        var hasProgress = pct !== null && pct !== undefined && typeof pct === "number" && Number.isFinite(pct);

        return (
            <article className="mi-panel mr-card">
                <h2 className="mi-panel__title">Storage</h2>
                <div className="mi-panel__content mr-card__body mr-card__body--content">
                    {hasProgress ? (
                        <div className="mr-progress">
                            <div className="mr-progress__bar">
                                <div
                                    className="mr-progress__fill"
                                    style={{ width: Math.min(100, Math.max(0, pct)) + "%" }}
                                />
                            </div>
                            <div className="mr-progress__label">
                                {pct.toFixed(1)}% Used
                            </div>
                        </div>
                    ) : null}
                    <dl className="mr-metric-list">
                        <div className="mr-metric-row">
                            <dt>Used / Total</dt>
                            <dd>
                                <span>{metricValue(storage?.used)}</span>
                                <small>{metricValue(storage?.usedUnit, "")}</small>
                                {" / "}
                                <span>{metricValue(storage?.total)}</span>
                                <small>{metricValue(storage?.totalUnit, "")}</small>
                            </dd>
                        </div>
                        <div className="mr-metric-row">
                            <dt>Usage %</dt>
                            <dd>{hasProgress ? pct.toFixed(1) + "%" : metricValue(null)}</dd>
                        </div>
                        <div className="mr-metric-row">
                            <dt>Runtime Size</dt>
                            <dd>
                                {storage?.runtimeSize !== null && storage?.runtimeSize !== undefined ? (
                                    <>
                                        <span>{storage.runtimeSize}</span>
                                        <small>{metricValue(storage.runtimeSizeUnit, "")}</small>
                                    </>
                                ) : (
                                    <span className="mr-text--muted">Unavailable</span>
                                )}
                            </dd>
                        </div>
                        <div className="mr-metric-row">
                            <dt>Active Recording Size</dt>
                            <dd>
                                {storage?.activeRecordingSize !== null && storage?.activeRecordingSize !== undefined ? (
                                    <>
                                        <span>{storage.activeRecordingSize}</span>
                                        <small>{metricValue(storage.activeRecordingSizeUnit, "")}</small>
                                    </>
                                ) : (
                                    <span className="mr-text--muted">Unavailable</span>
                                )}
                            </dd>
                        </div>
                        <div className="mr-metric-row">
                            <dt>Recorder Size</dt>
                            <dd>
                                <span>{metricValue(storage?.recorderSize)}</span>
                                <small>{metricValue(storage?.recorderSizeUnit, "")}</small>
                            </dd>
                        </div>
                        <div className="mr-metric-row">
                            <dt>Free</dt>
                            <dd>
                                <span>{metricValue(storage?.free)}</span>
                                <small>{metricValue(storage?.freeUnit, "")}</small>
                            </dd>
                        </div>
                    </dl>
                </div>
            </article>
        );
    };

    var renderArchivesCard = function () {
        if (recorderArchives.isLoading) {
            return (
                <article className="mi-panel mr-card">
                    <h2 className="mi-panel__title">Archives</h2>
                    <div className="mi-panel__content mr-card__body">
                        <p className="mr-card__placeholder">Loading...</p>
                    </div>
                </article>
            );
        }

        if (recorderArchives.isUnavailable || (recorderArchives.isError && recorderArchives.error?.code === "RECORDER_UNSUPPORTED_SOURCE")) {
            return (
                <article className="mi-panel mr-card">
                    <h2 className="mi-panel__title">Archives</h2>
                    <div className="mi-panel__content mr-card__body">
                        <p className="mr-card__placeholder">Unavailable</p>
                    </div>
                </article>
            );
        }

        if (recorderArchives.isError) {
            return (
                <article className="mi-panel mr-card">
                    <h2 className="mi-panel__title">Archives</h2>
                    <div className="mi-panel__content mr-card__body">
                        <p className="mr-card__placeholder">Error</p>
                    </div>
                </article>
            );
        }

        if (recorderArchives.isEmpty || !archives || archives.length === 0) {
            return (
                <article className="mi-panel mr-card">
                    <h2 className="mi-panel__title">Archives</h2>
                    <div className="mi-panel__content mr-card__body">
                        <p className="mr-card__placeholder">No archives</p>
                    </div>
                </article>
            );
        }

        return (
            <article className="mi-panel mr-card">
                <h2 className="mi-panel__title">Archives</h2>
                <div className="mi-panel__content mr-card__body mr-card__body--content">
                    <table className="mr-archive-table">
                        <thead>
                            <tr>
                                <th>Date</th>
                                <th>File</th>
                                <th>Compressed Size</th>
                                <th>Status</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            {archives.map(function (archive) {
                                return (
                                    <tr key={archive.id ?? archive.file}>
                                        <td>{metricValue(archive.date)}</td>
                                        <td>{metricValue(archive.file)}</td>
                                        <td className="mr-cell--muted">
                                            {metricValue(archive.compressedSize)}
                                        </td>
                                        <td className={archive.status === "Completed" ? "mr-cell--completed" : archive.status === "Recording" ? "mr-cell--recording" : "mr-cell--muted"}>
                                            {metricValue(archive.status)}
                                        </td>
                                        <td>
                                            <div className="mr-cell--actions">
                                                <button type="button" disabled title="Download API not implemented">
                                                    Download
                                                </button>
                                                <button type="button" disabled title="Replay not yet available">
                                                    Replay
                                                </button>
                                                <button type="button" disabled title="Delete not yet available">
                                                    Delete
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                    <div className="mr-pagination" aria-label="Archive pagination">
                        <button type="button" onClick={recorderArchives.previousPage} disabled={!recorderArchives.hasPreviousPage}>
                            Previous
                        </button>
                        <span>
                            Page {recorderArchives.page} of {Math.max(1, recorderArchives.totalPages)}
                            {recorderArchives.totalCount ? " (" + recorderArchives.totalCount + " archives)" : ""}
                        </span>
                        <button type="button" onClick={recorderArchives.nextPage} disabled={!recorderArchives.hasNextPage}>
                            Next
                        </button>
                    </div>
                </div>
            </article>
        );
    };

    var renderDiagnosticsCard = function () {
        var diagClass = "mr-diagnostics";
        if (!diagnosticsOpen) {
            diagClass += " mr-diagnostics--collapsed";
        }

        return (
            <article className={"mi-panel mr-card " + diagClass}>
                <button
                    type="button"
                    className="mr-diagnostics__toggle"
                    onClick={function () { setDiagnosticsOpen(!diagnosticsOpen); }}
                    aria-expanded={diagnosticsOpen}
                >
                    <span className="mr-diagnostics__toggle-icon">{diagnosticsOpen ? "\u25BC" : "\u25B6"}</span>
                    <h2 className="mi-panel__title">Runtime & Diagnostics</h2>
                </button>
                {diagnosticsOpen ? (
                    <div className="mi-panel__content mr-card__body mr-card__body--content">
                        {recorderStatus.isLoading ? (
                            <p className="mr-card__placeholder">Loading...</p>
                        ) : (
                            <dl className="mr-metric-list">
                                <div className="mr-metric-row">
                                    <dt>Connection State</dt>
                                    <dd>{status?.connectionState !== null && status?.connectionState !== undefined ? status.connectionState : UNKNOWN}</dd>
                                </div>
                                <div className="mr-metric-row">
                                    <dt>Reconnect Count</dt>
                                    <dd>{status?.reconnectCount !== null && status?.reconnectCount !== undefined ? status.reconnectCount : UNKNOWN}</dd>
                                </div>
                                <div className="mr-metric-row">
                                    <dt>Messages Received</dt>
                                    <dd>{metricValue(status?.messagesReceived, "Not exposed")}</dd>
                                </div>
                                <div className="mr-metric-row">
                                    <dt>Bytes Received</dt>
                                    <dd>{metricValue(status?.bytesReceived, "Not exposed")}</dd>
                                </div>
                                <div className="mr-metric-row">
                                    <dt>Sequence Anomalies</dt>
                                    <dd>{metricValue(status?.sequenceAnomalyCount, "Not exposed")}</dd>
                                </div>
                                <div className="mr-metric-row">
                                    <dt>Last Message</dt>
                                    <dd>{metricValue(status?.lastMessageAt, "Not exposed")}</dd>
                                </div>
                                <div className="mr-metric-row">
                                    <dt>Last Error</dt>
                                    <dd className="mr-diag--error">
                                        {status?.lastError !== null && status?.lastError !== undefined ? status.lastError : "None"}
                                    </dd>
                                </div>
                            </dl>
                        )}
                    </div>
                ) : null}
            </article>
        );
    };

    return (
        <main className="mi-page mr-page">
            <article className="mi-panel mr-card mr-card--operation">
                <h2 className="mi-panel__title">Recorder Operation</h2>
                <div className="mi-panel__content mr-card__body mr-card__body--content">
                    <div className="mr-action-row mr-action-row--centered">
                        <button
                            type="button"
                            className="mr-control-button mr-control-button--start"
                            disabled={!recorderControl.canStart}
                            onClick={recorderControl.startRecorder}
                        >
                            {recorderControl.isStarting ? "Starting..." : "START"}
                        </button>
                        <button
                            type="button"
                            className="mr-control-button mr-control-button--stop"
                            disabled={!recorderControl.canStop}
                            onClick={recorderControl.stopRecorder}
                        >
                            {recorderControl.isStopping ? "Stopping..." : "STOP"}
                        </button>
                    </div>
                    {recorderControl.controlError ? (
                        <p className="mr-card__placeholder mr-card__placeholder--error">
                            {recorderControl.controlError.message || "Control operation failed"}
                        </p>
                    ) : null}
                    {recorderControl.controlResult ? (
                        <p className="mr-card__placeholder">
                            {recorderControl.controlResult.operation || "Recorder"}: {recorderControl.controlResult.result || recorderControl.controlResult.status}
                            {recorderControl.controlResult.currentState ? " (" + recorderControl.controlResult.currentState + ")" : ""}
                        </p>
                    ) : null}
                </div>
            </article>

            <section className="mr-overview-grid" aria-label="Recorder overview">
                {renderStatusCard()}

                {renderStorageCard()}
            </section>

            {renderArchivesCard()}

            {renderDiagnosticsCard()}
        </main>
    );
}
