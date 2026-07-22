import { useState } from "react";

import {
    REPLAY_ENGINE_COMMANDS as C,
} from "../../features/market-intelligence/replay/replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "../../features/market-intelligence/replay/replayFixtures.js";
import {
    buildReplayControllerModel,
    convertSeekPercentToTimestamp,
    convertTimestampToSeekPercent,
} from "../../features/market-intelligence/replay/replayControllerModel.js";
import { useMarketIntelligence } from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";
import { bilingual } from "./marketIntelligenceLabels.js";

const errorText = (error) => {
    if (!error) return "None";
    const code = typeof error.code === "string" ? error.code : "REPLAY_ERROR";
    const message = typeof error.message === "string" ? error.message : "Replay failed.";
    return `${code} — ${message}`;
};

export function ReplayControllerView({
    model,
    seekPercent,
    seekTimestamp,
    onSeekPercentChange,
    onCommand,
}) {
    const controls = model.controls;
    const isEmpty = model.machineState === "IDLE";
    const button = (label, type, enabled, payload) => (
        <button
            className="mi-replay-controller__button"
            disabled={!enabled}
            onClick={() => onCommand(type, payload)}
            type="button"
        >
            {label}
        </button>
    );

    return (
        <section aria-labelledby="mi-replay-controller-title" className="mi-replay-controller">
            <div className="mi-replay-controller__heading">
                <div>
                    <h2 id="mi-replay-controller-title">{bilingual("replayController")}</h2>
                </div>
                <span className={`mi-status-label mi-replay-state mi-replay-state--${model.machineState.toLowerCase()}`}>
                    {model.machineState}
                </span>
            </div>

            {!isEmpty && <dl className="mi-replay-controller__summary mi-replay-controller__summary--primary">
                <div><dt>{bilingual("progress")}</dt><dd>{model.progressPercent}%</dd></div>
                <div><dt>{bilingual("currentCursor")}</dt><dd>{model.cursor}</dd></div>
                <div><dt>{bilingual("currentEvent")}</dt><dd>{model.currentEvent.type}</dd></div>
            </dl>}

            <div aria-label="Replay operations" className="mi-replay-controller__buttons">
                {button("LOAD SAMPLE REPLAY（サンプル読込）", C.LOAD_DATASET, controls.canLoad, {
                    dataset: XRP_REPLAY_FIXTURE,
                })}
                {!isEmpty && <>{button("PLAY（再生）", C.PLAY, controls.canPlay)}
                {button("PAUSE（一時停止）", C.PAUSE, controls.canPause)}
                {button("STEP BACK（1ステップ戻る）", C.STEP_BACKWARD, controls.canStepBackward)}
                {button("STEP FORWARD（1ステップ進む）", C.STEP_FORWARD, controls.canStepForward)}
                {button("START（先頭）", C.JUMP_TO_START, controls.canJumpStart)}
                {button("END（末尾）", C.JUMP_TO_END, controls.canJumpEnd)}
                {button("RESTART（再開）", C.RESTART, controls.canRestart)}
                {button("RESET（リセット）", C.RESET, controls.canReset)}
                {button("RETRY（再試行）", C.RETRY, controls.canRetry)}</>}
            </div>

            {!isEmpty && <div className="mi-replay-controller__seek">
                <label htmlFor="mi-replay-seek">
                    {bilingual("seek")}: <strong>{seekPercent}%</strong>
                </label>
                <input
                    disabled={!controls.canSeek}
                    id="mi-replay-seek"
                    max="100"
                    min="0"
                    onChange={(event) => onSeekPercentChange(event.target.value)}
                    step="1"
                    type="range"
                    value={seekPercent}
                />
                <output htmlFor="mi-replay-seek">Target: {seekTimestamp ?? "—"}</output>
                {button(
                    "SEEK（移動）",
                    C.SEEK,
                    controls.canSeek && seekTimestamp !== null,
                    { timestamp: seekTimestamp },
                )}
            </div>}

            {!isEmpty && <div className="mi-replay-controller__messages" aria-live="polite">
                <p><strong>Replay Error:</strong> {errorText(model.error)}</p>
                <p><strong>Last command rejected:</strong> {model.rejectionReason ?? "None"}</p>
                {model.machineState === "PLAYING" && (
                    <p className="mi-replay-controller__manual-note">
                        Manual playback mode. Automatic advancement is not enabled.
                    </p>
                )}
            </div>}
            {!isEmpty && <details className="mi-advanced-disclosure mi-replay-controller__details">
                <summary>Dataset Details（データセット詳細）</summary>
                <dl className="mi-replay-controller__summary">
                    <div><dt>Dataset ID</dt><dd>{model.datasetSummary.id}</dd></div>
                    <div><dt>{bilingual("symbol")}</dt><dd>{model.datasetSummary.symbol}</dd></div>
                    <div><dt>{bilingual("exchange")}</dt><dd>{model.datasetSummary.exchange}</dd></div>
                    <div><dt>Trade Mode（取引モード）</dt><dd>{model.datasetSummary.tradeMode}</dd></div>
                    <div><dt>Reached Events（到達イベント）</dt><dd>{model.reachedEventCount} / {model.totalEventCount}</dd></div>
                    <div><dt>Last Command（最終操作）</dt><dd>{model.accepted ? "Accepted" : "Rejected"}</dd></div>
                </dl>
            </details>}
        </section>
    );
}

export default function ReplayController() {
    const { replayEngine, applyReplayCommand } = useMarketIntelligence();
    const model = buildReplayControllerModel(replayEngine);
    const [seekPreview, setSeekPreview] = useState(null);
    const seekPercent = seekPreview ?? Math.round(convertTimestampToSeekPercent(
        replayEngine.dataset,
        replayEngine.replayCursor,
    ));
    const seekTimestamp = convertSeekPercentToTimestamp(replayEngine.dataset, seekPercent);
    const handleCommand = (type, payload) => {
        setSeekPreview(null);
        applyReplayCommand({ type, payload });
    };
    const handleSeekPercentChange = (value) => {
        const numeric = Number(value);
        if (Number.isFinite(numeric)) setSeekPreview(Math.min(100, Math.max(0, numeric)));
    };

    return (
        <ReplayControllerView
            model={model}
            onCommand={handleCommand}
            onSeekPercentChange={handleSeekPercentChange}
            seekPercent={seekPercent}
            seekTimestamp={seekTimestamp}
        />
    );
}
