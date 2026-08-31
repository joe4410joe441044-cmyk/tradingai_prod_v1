import AutoMarketSelectionCard from "../AutoMarketSelectionCard";
import { useMarketIntelligence } from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";

export default function AutoMarketSelectionPanel() {
    const { autoMarketSelectionStatus } = useMarketIntelligence();
    return <AutoMarketSelectionCard collapsible={true} status={autoMarketSelectionStatus} />;
}
