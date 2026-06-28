// frontend/src/components/RiskPanel.jsx

/* =========================================================
   POSITION / RISK TERMINAL PANEL
========================================================= */

export default function RiskPanel({

    values = {},

    onChange = () => {},

}) {

    const handle = (
        key,
        value
    ) => {

        onChange({
            [key]: value,
        });

    };

    return (

        <div className="terminal-panel">

            {/* ============================================= */}
            {/* TITLE */}
            {/* ============================================= */}

            <div className="panel-title">

                POSITION / RISK（ポジション・リスク設定）

            </div>

            {/* ============================================= */}
            {/* MAX DD */}
            {/* ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    MAX DD

                </div>

                <div className="config-control">

                    <input
                        className="config-select"
                        type="number"
                        value={
                            values.maxDd ?? 5
                        }
                        onChange={(e) =>
                            handle(
                                "maxDd",
                                Number(
                                    e.target.value
                                )
                            )
                        }
                    />

                </div>

            </div>

            {/* ============================================= */}
            {/* POSITION SIZE */}
            {/* ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    POSITION SIZE

                </div>

                <div className="config-control">

                    <input
                        className="config-select"
                        type="number"
                        value={
                            values.positionSize ?? 100
                        }
                        onChange={(e) =>
                            handle(
                                "positionSize",
                                Number(
                                    e.target.value
                                )
                            )
                        }
                    />

                </div>

            </div>

            {/* ============================================= */}
            {/* TAKE PROFIT */}
            {/* ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    TP

                </div>

                <div className="config-control">

                    <input
                        className="config-select"
                        type="number"
                        step="0.1"
                        value={
                            values.tp ?? 1.0
                        }
                        onChange={(e) =>
                            handle(
                                "tp",
                                Number(
                                    e.target.value
                                )
                            )
                        }
                    />

                </div>

            </div>

            {/* ============================================= */}
            {/* STOP LOSS */}
            {/* ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    SL

                </div>

                <div className="config-control">

                    <input
                        className="config-select"
                        type="number"
                        step="0.1"
                        value={
                            values.sl ?? 1.0
                        }
                        onChange={(e) =>
                            handle(
                                "sl",
                                Number(
                                    e.target.value
                                )
                            )
                        }
                    />

                </div>

            </div>

            {/* ============================================= */}
            {/* TRAILING */}
            {/* ============================================= */}

            <div className="config-row">

                <div className="config-label">

                    TRAILING

                </div>

                <div className="config-control">

                    <select
                        className="config-select"
                        value={
                            values.trailing
                                ? "ON"
                                : "OFF"
                        }
                        onChange={(e) =>
                            handle(
                                "trailing",
                                e.target.value === "ON"
                            )
                        }
                    >

                        <option value="OFF">
                            OFF
                        </option>

                        <option value="ON">
                            ON
                        </option>

                    </select>

                </div>

            </div>

        </div>

    );

}