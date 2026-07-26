const shown = (value) => (
    value === null || value === undefined || value === "" ? "—" : String(value)
);
const booleanStatus = (value) => (
    value === true ? "ON" : value === false ? "OFF" : "—"
);
const timeStatus = (value) => {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
};
const Fact = ({ label, value, tone = "" }) => (
    <div className={`advisor-runtime__fact ${tone ? `advisor-runtime__fact--${tone}` : ""}`}>
        <dt>{label}</dt>
        <dd>{shown(value)}</dd>
    </div>
);

export default function AdvisorRuntimeStatus({
    data,
    connectionState,
    loading,
    error,
    lastSuccessfulAt,
    onRetry,
}) {
    if (loading && !data) {
        return (
            <section aria-live="polite" className="advisor-runtime">
                <h3>RUNTIME STATUS</h3>
                <p className="advisor-runtime__notice">Loading runtime status…</p>
            </section>
        );
    }

    if (!data) {
        return (
            <section aria-live="polite" className="advisor-runtime">
                <h3>RUNTIME STATUS</h3>
                <div className="advisor-runtime__notice advisor-runtime__notice--error">
                    <strong>Runtime Status Unavailable</strong>
                    <span>{error?.message || "Runtime status could not be loaded."}</span>
                    <span>Retryable: {error?.retryable === true ? "YES" : "NO"}</span>
                    {error?.requestId && <small>Request ID: {error.requestId}</small>}
                    <button aria-label="Retry runtime status" onClick={onRetry} type="button">
                        Retry
                    </button>
                </div>
            </section>
        );
    }

    const warnings = data.warnings.slice(0, 3);
    const degraded = connectionState === "DEGRADED";
    return (
        <section aria-live="polite" className="advisor-runtime">
            <div className="advisor-runtime__title">
                <h3>RUNTIME STATUS</h3>
                <span>{connectionState}</span>
            </div>
            {degraded && (
                <div className="advisor-runtime__notice advisor-runtime__notice--warning">
                    <strong>Showing last known runtime state</strong>
                    <span>{error?.message || "The latest refresh failed."}</span>
                    <button aria-label="Retry runtime status" onClick={onRetry} type="button">
                        Retry
                    </button>
                </div>
            )}
            <div className="advisor-runtime__cards">
                <section>
                    <h4>BOT</h4>
                    <dl>
                        <Fact label="State" value={data.bot.state} />
                        <Fact label="Mode" value={data.bot.mode} />
                        <Fact label="Exchange" value={data.bot.exchange?.toUpperCase()} />
                        <Fact label="Symbol" value={data.bot.symbol} />
                    </dl>
                </section>
                <section>
                    <h4>OPERATION</h4>
                    <dl>
                        <Fact label="Loop Enabled" value={booleanStatus(data.operation.loopEnabled)} />
                        <Fact label="Loop State" value={data.operation.loopState} />
                        <Fact label="Auto Trade" value={booleanStatus(data.operation.autoTradeEnabled)} />
                    </dl>
                </section>
                <section>
                    <h4>SAFETY</h4>
                    <dl>
                        <Fact label="Emergency Locked" value={booleanStatus(data.safety.emergencyLocked)} />
                        <Fact label="Emergency State" value={data.safety.emergencyState} />
                        <Fact label="Dry Run" value={booleanStatus(data.safety.dryRun)} />
                        <Fact
                            label="Real Order Allowed"
                            tone={data.safety.realOrderAllowed === true ? "danger" : "safe"}
                            value={booleanStatus(data.safety.realOrderAllowed)}
                        />
                    </dl>
                </section>
                <section>
                    <h4>CONNECTION / FRESHNESS</h4>
                    <dl>
                        <Fact label="Connection" value={connectionState} />
                        <Fact
                            label="Freshness"
                            tone={data.runtime.freshness === "FRESH" ? "safe" : "warning"}
                            value={data.runtime.freshness}
                        />
                        <Fact label="Captured At" value={timeStatus(data.runtime.capturedAt)} />
                        <Fact label="Source Updated At" value={timeStatus(data.runtime.sourceUpdatedAt)} />
                        <Fact label="Last Successful Fetch" value={timeStatus(lastSuccessfulAt)} />
                    </dl>
                </section>
            </div>
            {data.runtime.freshness === "STALE" && (
                <p className="advisor-runtime__freshness-message">Runtime data is stale.</p>
            )}
            {data.runtime.freshness === "UNKNOWN" && (
                <p className="advisor-runtime__freshness-message">
                    Runtime update time is unavailable.
                </p>
            )}
            {warnings.length > 0 && (
                <div className="advisor-runtime__warnings">
                    <strong>Warnings ({data.warnings.length})</strong>
                    <ul>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
                </div>
            )}
        </section>
    );
}
