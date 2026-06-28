import React from "react";

import StatusStrip from "./StatusStrip";

export default function Header({
    executionEnabled
}) {

    return (

        <header className="app-header">

            <StatusStrip
                botRunning={
                    executionEnabled
                }
            />

        </header>

    );

}