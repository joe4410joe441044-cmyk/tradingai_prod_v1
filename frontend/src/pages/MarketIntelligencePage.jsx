import AIIntelligenceWorkspace from "../components/market-intelligence/AIIntelligenceWorkspace";
import AutoMarketSelectionPanel from "../components/market-intelligence/AutoMarketSelectionPanel";
import DecisionRailway, { DecisionRailwaySummary } from "../components/market-intelligence/DecisionRailway";
import MarketIntelligenceErrorBoundary from "../components/market-intelligence/MarketIntelligenceErrorBoundary";
import MarketIntelligenceToolbar from "../components/market-intelligence/MarketIntelligenceToolbar";
import MarketIntelligenceWorkspace from "../components/market-intelligence/MarketIntelligenceWorkspace";
import PositionTimeline from "../components/market-intelligence/PositionTimeline";
import ReplayController from "../components/market-intelligence/ReplayController";
import ReplayInspector from "../components/market-intelligence/ReplayInspector";
import ReplayInvestigationPanel from "../components/market-intelligence/ReplayInvestigationPanel";
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
                    <MarketIntelligenceWorkspace
                        primaryLeft={<ReplayMarketView />}
                        primaryRight={<AutoMarketSelectionPanel />}
                        secondary={<AIIntelligenceWorkspace finalDecision={<DecisionRailwaySummary />} />}
                        investigation={
                            <ReplayInvestigationPanel>
                                <ReplayController />
                                <div className="mi-replay-workspace__analysis">
                                    <DecisionRailway showSummary={false} />
                                    <ReplayInspector />
                                </div>
                                <PositionTimeline />
                                <ReplayTimeline />
                            </ReplayInvestigationPanel>
                        }
                    />
                </main>
            </MarketIntelligenceProvider>
        </MarketIntelligenceErrorBoundary>
    );
}
