import { useEffect, useState } from "react";

import "./App.css";

import AppNavigation from "./components/AppNavigation";
import AIAdvisorPage from "./pages/AIAdvisorPage";
import Dashboard from "./pages/Dashboard";
import MarketIntelligencePage from "./pages/MarketIntelligencePage";
import MarketRecorderPage from "./pages/MarketRecorderPage";
import MoneyManagementPage from "./pages/MoneyManagementPage";
import SupervisorPage from "./pages/SupervisorPage";
import { DashboardMarketContextProvider } from "./state/dashboard-market/DashboardMarketContext";
import {
    startWebSocketRuntime,
    stopWebSocketRuntime,
} from "./runtime/websocketRuntime";

const MARKET_INTELLIGENCE_PATH = "/market-intelligence";
const AI_ADVISOR_PATH = "/ai-advisor";
const MONEY_MANAGEMENT_PATH = "/money-management";
const MARKET_RECORDER_PATH = "/market-recorder";
const SUPERVISOR_PATH = "/supervisor";

const resolveAppPath = (pathname) => {
    if (pathname === MARKET_INTELLIGENCE_PATH) {
        return MARKET_INTELLIGENCE_PATH;
    }
    if (pathname === AI_ADVISOR_PATH) {
        return AI_ADVISOR_PATH;
    }
    if (pathname === MONEY_MANAGEMENT_PATH) {
        return MONEY_MANAGEMENT_PATH;
    }
    if (pathname === MARKET_RECORDER_PATH) {
        return MARKET_RECORDER_PATH;
    }
    if (pathname === SUPERVISOR_PATH) {
        return SUPERVISOR_PATH;
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
            : currentPath === MONEY_MANAGEMENT_PATH
                ? MoneyManagementPage
                : currentPath === MARKET_RECORDER_PATH
                    ? MarketRecorderPage
                    : currentPath === SUPERVISOR_PATH
                        ? SupervisorPage
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
