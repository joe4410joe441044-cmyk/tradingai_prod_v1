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
        pipelineStatus: "WAIT",
        loopCount: 0,
    });

    return (

        <div className="app-shell">

            <Header
                executionEnabled={
                    executionEnabled
                }
                pipelineStatus={runtimeHealthSummary.pipelineStatus}
                loopCount={runtimeHealthSummary.loopCount}
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
