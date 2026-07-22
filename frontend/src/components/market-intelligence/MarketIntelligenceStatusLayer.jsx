import { REPLAY_ENGINE_COMMANDS } from "../../features/market-intelligence/replay/replayEngine.js";
import { useMarketIntelligence } from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";

const stateModel = (engine) => {
    const state = engine?.machine?.state ?? "IDLE";
    if (["LOADING", "RETRY_LOADING"].includes(state)) return {
        title: "Replay is loading.", message: "Preparing the selected replay projection.", label: "LOADING", retry: false,
    };
    if (state === "ERROR" || engine?.engineError) return {
        title: "Replay unavailable.",
        message: engine?.engineError?.message ?? "The replay data is malformed or could not be loaded.",
        label: "ERROR", retry: true,
    };
    if (!engine?.dataset) return {
        title: "No replay selected.", message: "Select or load a replay to review its market context and decision path.",
        label: "EMPTY", retry: false,
    };
    if (!engine?.projection?.currentEvent) return {
        title: "Replay data unavailable.", message: "The replay is ready, but no current event is available.",
        label: "UNAVAILABLE", retry: false,
    };
    const quality = engine.projection.dataQuality ?? "UNKNOWN";
    if (["PARTIAL", "DEGRADED", "STALE", "INVALID", "UNKNOWN"].includes(quality)) return {
        title: "Replay ready with partial data.", message: `Projection data quality: ${quality}. Missing values remain explicit.`,
        label: "PARTIAL", retry: false,
    };
    return {
        title: "Replay ready.", message: "Market, decision, marker, inspector, and timeline views share one Replay Cursor.",
        label: "READY", retry: false,
    };
};

export default function MarketIntelligenceStatusLayer() {
    const { replayEngine, applyReplayCommand } = useMarketIntelligence();
    const status = stateModel(replayEngine);
    return (
        <section aria-labelledby="mi-page-status-title" className={`mi-empty-state mi-page-status mi-page-status--${status.label.toLowerCase()}`}
            role={status.label === "ERROR" ? "alert" : "status"}>
            <div>
                <h2 id="mi-page-status-title">{status.title}</h2>
                <p>{status.message}</p>
            </div>
            <div className="mi-page-status__actions">
                <span className="mi-status-label mi-status-label--muted">{status.label}</span>
                {status.retry && <button onClick={() => applyReplayCommand({ type: REPLAY_ENGINE_COMMANDS.RETRY })}
                    type="button">RETRY</button>}
            </div>
        </section>
    );
}
