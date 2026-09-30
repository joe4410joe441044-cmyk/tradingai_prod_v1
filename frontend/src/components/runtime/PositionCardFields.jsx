import { positionNumber } from "./accountRuntimeModel.js";

export function PositionMetric({ label, value, pnl }) {
    const tone = typeof pnl === "number" && Number.isFinite(pnl) ? (pnl > 0 ? "positive" : pnl < 0 ? "negative" : "neutral") : "neutral";
    return <div className={`as-position-metric as-position-metric--${tone}`}>
        <dt>{label}</dt><dd>{value ?? "—"}</dd>
    </div>;
}
export function PositionBadges({ state, position }) {
    return <div className="as-position-badges">
        <strong>{state === "OPEN" ? "● OPEN" : state}</strong>
        <span className="semantic-badge">{["PAPER", "LIVE"].includes(position.mode) ? position.mode : "MODE UNKNOWN"}</span>
        <span className="semantic-badge">{["MANUAL", "BOT"].includes(position.control) ? position.control : "UNKNOWN"}</span>
    </div>;
}
export function PositionIdentity({ position }) {
    return <div className="as-position-identity"><strong>{position.symbol ?? "SYMBOL UNKNOWN"}</strong>
        <strong>{["LONG", "SHORT"].includes(position.side) ? position.side : "SIDE UNKNOWN"}</strong></div>;
}
export function PositionMoney({ value, pnl = false }) {
    return <>{positionNumber(value, pnl)}{typeof value === "number" && Number.isFinite(value) ? " USDT" : ""}</>;
}
