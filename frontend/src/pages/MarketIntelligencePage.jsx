import DecisionRailway, { DecisionRailwaySummary } from "../components/market-intelligence/DecisionRailway";
import MarketIntelligenceErrorBoundary from "../components/market-intelligence/MarketIntelligenceErrorBoundary";
import MarketIntelligenceToolbar from "../components/market-intelligence/MarketIntelligenceToolbar";
import MarketIntelligenceWorkspace from "../components/market-intelligence/MarketIntelligenceWorkspace";
import ReplayController from "../components/market-intelligence/ReplayController";
import ReplayInspector from "../components/market-intelligence/ReplayInspector";
import ReplayMarketView from "../components/market-intelligence/ReplayMarketView";
import ReplayTimeline from "../components/market-intelligence/ReplayTimeline";
import { MarketIntelligenceProvider } from "../state/market-intelligence/MarketIntelligenceProvider";

export default function MarketIntelligencePage() {
    return (
        <MarketIntelligenceErrorBoundary>
            <MarketIntelligenceProvider>
                <main className="mi-page">
                    <h1 className="mi-visually-hidden">MARKET INTELLIGENCE（市場インテリジェンス）</h1>
                    <MarketIntelligenceToolbar />
                    <section aria-label="Primary market intelligence" className="mi-primary-view">
                        <ReplayMarketView />
                        <DecisionRailwaySummary />
                        <ReplayController />
                    </section>
                    <MarketIntelligenceWorkspace leftPanel={<DecisionRailway showSummary={false} />}
                        rightPanel={<ReplayInspector />} />
                    <ReplayTimeline />
                </main>
            </MarketIntelligenceProvider>
        </MarketIntelligenceErrorBoundary>
    );
}
