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

    return (

        <div className="app-shell">

            <Header
                executionEnabled={
                    executionEnabled
                }
            />

            <Dashboard
                executionEnabled={
                    executionEnabled
                }
                setExecutionEnabled={
                    setExecutionEnabled
                }
            />

        </div>

    );

}