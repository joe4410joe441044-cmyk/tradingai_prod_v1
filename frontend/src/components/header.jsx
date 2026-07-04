import React from "react";

import StatusStrip from "./StatusStrip";

export default function Header({
    botStatus,
    wsStatus,
    engineStatus,
    executionState,
    latency,
    pipelineStatus,
    loopCount,
}) {

    return (

        <header className="app-header">

            <StatusStrip
                botStatus={botStatus}
                wsStatus={wsStatus}
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
