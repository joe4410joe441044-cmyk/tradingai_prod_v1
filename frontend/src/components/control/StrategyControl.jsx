import {
    setMode,
    triggerEmergencyStop,
} from "../../runtime/governanceRuntime";

import {
    telemetryState,
} from "../../store/telemetryStore";

export default function StrategyControl() {

    /* =====================================================
       GOVERNANCE RUNTIME
    ===================================================== */

    const governance =
        telemetryState.governance || {};

    /* =====================================================
       BACKEND STATE
    ===================================================== */

    const mode =
        governance.mode || "PAPER";

    const survivability =
        governance.survivability || "--";

    const cognitionStability =
        governance.cognitionStability || "--";

    const restrictionReason =
        governance.restrictionReason || "NONE";

    /* =====================================================
       MODE CHANGE
    ===================================================== */

    const changeMode = async (
        nextMode
    ) => {

        const ok = window.confirm(
            "RUNTIME PROFILE を " +
            nextMode.toUpperCase() +
            " に変更しますか？"
        );

        if (!ok) {

            return;

        }

        try {

            await setMode(
                nextMode.toUpperCase()
            );

            console.log(
                "RUNTIME PROFILE CHANGE:",
                nextMode.toUpperCase()
            );

        } catch (err) {

            console.error(
                "RUNTIME PROFILE ERROR:",
                err
            );

        }

    };

    /* =====================================================
       UI
    ===================================================== */

    return (

        <>

            {/* ============================================= */}
            {/* RUNTIME PROFILE */}
            {/* ============================================= */}

            <div className="control-buttons">

                <button
                    className={
                        mode === "PAPER"
                            ? "start-button active"
                            : "start-button"
                    }
                    onClick={() =>
                        changeMode("paper")
                    }
                >

                    SAFE

                </button>

                <button
                    className={
                        mode === "PRODUCTION"
                            ? "stop-button active"
                            : "stop-button"
                    }
                    onClick={() =>
                        changeMode("production")
                    }
                >

                    PRODUCTION

                </button>

            </div>

            {/* ============================================= */}
            {/* RUNTIME STATE */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    RUNTIME
                </span>

                <span
                    className={
                        mode === "PRODUCTION"
                            ? "danger"
                            : "online"
                    }
                >

                    {mode}

                </span>

            </div>

            {/* ============================================= */}
            {/* EXCHANGE */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    EXCHANGE
                </span>

                <span>
                    BINANCE
                </span>

            </div>

            {/* ============================================= */}
            {/* SYMBOL */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    SYMBOL
                </span>

                <span>
                    XRPUSDT
                </span>

            </div>

            {/* ============================================= */}
            {/* SURVIVABILITY */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    SURVIVABILITY
                </span>

                <span

                className="neutral"

                >

                    {survivability}

                </span>

            </div>

            {/* ============================================= */}
            {/* COGNITION */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    COGNITION
                </span>

                <span>

                    {cognitionStability}

                </span>

            </div>

            {/* ============================================= */}
            {/* RESTRICTION */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    RESTRICTION
                </span>

                <span>

                    {restrictionReason}

                </span>

            </div>

            {/* ============================================= */}
            {/* OPERATIONAL TELEMETRY */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    VOLATILITY
                </span>

                <span>
                    0.0025
                </span>

            </div>


            {/* ============================================= */}
            {/* GOVERNANCE AUTHORITY */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    AUTHORITY
                </span>

                <span className="online">
                    BACKEND
                </span>

            </div>

            {/* ============================================= */}
            {/* QUICK ACTIONS */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    KILL SWITCH
                </span>

                <span
                    className="danger"
                    onClick={
                        triggerEmergencyStop
                    }
                    style={{
                        cursor: "pointer",
                    }}
                >

                    ARMED

                </span>

            </div>

        </>

    );

}
