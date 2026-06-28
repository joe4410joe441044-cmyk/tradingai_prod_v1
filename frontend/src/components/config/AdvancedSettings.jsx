export default function AdvancedSettings({

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
       STATUS
    ===================================================== */

    const dryRun =
        config.dry_run || "ON";

    const partialTP =
        config.partial_tp || "OFF";

    const breakEven =
        config.break_even || "OFF";

    const trailingStop =
        config.trailing_stop || "OFF";

    const timeLock =
        config.time_lock || 3;

    /* =====================================================
       UI
    ===================================================== */

    return (

        <>

            {/* ============================================= */}
            {/* ADVANCED MODE */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    ADVANCED
                </span>

                <span className="warning">
                    ENABLED
                </span>

            </div>

            {/* ============================================= */}
            {/* DRY RUN */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    DRY RUN
                </span>

                <span
                    className={
                        dryRun === "ON"
                            ? "online"
                            : "danger"
                    }
                >

                    {dryRun}

                </span>

            </div>

            {/* ============================================= */}
            {/* PARTIAL TP */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    PARTIAL TP
                </span>

                <span
                    className={
                        partialTP === "ON"
                            ? "online"
                            : "danger"
                    }
                >

                    {partialTP}

                </span>

            </div>

            {/* ============================================= */}
            {/* BREAK EVEN */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    BREAK EVEN
                </span>

                <span
                    className={
                        breakEven === "ON"
                            ? "online"
                            : "danger"
                    }
                >

                    {breakEven}

                </span>

            </div>

            {/* ============================================= */}
            {/* TRAILING STOP */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    TRAILING STOP
                </span>

                <span
                    className={
                        trailingStop === "ON"
                            ? "online"
                            : "danger"
                    }
                >

                    {trailingStop}

                </span>

            </div>

            {/* ============================================= */}
            {/* TIME LOCK */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    TIME LOCK
                </span>

                <span>

                    {timeLock}s

                </span>

            </div>

            {/* ============================================= */}
            {/* AUTO MANAGEMENT */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    AUTO MGMT
                </span>

                <span className="online">
                    ACTIVE
                </span>

            </div>

            {/* ============================================= */}
            {/* SURVIVABILITY */}
            {/* ============================================= */}

            <div className="compact-row">

                <span>
                    SURVIVABILITY
                </span>

                <span className="warning">
                    HIGH
                </span>

            </div>

            {/* ============================================= */}
            {/* QUICK PROFILE */}
            {/* ============================================= */}

            <div className="control-buttons">

                <button
                    className="start-button"
                    onClick={() => {

                        update(
                            "partial_tp",
                            "ON"
                        );

                        update(
                            "break_even",
                            "ON"
                        );

                        update(
                            "trailing_stop",
                            "ON"
                        );

                    }}
                >

                    SAFE

                </button>

                <button
                    className="stop-button"
                    onClick={() => {

                        update(
                            "partial_tp",
                            "OFF"
                        );

                        update(
                            "break_even",
                            "OFF"
                        );

                        update(
                            "trailing_stop",
                            "OFF"
                        );

                    }}
                >

                    RAW

                </button>

            </div>

        </>

    );

}