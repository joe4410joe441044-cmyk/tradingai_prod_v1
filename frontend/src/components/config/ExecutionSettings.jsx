export default function ExecutionSettings({

    config = {},
    setConfig = () => {},

}) {

    const update = (
        key,
        value
    ) => {

        setConfig({

            ...config,

            [key]: value,

        });

    };

    return (

        <>

            <div className="compact-row">

                <span>
                    EXECUTION MODE
                </span>

                <span className="online">
                    STANDARD
                </span>

            </div>

            <div className="compact-row">

                <span>
                    ROUTER MODE
                </span>

                <span className="online">
                    AUTOMATIC
                </span>

            </div>

            <div className="compact-row">

                <span>
                    EXECUTION STATE
                </span>

                <span className="online">
                    ACTIVE
                </span>

            </div>

            <div className="compact-row">

                <span>
                    COOLDOWN
                </span>

                <span>
                    {
                        config.cooldown || 2
                    }s
                </span>

            </div>

            <div className="compact-row">

                <span>
                    ENTRY LIMIT
                </span>

                <span>
                    {
                        config.max_entries || 5
                    }
                </span>

            </div>

            <div className="compact-row">

                <span>
                    REENTRY DELAY
                </span>

                <span>
                    {
                        config.reentry_delay || 3
                    }s
                </span>

            </div>

            <div className="compact-row">

                <span>
                    SINGLE SIGNAL
                </span>

                <span
                    className={
                        config.one_signal_only === "OFF"
                            ? "warning"
                            : "online"
                    }
                >

                    {
                        config.one_signal_only || "ON"
                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    SIGNAL LOCK
                </span>

                <span
                    className={
                        config.signal_lock === "OFF"
                            ? "warning"
                            : "online"
                    }
                >

                    {
                        config.signal_lock || "ON"
                    }

                </span>

            </div>

            <div className="compact-row">

                <span>
                    EXECUTION PROFILE
                </span>

                <span className="online">
                    BALANCED
                </span>

            </div>

            <div className="compact-row">

                <span>
                    LATENCY MODE
                </span>

                <span>
                    LOW LATENCY
                </span>

            </div>

            <div className="control-buttons">

                <button
                    className="start-button"
                    onClick={() =>
                        update(
                            "execution_profile",
                            "CONSERVATIVE"
                        )
                    }
                >

                    CONSERVATIVE

                </button>

                <button
                    className="stop-button"
                    onClick={() =>
                        update(
                            "execution_profile",
                            "AGGRESSIVE"
                        )
                    }
                >

                    AGGRESSIVE

                </button>

            </div>

        </>

    );

}