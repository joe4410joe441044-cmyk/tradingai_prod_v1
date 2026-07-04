#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

SERVER_JSON="$(curl -s http://127.0.0.1:8001/)"
STATUS_JSON="$(curl -s http://127.0.0.1:8001/api/bot/status)"

echo "======================================"
echo " TradingAI Runtime Monitor"
echo "======================================"

SERVER_RUNTIME="$(echo "$SERVER_JSON" | jq -r '.runtime // .status // "N/A"')"

echo "$STATUS_JSON" | jq -r --arg server_runtime "$SERVER_RUNTIME" '
  def v($x): if $x == null then "N/A" else ($x|tostring) end;

  . as $root
  | ($root.runtime_health // $root.runtimeHealth // {}) as $rh
  | ($rh.bot // {}) as $bot
  | ($rh.runtimeEngine // $rh.tradingRuntime // {}) as $trading
  | ($rh.executionAuthority // {}) as $auth
  | ($rh.executionEngine // {}) as $engine
  | ($rh.tradingDecision // {}) as $decision

  | "Bot State:             " + v($bot.status // $root.status)
  , "Symbol:                " + v($root.symbol)
  , "Mode:                  " + v($root.execution_mode // $root.mode)
  , "Server Runtime:        " + v($server_runtime)
  , "Browser WS:            " + v($rh.browserWebSocket.status // $rh.browserWs // $rh.browserWS // $rh.browser_ws)
  , "Exchange WS:           " + v($rh.exchangeWebSocket.status // $rh.exchangeWs // $rh.exchangeWS // $rh.exchange_ws)
  , "Trading Runtime:       " + v($trading.status // $trading.state // $rh.runtimeEngine // $rh.tradingRuntime)
  , "Pipeline:              " + v($rh.pipeline.status // $rh.pipelineStatus // $rh.pipeline)
  , "Health Severity:       " + v($rh.severity // $rh.healthSeverity // $rh.status)
  , "Blocking Reason:       " + v($rh.blockingReason)
  , "Execution Authority:   " + v($auth.status // $auth.enabled)
  , "Execution Engine:      " + v($engine.status)
  , "Execution Available:   " + v($engine.available)
  , "Execution Enabled:     " + v($engine.enabled)
  , "Execution Allowed:     " + v($engine.allowed)
  , "Current Decision:      " + v($rh.tradingAction.decision // $decision.current // $root.aiDecision)
  , "Trading Action:        " + v($rh.tradingAction.status // $decision.tradingAction // $rh.tradingAction)
  , "Action Reason:         " + v($rh.tradingAction.reason // $decision.reason // $rh.actionReason)
  , "Last Completed:        " + v($rh.lastCompletedDecision // $decision.lastCompleted)
  , "Snapshot ID:           " + v($rh.snapshotId)
  , "Lifecycle Revision:    " + v($rh.lifecycleRevision)
  , "Generated At:          " + v($rh.generatedAt)
'

echo "======================================"
