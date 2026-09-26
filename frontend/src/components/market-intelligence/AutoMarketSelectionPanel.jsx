import { useState } from "react";

import AutoMarketSelectionCard from "../AutoMarketSelectionCard";
import { API } from "../../api/index.js";
import { authenticatedControlRequest } from "../../features/auth/operatorAuth.js";
import { deriveReselectBlocker } from "../../features/auto-market-selection/autoMarketSelectionModel.js";
import { useMarketIntelligence } from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";

export default function AutoMarketSelectionPanel() {
    const { autoMarketSelectionStatus, botStatus } = useMarketIntelligence();
    const [reselectBusy, setReselectBusy] = useState(false);
    const blocker = deriveReselectBlocker(botStatus);

    const handleReselect = async () => {
        if (reselectBusy) return;
        setReselectBusy(true);
        try {
            await authenticatedControlRequest(API.paperAutoReselect(), { method: "POST" });
        } catch (error) {
            console.error("AMS RESELECT ERROR", error);
        } finally {
            setReselectBusy(false);
        }
    };

    return (
        <AutoMarketSelectionCard
            collapsible={true}
            status={autoMarketSelectionStatus}
            onReselect={handleReselect}
            reselectDisabled={blocker.disabled}
            reselectReason={blocker.reason}
            reselectBusy={reselectBusy}
        />
    );
}
