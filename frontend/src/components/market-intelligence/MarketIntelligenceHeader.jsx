import { useMarketIntelligence } from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";

export default function MarketIntelligenceHeader() {
    const { replayEngine } = useMarketIntelligence();
    const contextLabel = replayEngine?.projection?.positionContext?.positionId
        ? "POSITION CONTEXT AVAILABLE" : replayEngine?.dataset ? "REPLAY LOADED" : "NO POSITION SELECTED";
    return (
        <header className="mi-header">
            <div>
                <h1 className="mi-header__title">MARKET INTELLIGENCE</h1>
                <p className="mi-header__subtitle">
                    Real-time Market Recognition &amp; AI Decision Engine
                </p>
            </div>

            <div aria-label="Review status" className="mi-header__badges">
                <span className="mi-status-label">REVIEW</span>
                <span className="mi-status-label mi-status-label--muted">
                    {contextLabel}
                </span>
            </div>
        </header>
    );
}
