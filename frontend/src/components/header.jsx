import React from "react";

import StatusStrip from "./StatusStrip";

export default function Header({ runtimeHealth }) {

    return (

        <header className="app-header">

            <StatusStrip
                runtimeHealth={runtimeHealth}
            />

        </header>

    );

}
