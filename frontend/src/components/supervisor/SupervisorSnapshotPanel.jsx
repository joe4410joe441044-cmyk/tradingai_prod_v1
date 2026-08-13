import { useEffect, useState } from "react";

import { getSupervisorSnapshot } from "../../api/supervisorClient";

function DomainLine({ label, value }) {
    const display = value === null || value === undefined || value === "" ? "UNKNOWN" : String(value);
    return (
        <div className="supervisor-snapshot__line">
            <dt>{label}</dt>
            <dd>{display}</dd>
        </div>
    );
}

function DomainState({ label, domain }) {
    const data = domain && typeof domain === "object" ? domain : {};
    return (
        <div className="supervisor-snapshot__domain">
            <h3>{label}</h3>
            <dl className="supervisor-snapshot__lines">
                <DomainLine label="Freshness" value={data.freshness} />
                {Object.entries(data)
                    .filter(([key]) => key !== "freshness" && key !== "evaluatedAt" && key !== "fieldStates" && key !== "source")
                    .map(([key, value]) => (
                        <DomainLine key={key} label={key} value={value} />
                    ))}
            </dl>
        </div>
    );
}

function WarningRow({ warning }) {
    return (
        <li className="supervisor-snapshot__warning">
            <strong>{warning.code ?? "UNKNOWN"}</strong>
            <span>{warning.domain ?? "?"}.{warning.field ?? "?"}</span>
            <p>{warning.message ?? "No message."}</p>
        </li>
    );
}

export default function SupervisorSnapshotPanel() {
    const [snapshot, setSnapshot] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");

    useEffect(() => {
        let active = true;
        getSupervisorSnapshot()
            .then((next) => {
                if (active) setSnapshot(next);
            })
            .catch((failure) => {
                if (active) setError(failure?.message || "Snapshot unavailable.");
            })
            .finally(() => {
                if (active) setLoading(false);
            });
        return () => {
            active = false;
        };
    }, []);

    const warnings = Array.isArray(snapshot?.warnings) ? snapshot.warnings : [];
    const moneyManagement = snapshot?.moneyManagement && typeof snapshot.moneyManagement === "object"
        ? snapshot.moneyManagement
        : {};

    return (
        <section className="supervisor-snapshot" aria-labelledby="supervisor-snapshot-heading">
            <div className="supervisor-snapshot__heading">
                <div>
                    <p className="supervisor-page__section-kicker">READ-ONLY OBSERVATION</p>
                    <h3 id="supervisor-snapshot-heading">Snapshot</h3>
                </div>
                <span className="supervisor-snapshot__meta" aria-label="Snapshot metadata">
                    {snapshot?.capturedAt ? `Captured ${snapshot.capturedAt}` : "Captured UNKNOWN"}
                    {snapshot?.overallFreshness ? ` · ${snapshot.overallFreshness}` : ""}
                </span>
            </div>

            {loading && <p className="supervisor-snapshot__state">Snapshot Loading…</p>}

            {error && <p className="supervisor-snapshot__error" role="alert">Snapshot unavailable: {error}</p>}

            {!loading && !error && (
                <div className="supervisor-snapshot__content">
                    <div className="supervisor-snapshot__domains">
                        <DomainState label="Bot" domain={snapshot?.bot} />
                        <DomainState label="Loop" domain={snapshot?.loop} />
                        <DomainState label="Trade" domain={snapshot?.trade} />
                        <DomainState label="Governance" domain={snapshot?.governance} />
                        <DomainState label="Emergency" domain={snapshot?.emergency} />
                        <DomainState label="Execution" domain={snapshot?.execution} />
                        <DomainState label="Market" domain={snapshot?.market} />
                        <DomainState label="Health" domain={snapshot?.health} />
                    </div>

                    <div className="supervisor-snapshot__mm">
                        <h3>Money Management</h3>
                        <dl className="supervisor-snapshot__lines">
                            <DomainLine label="capitalSource" value={moneyManagement.capitalSource ?? "UNKNOWN"} />
                            <DomainLine label="mmMode" value={moneyManagement.mmMode} />
                            <DomainLine label="executionEntryAllowed" value={moneyManagement.executionEntryAllowed} />
                            <DomainLine label="ruinGuardStatus" value={moneyManagement.ruinGuardStatus} />
                            <DomainLine label="authorityFresh" value={moneyManagement.authorityFresh} />
                        </dl>
                    </div>

                    <div className="supervisor-snapshot__diagnostics">
                        <h3>Diagnostics</h3>
                        {warnings.length === 0 ? (
                            <p className="supervisor-snapshot__state">No warnings.</p>
                        ) : (
                            <ul className="supervisor-snapshot__warnings">
                                {warnings.map((warning, index) => (
                                    <WarningRow key={`${warning.code}-${index}`} warning={warning} />
                                ))}
                            </ul>
                        )}
                    </div>
                </div>
            )}
        </section>
    );
}
