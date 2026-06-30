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

                    MAX DD（最大ドローダウン）

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

                    POSITION SIZE（ポジションサイズ）

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

                    TP（利確）

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

                    SL（損切り）

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

                    TRAILING（トレーリング）

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
                            OFF（無効）
                        </option>

                        <option value="ON">
                            ON（有効）
                        </option>

                    </select>

                </div>

            </div>

        </div>

    );

}
