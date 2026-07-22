import { useMarketIntelligence } from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";
import { REPLAY_ENGINE_COMMANDS } from "../../features/market-intelligence/replay/replayEngine.js";
import { bilingual } from "./marketIntelligenceLabels.js";

const timestampLabel = (value) => {
    const epoch = typeof value === "number" ? value : Date.parse(value);
    if (!Number.isFinite(epoch)) return "Timestamp unavailable";
    const date = new Date(epoch);
    return Number.isFinite(date.getTime()) ? date.toISOString() : "Timestamp unavailable";
};

export default function MarketIntelligenceToolbar() {
    const { replayEngine, applyReplayCommand } = useMarketIntelligence();
    const projection = replayEngine?.projection;
    const hasReplay = Boolean(replayEngine?.dataset);
    const quality = projection?.dataQuality ?? "MISSING";
    const machineState = replayEngine?.machine?.state ?? "IDLE";
    const hasError = machineState === "ERROR" || Boolean(replayEngine?.engineError);
    const status = hasError ? "ERROR" : !hasReplay ? "NO REPLAY SELECTED" : !projection?.currentEvent
        ? "UNAVAILABLE" : quality === "VALID" ? "REPLAY READY" : "PARTIAL";

    return (
        <section aria-labelledby="mi-toolbar-heading" className="mi-toolbar">
            <h2 className="mi-visually-hidden" id="mi-toolbar-heading">Replay context（リプレイ状況）</h2>

            <label className="mi-toolbar__field">
                <span>{bilingual("position")}</span>
                <select disabled value={replayEngine?.dataset?.datasetId ?? ""}>
                    <option value={replayEngine?.dataset?.datasetId ?? ""}>
                        {hasReplay ? replayEngine.dataset.datasetId ?? "Replay loaded" : "NO REPLAY SELECTED"}
                    </option>
                </select>
            </label>

            <div className="mi-toolbar__field">
                <span>{bilingual("mode")}</span>
                <strong>{hasReplay ? replayEngine.machine?.state ?? "REVIEW" : "REVIEW"}</strong>
            </div>

            <div className="mi-toolbar__field">
                <span>{bilingual("timestamp")}</span>
                <strong>{timestampLabel(replayEngine?.replayCursor)}</strong>
            </div>

            <div className="mi-toolbar__field">
                <span>{bilingual("quality")}</span>
                <strong className={quality === "VALID" ? undefined : "mi-status-text--missing"}>{quality}</strong>
            </div>
            <div className="mi-toolbar__field mi-toolbar__status">
                <span>{bilingual("status")}</span>
                <strong className={status === "REPLAY READY" ? undefined : "mi-status-text--missing"}>{status}</strong>
                {hasError && <button onClick={() => applyReplayCommand({ type: REPLAY_ENGINE_COMMANDS.RETRY })}
                    type="button">RETRY（再試行）</button>}
            </div>
        </section>
    );
}
