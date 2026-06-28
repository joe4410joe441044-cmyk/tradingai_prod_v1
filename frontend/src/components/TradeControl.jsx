import React from "react";

import {
  telemetryStore,
} from "../store/telemetryStore";

import {
  setExecutionEnabled,
} from "../runtime/governanceRuntime";

export default function TradeControl() {

  // =====================================
  // GOVERNANCE RUNTIME
  // =====================================

  const governance =
    telemetryStore.governance || {};

  const execution =
    telemetryStore.execution || {};

  // =====================================
  // BACKEND AUTHORITATIVE STATE
  // =====================================

  const mode =
    governance.mode || "PAPER";

  const executionEnabled =
    governance.execution_enabled === true;

  const connected =
    execution.connected === true;

  // =====================================
  // GOVERNANCE ACTION
  // =====================================

  const toggleExecution =
    async () => {

    // 🚨 REAL execution confirmation
    if (
      mode === "LIVE" &&
      executionEnabled === false
    ) {

      const ok = window.confirm(
        "⚠️ REAL TRADING を有効化します。\n本当に EXECUTION を ENABLE にしますか？"
      );

      if (!ok) {

        return;

      }

    }

    try {

      await setExecutionEnabled(
        !executionEnabled
      );

      console.log(
        "EXECUTION TOGGLE:",
        !executionEnabled
      );

    } catch (err) {

      console.error(
        "EXECUTION TOGGLE ERROR:",
        err
      );

    }

  };

  return (

    <div
      style={{
        border: "1px solid #ccc",
        padding: "10px",
        marginTop: "10px"
      }}
    >

      <h4>Control</h4>

      {/* =====================================
          GOVERNANCE STATUS
      ===================================== */}

      <p>

        BOT:{" "}

        <b
          style={{
            color:
              connected
                ? "green"
                : "red"
          }}
        >

          {
            connected
              ? "CONNECTED"
              : "DISCONNECTED"
          }

        </b>

      </p>

      <p>

        MODE:{" "}

        <b
          style={{
            color:
              mode === "LIVE"
                ? "red"
                : "green"
          }}
        >

          {mode}

        </b>

      </p>

      <p>

        EXECUTION:{" "}

        <b
          style={{
            color:
              executionEnabled
                ? "red"
                : "green"
          }}
        >

          {
            executionEnabled
              ? "LIVE ENABLED"
              : "BLOCKED"
          }

        </b>

      </p>

      {/* =====================================
          GOVERNANCE ACTION
      ===================================== */}

      <button
        onClick={toggleExecution}
      >

        {
          executionEnabled
            ? "Disable Execution"
            : "Enable Execution"
        }

      </button>

      {/* =====================================
          LIVE WARNING
      ===================================== */}

      {

        executionEnabled && (

          <div
            style={{
              color: "red",
              fontWeight: "bold"
            }}
          >

            ⚠️ REAL TRADING ACTIVE

          </div>

        )

      }

    </div>

  );

}