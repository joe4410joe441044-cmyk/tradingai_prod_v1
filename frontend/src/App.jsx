import { useState } from "react";

import "./App.css";

import AppNavigation from "./components/AppNavigation";
import Dashboard from "./pages/Dashboard";
import MarketIntelligencePage from "./pages/MarketIntelligencePage";

const MARKET_INTELLIGENCE_PATH = "/market-intelligence";

const resolveAppPath = (pathname) => (
    pathname === MARKET_INTELLIGENCE_PATH
        ? MARKET_INTELLIGENCE_PATH
        : "/"
);

/* =================================================
   APP
================================================= */

export default function App() {
    const [currentPath, setCurrentPath] = useState(() => (
        resolveAppPath(window.location.pathname)
    ));

    const CurrentPage = currentPath === MARKET_INTELLIGENCE_PATH
        ? MarketIntelligencePage
        : Dashboard;

    return (
        <div className="app-shell market-intelligence">
            <AppNavigation
                currentPath={currentPath}
                onPathChange={setCurrentPath}
            />

            <CurrentPage />
        </div>
    );
}
