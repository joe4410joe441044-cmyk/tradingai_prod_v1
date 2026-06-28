export default function PositionSettings({

    config = {},
    setConfig = () => {},

}) {

    /* =====================================================
       UPDATE
    ===================================================== */

    const update = (
        key,
        value
    ) => {

        setConfig({

            ...config,

            [key]: value,

        });

    };

    /* =====================================================
       UI
    ===================================================== */

    return (

        <>

            {/* ============================================= */}
            {/* POSITION MODE */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    POSITION MODE
                </span>

                <span className="online">
                    SINGLE
                </span>

            </div>

            {/* ============================================= */}
            {/* MAX POSITIONS */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    MAX POSITIONS
                </span>

                <span>
                    {
                        config.max_positions || 1
                    }
                </span>

            </div>

            {/* ============================================= */}
            {/* POSITION LIMIT */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    POSITION LIMIT
                </span>

                <span className="warning">
                    HARD LIMIT
                </span>

            </div>

            {/* ============================================= */}
            {/* HEDGING */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    HEDGING
                </span>

                <span
                    className={
                        config.allow_hedging === "ON"
                            ? "online"
                            : "danger"
                    }
                >

                    {
                        config.allow_hedging || "OFF"
                    }

                </span>

            </div>

            {/* ============================================= */}
            {/* SCALE IN */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    SCALE IN
                </span>

                <span
                    className={
                        config.scale_in === "ON"
                            ? "online"
                            : "danger"
                    }
                >

                    {
                        config.scale_in || "OFF"
                    }

                </span>

            </div>

            {/* ============================================= */}
            {/* SCALE OUT */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    SCALE OUT
                </span>

                <span className="online">
                    ON
                </span>

            </div>

            {/* ============================================= */}
            {/* AUTO CLOSE */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    AUTO CLOSE
                </span>

                <span className="online">
                    ENABLED
                </span>

            </div>

            {/* ============================================= */}
            {/* POSITION ROUTER */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    POSITION ROUTER
                </span>

                <span className="online">
                    ACTIVE
                </span>

            </div>

            {/* ============================================= */}
            {/* POSITION PROFILE */}
            {/* ============================================= */}

            <div className="control-buttons">

                <button
                    className="start-button"
                    onClick={() =>
                        update(
                            "position_profile",
                            "safe"
                        )
                    }
                >

                    SAFE

                </button>

                <button
                    className="stop-button"
                    onClick={() =>
                        update(
                            "position_profile",
                            "aggressive"
                        )
                    }
                >

                    AGGR

                </button>

            </div>

        </>

    );

}