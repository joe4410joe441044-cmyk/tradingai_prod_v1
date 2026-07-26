import { useEffect, useState } from "react";

import "./App.css";

import AppNavigation from "./components/AppNavigation";
import AIAdvisorPage from "./pages/AIAdvisorPage";
import Dashboard from "./pages/Dashboard";
import MarketIntelligencePage from "./pages/MarketIntelligencePage";
import { DashboardMarketContextProvider } from "./state/dashboard-market/DashboardMarketContext";
import {
    startWebSocketRuntime,
    stopWebSocketRuntime,
} from "./runtime/websocketRuntime";

const MARKET_INTELLIGENCE_PATH = "/market-intelligence";
const AI_ADVISOR_PATH = "/ai-advisor";

const resolveAppPath = (pathname) => {
    if (pathname === MARKET_INTELLIGENCE_PATH) {
        return MARKET_INTELLIGENCE_PATH;
    }
    if (pathname === AI_ADVISOR_PATH) {
        return AI_ADVISOR_PATH;
    }
    return "/";
};

/* =================================================
   APP
================================================= */

export default function App() {
    const [currentPath, setCurrentPath] = useState(() => (
        resolveAppPath(window.location.pathname)
    ));

    const CurrentPage = currentPath === MARKET_INTELLIGENCE_PATH
        ? MarketIntelligencePage
        : currentPath === AI_ADVISOR_PATH
            ? AIAdvisorPage
            : Dashboard;
    const advisorActive = currentPath === AI_ADVISOR_PATH;

    useEffect(() => {
        if (advisorActive) {
            stopWebSocketRuntime();
            return;
        }
        startWebSocketRuntime();
        return () => stopWebSocketRuntime();
    }, [advisorActive]);

    return (
        <DashboardMarketContextProvider>
            <div className="app-shell market-intelligence">
                <AppNavigation
                    currentPath={currentPath}
                    onPathChange={setCurrentPath}
                />

                <CurrentPage />
            </div>
        </DashboardMarketContextProvider>
    );
}
