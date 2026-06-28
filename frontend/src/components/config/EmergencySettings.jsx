export default function EmergencySettings({

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

    const emergencyStop =
        config.emergency_stop || "ENABLED";

    const autoRiskStop =
        config.auto_risk_stop || "ON";

    const maxDailyLoss =
        config.max_daily_loss || 50;

    const maxTrades =
        config.max_trades || 20;

    return (

        <>

            <div className="compact-row">

                <span>
                    RISK STATUS
                </span>

                <span className="warning">
                    MONITORING
                </span>

            </div>

            <div className="compact-row">

                <span>
                    EMERGENCY STOP
                </span>

                <span
                    className={
                        emergencyStop === "ENABLED"
                            ? "online"
                            : "danger"
                    }
                >

                    {emergencyStop}

                </span>

            </div>

            <div className="compact-row">

                <span>
                    AUTO RISK STOP
                </span>

                <span
                    className={
                        autoRiskStop === "ON"
                            ? "online"
                            : "warning"
                    }
                >

                    {autoRiskStop}

                </span>

            </div>

            <div className="compact-row">

                <span>
                    DAILY LOSS LIMIT
                </span>

                <span className="danger">

                    {maxDailyLoss} USDT

                </span>

            </div>

            <div className="compact-row">

                <span>
                    MAX EXECUTIONS
                </span>

                <span className="warning">

                    {maxTrades}

                </span>

            </div>

            <div className="compact-row">

                <span>
                    RECOVERY MODE
                </span>

                <span className="warning">
                    STANDBY
                </span>

            </div>

            <div className="compact-row">

                <span>
                    POSITION CLOSE
                </span>

                <span className="online">
                    AVAILABLE
                </span>

            </div>

            <div className="compact-row">

                <span>
                    CIRCUIT BREAKER
                </span>

                <span className="online">
                    ENABLED
                </span>

            </div>

            <div className="control-buttons">

                <button
                    className="start-button"
                    onClick={() => {

                        update(
                            "emergency_stop",
                            "ENABLED"
                        );

                        update(
                            "auto_risk_stop",
                            "ON"
                        );

                    }}
                >

                    CONSERVATIVE

                </button>

                <button
                    className="stop-button"
                    onClick={() => {

                        update(
                            "emergency_stop",
                            "DISABLED"
                        );

                        update(
                            "auto_risk_stop",
                            "OFF"
                        );

                    }}
                >

                    AGGRESSIVE

                </button>

            </div>

        </>

    );

}