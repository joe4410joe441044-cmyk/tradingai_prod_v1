import { positionNumber, positionQuantity, positionTime, positionHolding } from "./accountRuntimeModel.js";
import { PositionMetric, PositionBadges, PositionIdentity, PositionMoney } from "./PositionCardFields.jsx";

export default function LastPositionEventCard({ position = {} }) {
    const state = ["CLOSED", "NONE"].includes(position.event) ? position.event : "UNKNOWN";
    return <article className="semantic-card as-card clear as-position-card as-position-card--secondary" data-testid="last-position-event-card">
        <header className="semantic-card-header"><h2>LAST POSITION EVENT / 直前ポジションイベント</h2></header>
        <div className="as-position-body">
        <PositionBadges state={state} position={position} />
        {state === "CLOSED" ? <>
            <PositionIdentity position={position} />
            <dl className="as-position-grid">
                <PositionMetric label="QUANTITY" value={positionQuantity(position)} />
                <PositionMetric label="ENTRY PRICE" value={positionNumber(position.entryPrice)} />
                <PositionMetric label="EXIT PRICE" value={positionNumber(position.exitPrice)} />
                <PositionMetric label="REALIZED PNL" value={<PositionMoney value={position.realizedPnl} pnl />} pnl={position.realizedPnl} />
                <PositionMetric label="HOLDING" value={positionHolding(position.holdingMs)} />
                <PositionMetric label="EXIT REASON" value={position.exitReason} />
                <PositionMetric label="OPENED" value={positionTime(position.openedAt)} />
                <PositionMetric label="CLOSED" value={positionTime(position.closedAt)} />
            </dl>
            <details className="as-position-details"><summary>EVENT DETAILS / 詳細</summary><dl className="as-position-grid">
                <PositionMetric label="SOURCE" value={position.source} />
                <PositionMetric label="TRADE ID" value={position.tradeId} />
                <PositionMetric label="REALIZED PNL AUTHORITATIVE" value={position.realizedPnlAuthoritative === true ? "YES" : position.realizedPnlAuthoritative === false ? "NO" : "UNKNOWN"} />
            </dl></details>
        </> : <p className="as-position-message">{state === "NONE" ? "NO RECENT POSITION EVENT" : "RECENT POSITION EVENT UNAVAILABLE"}</p>}
        </div>
    </article>;
}
