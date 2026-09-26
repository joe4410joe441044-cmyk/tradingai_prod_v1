import { useMarketIntelligence } from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";
import { REPLAY_ENGINE_COMMANDS } from "../../features/market-intelligence/replay/replayEngine.js";
import { bilingualSlash, bilingualSlashText } from "./marketIntelligenceLabels.js";

const replayStatusLabel = (status) => status === "NO REPLAY SELECTED"
    ? bilingualSlashText("NO REPLAY SELECTED", "リプレイ未選択") : status;

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
        <section aria-labelledby="mi-toolbar-heading" className={`mi-toolbar${hasReplay ? "" : " mi-toolbar--empty"}`}>
            <h2 className="mi-visually-hidden" id="mi-toolbar-heading">Replay context（リプレイ状況）</h2>

            {!hasReplay ? <>
                <div className="mi-toolbar__field">
                    <span>{bilingualSlash("mode")}</span>
                    <strong>REVIEW</strong>
                </div>
                <div className="mi-toolbar__field mi-toolbar__status">
                    <span>{bilingualSlashText("REPLAY", "リプレイ")}</span>
                    <strong className="mi-status-text--missing">{replayStatusLabel(status)}</strong>
                    {hasError && <button onClick={() => applyReplayCommand({ type: REPLAY_ENGINE_COMMANDS.RETRY })}
                        type="button">RETRY（再試行）</button>}
                </div>
            </> : <><label className="mi-toolbar__field">
                <span>{bilingualSlash("position")}</span>
                <select disabled value={replayEngine?.dataset?.datasetId ?? ""}>
                    <option value={replayEngine?.dataset?.datasetId ?? ""}>
                        {replayEngine.dataset.datasetId ?? "Replay loaded"}
                    </option>
                </select>
            </label>

            <div className="mi-toolbar__field">
                <span>{bilingualSlash("mode")}</span>
                <strong>{replayEngine.machine?.state ?? "REVIEW"}</strong>
            </div>

            <div className="mi-toolbar__field">
                <span>{bilingualSlash("timestamp")}</span>
                <strong>{timestampLabel(replayEngine?.replayCursor)}</strong>
            </div>

            <div className="mi-toolbar__field">
                <span>{bilingualSlash("quality")}</span>
                <strong className={quality === "VALID" ? undefined : "mi-status-text--missing"}>{quality}</strong>
            </div>
            <div className="mi-toolbar__field mi-toolbar__status">
                <span>{bilingualSlash("status")}</span>
                <strong className={status === "REPLAY READY" ? undefined : "mi-status-text--missing"}>{status}</strong>
                {hasError && <button onClick={() => applyReplayCommand({ type: REPLAY_ENGINE_COMMANDS.RETRY })}
                    type="button">RETRY（再試行）</button>}
            </div></>}
        </section>
    );
}
