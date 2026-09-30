import { positionNumber, positionQuantity, positionTime, positionHolding, positionState } from "./accountRuntimeModel.js";
import { PositionMetric, PositionBadges, PositionIdentity, PositionMoney } from "./PositionCardFields.jsx";

export default function CurrentPositionCard({ position = {} }) {
    const state = positionState(position);
    const rows = Array.isArray(position.positions) ? position.positions : [];
    return <article className={`semantic-card as-card clear as-position-card${state === "OPEN" ? " as-position-card--open" : ""}${state === "UNKNOWN / STALE" ? " as-position-card--stale" : ""}`} data-testid="current-position-card">
        <header className="semantic-card-header"><h2>CURRENT POSITION / 現在保有ポジション</h2></header>
        <div className="as-position-body">
        <PositionBadges state={state} position={position} />
        {state === "OPEN" ? <>
            <PositionIdentity position={position} />
            <dl className="as-position-grid as-position-primary">
                <PositionMetric label="QUANTITY" value={positionQuantity(position)} />
                <PositionMetric label="ENTRY PRICE" value={positionNumber(position.entryPrice)} />
                <PositionMetric label="MARK PRICE" value={positionNumber(position.markPrice)} />
                <PositionMetric label="UNREALIZED PNL" value={<PositionMoney value={position.unrealizedPnl} pnl />} pnl={position.unrealizedPnl} />
            </dl>
            <dl className="as-position-grid">
                <PositionMetric label="POSITION VALUE" value={<PositionMoney value={position.positionValue} />} />
                <PositionMetric label="LEVERAGE" value={positionNumber(position.leverage)} />
                <PositionMetric label="MARGIN USED" value={<PositionMoney value={position.marginUsed} />} />
                <PositionMetric label="LIQUIDATION PRICE" value={positionNumber(position.liquidationPrice)} />
                <PositionMetric label="ENTRY TIME" value={positionTime(position.entryTime)} />
                <PositionMetric label="HOLDING TIME" value={positionHolding(position.holdingMs)} />
            </dl>
        </> : <p className="as-position-message">{state === "FLAT" ? "NO OPEN POSITION" : state === "UNKNOWN / STALE" ? "POSITION DATA IS STALE" : state === "MULTIPLE POSITIONS" ? `${rows.length} OPEN POSITIONS DETECTED` : "POSITION STATE UNAVAILABLE"}</p>}
        <details className="as-position-details"><summary>POSITION DETAILS / 詳細</summary>
            <dl className="as-position-grid">
                <PositionMetric label="SOURCE" value={position.source} />
                <PositionMetric label="FRESHNESS" value={position.freshness ?? "UNKNOWN"} />
                <PositionMetric label="SOURCE UPDATED" value={positionTime(position.sourceUpdatedAt)} />
                <PositionMetric label="REASON" value={position.reason} />
                {state === "OPEN" && <>
                    <PositionMetric label="COIN QUANTITY" value={positionNumber(position.coinQuantity)} />
                    <PositionMetric label="CONTRACTS" value={positionNumber(position.contractQuantity)} />
                    <PositionMetric label="ENTRY ORDER SIDE" value={position.orderSide} />
                    <PositionMetric label="MARK PRICE SOURCE" value={position.markPriceSource} />
                    <PositionMetric label="UNREALIZED PNL SOURCE" value={position.unrealizedPnlSource} />
                </>}
            </dl>
            {state === "MULTIPLE POSITIONS" && <ul>{rows.map((row, index) => <li key={index}>{row.symbol ?? "SYMBOL UNKNOWN"} — {["LONG", "SHORT"].includes(row.side) ? row.side : "SIDE UNKNOWN"}</li>)}</ul>}
        </details>
        </div>
    </article>;
}
