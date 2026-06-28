import React from "react";

export default function QuickActions() {

    return (

        <div className="terminal-panel">

            {/* =============================================
               TITLE
            ============================================= */}

            <div className="panel-title">

                QUICK ACTIONS（クイック操作）

            </div>

            {/* =============================================
               ACTION GRID
            ============================================= */}

            <div className="quick-actions-grid">

                <button className="quick-action-button flatten">

                    FLATTEN NOW（全決済）

                </button>

                <button className="quick-action-button cancel">

                    CANCEL ALL（全キャンセル）

                </button>

                <button className="quick-action-button reset">

                    RESET BOT（BOTリセット）

                </button>

                <button className="quick-action-button safe">

                    SAFE MODE（安全モード）

                </button>

            </div>

        </div>

    );

}