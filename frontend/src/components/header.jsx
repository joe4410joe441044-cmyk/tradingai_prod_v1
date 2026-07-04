import React from "react";

import StatusStrip from "./StatusStrip";

export default function Header({
    botRunning,
    wsConnected,
    engineStatus,
    executionState,
    latency,
    pipelineStatus,
    loopCount,
}) {

    return (

        <header className="app-header">

            <StatusStrip
                botRunning={botRunning}
                wsConnected={wsConnected}
                engineStatus={engineStatus}
                executionState={executionState}
                latency={latency == null || latency === "--"
                    ? "--"
                    : `${Number(latency).toFixed(2)} ms`
                }
                pipelineStatus={pipelineStatus}
                loopCount={loopCount}
            />

        </header>

    );

}
