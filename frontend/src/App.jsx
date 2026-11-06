import { useEffect, useState } from "react";

import "./App.css";

import AppNavigation from "./components/AppNavigation";
import AccountStatusPage from "./pages/AccountStatusPage";
import AIAdvisorPage from "./pages/AIAdvisorPage";
import Dashboard from "./pages/Dashboard";
import MarketIntelligencePage from "./pages/MarketIntelligencePage";
import MarketRecorderPage from "./pages/MarketRecorderPage";
import MoneyManagementPage from "./pages/MoneyManagementPage";
import ParameterSettingsPage from "./pages/ParameterSettingsPage";
import PropIsolatedDemoPage from "./pages/PropIsolatedDemoPage";
import SupervisorPage from "./pages/SupervisorPage";
import TradeHistoryPage from "./pages/TradeHistoryPage";
import {
    PROP_ISOLATED_DEMO_ENABLED,
    PROP_ISOLATED_DEMO_PATH,
} from "./features/prop-accounts/propIsolatedDemoFeature.js";
import { resolveAppPath } from "./appRouteModel.js";
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
const ACCOUNT_STATUS_PATH = "/account-status";
const PARAMETER_SETTINGS_PATH = "/parameter-settings";
const TRADE_HISTORY_PATH = "/trade-history";

/* =================================================
   APP
================================================= */

export default function App() {
    const [currentPath, setCurrentPath] = useState(() => (
        resolveAppPath(window.location.pathname)
    ));

    const CurrentPage = currentPath === PROP_ISOLATED_DEMO_PATH
        ? PropIsolatedDemoPage
        : currentPath === ACCOUNT_STATUS_PATH
        ? AccountStatusPage
        : currentPath === MARKET_INTELLIGENCE_PATH
            ? MarketIntelligencePage
            : currentPath === AI_ADVISOR_PATH
                ? AIAdvisorPage
                : currentPath === MONEY_MANAGEMENT_PATH
                    ? MoneyManagementPage
                    : currentPath === MARKET_RECORDER_PATH
                        ? MarketRecorderPage
                        : currentPath === SUPERVISOR_PATH
                            ? SupervisorPage
                            : currentPath === PARAMETER_SETTINGS_PATH
                                ? ParameterSettingsPage
                                : currentPath === TRADE_HISTORY_PATH
                                    ? TradeHistoryPage
                                    : Dashboard;
    const runtimeSuppressed = currentPath === AI_ADVISOR_PATH
        || currentPath === PROP_ISOLATED_DEMO_PATH;

    useEffect(() => {
        if (runtimeSuppressed) {
            stopWebSocketRuntime();
            return;
        }
        startWebSocketRuntime();
        return () => stopWebSocketRuntime();
    }, [runtimeSuppressed]);

    return (
        <DashboardMarketContextProvider>
            <div className="app-shell market-intelligence">
                <AppNavigation
                    currentPath={currentPath}
                    onPathChange={setCurrentPath}
                    propDemoEnabled={PROP_ISOLATED_DEMO_ENABLED}
                />

                <CurrentPage />
            </div>
        </DashboardMarketContextProvider>
    );
}
