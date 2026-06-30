import React from "react";

import StatusStrip from "./StatusStrip";

export default function Header({
    executionEnabled,
    pipelineStatus,
    loopCount,
}) {

    return (

        <header className="app-header">

            <StatusStrip
                botRunning={
                    executionEnabled
                }
                pipelineStatus={pipelineStatus}
                loopCount={loopCount}
            />

        </header>

    );

}
