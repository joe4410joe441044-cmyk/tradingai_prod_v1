import { useEffect, useState } from "react";
import SupervisorActionableUnknown from "./SupervisorActionableUnknown";

import {
    deriveProviderConnection,
    getSupervisorProviderStatus,
    llmInterpretationSeverity,
    supervisorCoreSeverity,
} from "../../api/supervisorClient";

function providerSeverity(provider) {
    if (provider === "DISABLED") return "neutral";
    if (provider === "OPENAI" || provider === "OLLAMA_LOCAL") return "normal";
    return "unknown";
}

function connectionSeverity(connection) {
    if (connection === "CONNECTED") return "normal";
    if (connection === "ENABLED") return "warning";
    return "neutral";
}

function StatusChip({ label, value, severity }) {
    return (
        <span className={`supervisor-statusbar__chip supervisor-statusbar__chip--${severity}`}>
            <span className="supervisor-statusbar__label">{label}</span>
            <span className="supervisor-statusbar__value">{value}</span>
        </span>
    );
}

export default function SupervisorOverview() {
    const [status, setStatus] = useState(null);
    const [error, setError] = useState("");

    useEffect(() => {
        let active = true;
        getSupervisorProviderStatus()
            .then((next) => {
                if (active) setStatus(next);
            })
            .catch((failure) => {
                if (active) setError(failure?.message || "Supervisor status is unavailable.");
            });
        return () => {
            active = false;
        };
    }, []);

    const core = status?.supervisorCore ?? "UNKNOWN";
    const llm = status?.llmStatus ?? "UNKNOWN";
    const provider = status?.provider ?? "UNKNOWN";
    const connection = status ? deriveProviderConnection(status) : "UNKNOWN";
    const effect = status?.operationalEffect ?? "NONE";
    const mode = status?.mode ?? "SHADOW";

    return (
        <section className="supervisor-statusbar" aria-label="Supervisor status">
            <StatusChip label="Core" value={core} severity={supervisorCoreSeverity(core)} />
            <StatusChip label="AI" value={llm} severity={llmInterpretationSeverity(llm)} />
            <StatusChip label="Provider" value={provider} severity={providerSeverity(provider)} />
            <StatusChip label="Connection" value={connection} severity={connectionSeverity(connection)} />
            <StatusChip label="Effect" value={effect} severity={effect === "NONE" ? "neutral" : "error"} />
            <StatusChip label="Mode" value={mode} severity="neutral" />
            {error && <span className="supervisor-statusbar__error" role="alert">{error}</span>}
            {(error || [core, llm, provider, connection].includes("UNKNOWN")) && (
                <SupervisorActionableUnknown item={{
                    subject: "Supervisor status",
                    reason: error || "現在のProvider/Core状態を示す検証済み応答を取得できていません。",
                    missingInformation: "現在の正式なSupervisor Core / AI / Provider接続状態",
                    safeNextStep: "Supervisorの読み取り専用Status表示を再確認し、継続する場合は管理者へ接続状態の確認を依頼してください。",
                    decisionImpact: "未確認の状態を正常と推測せず、AI説明に依存する判断は保留してください。",
                }} />
            )}
        </section>
    );
}
