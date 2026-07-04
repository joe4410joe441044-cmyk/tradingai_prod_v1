import React, { useState } from "react";

import "./App.css";

import Header from "./components/header";
import Dashboard from "./pages/Dashboard";

/* =================================================
   APP
================================================= */

export default function App() {

    /* =============================================
       GLOBAL EXECUTION STATE
    ============================================= */

    const [
        executionEnabled,
        setExecutionEnabled
    ] = useState(false);
    const [runtimeHealthSummary, setRuntimeHealthSummary] = useState({
        botRunning: false,
        wsConnected: false,
        engineStatus: "STOPPED",
        executionState: "DISABLED",
        latency: "--",
        pipelineStatus: "WAIT",
        loopCount: 0,
    });

    return (

        <div className="app-shell">

            <Header
                {...runtimeHealthSummary}
            />

            <Dashboard
                executionEnabled={
                    executionEnabled
                }
                setExecutionEnabled={
                    setExecutionEnabled
                }
                onRuntimeHealthChange={setRuntimeHealthSummary}
            />

        </div>

    );

}
