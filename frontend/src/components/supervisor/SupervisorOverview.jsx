import { useEffect, useState } from "react";

import {
    deriveProviderConnection,
    getSupervisorProviderStatus,
    llmInterpretationSeverity,
    supervisorCoreSeverity,
} from "../../api/supervisorClient";

function StatusValue({ value, severity }) {
    return (
        <dd className={`supervisor-overview__state supervisor-overview__state--${severity}`}>
            {value}
        </dd>
    );
}

export default function SupervisorOverview() {
    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");

    useEffect(() => {
        let active = true;
        getSupervisorProviderStatus()
            .then((next) => {
                if (active) setStatus(next);
            })
            .catch((failure) => {
                if (active) setError(failure?.message || "Supervisor status is unavailable.");
            })
            .finally(() => {
                if (active) setLoading(false);
            });
        return () => {
            active = false;
        };
    }, []);

    const core = status?.supervisorCore ?? "UNKNOWN";
    const llm = status?.llmStatus ?? "UNKNOWN";
    const operationalEffect = status?.operationalEffect ?? "NONE";
    const provider = status?.provider ?? "UNKNOWN";
    const connection = status ? deriveProviderConnection(status) : "UNKNOWN";

    return (
        <section className="supervisor-overview" aria-labelledby="supervisor-overview-heading">
            <div className="supervisor-overview__heading">
                <p className="supervisor-page__section-kicker">CURRENT STATUS</p>
                <h2 id="supervisor-overview-heading">Overview</h2>
            </div>

            <dl className="supervisor-overview__status">
                <div>
                    <dt>Supervisor Core</dt>
                    <StatusValue value={core} severity={supervisorCoreSeverity(core)} />
                </div>
                <div>
                    <dt>AI Interpretation</dt>
                    <StatusValue value={llm} severity={llmInterpretationSeverity(llm)} />
                </div>
                <div>
                    <dt>Operational Effect</dt>
                    <StatusValue value={operationalEffect} severity={operationalEffect === "NONE" ? "neutral" : "error"} />
                </div>
            </dl>

            <div className="supervisor-overview__explanation">
                <strong>Supervisor</strong>
                {loading && <p>Status Loading…</p>}
                {error && <p role="alert">{error}</p>}
                {!loading && !error && (
                    <>
                        <p>
                            Supervisor Coreは正常稼働。Generative AI Interpretationは現在
                            {llm === "DISABLED" ? " DISABLED（未使用）" : ` ${llm}`}。
                        </p>
                        <p className="supervisor-overview__provider" aria-label={`Provider: ${provider}`}>
                            Provider: {provider} · Connection: {connection}
                        </p>
                    </>
                )}
            </div>
        </section>
    );
}
