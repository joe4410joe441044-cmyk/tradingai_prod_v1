export function adaptiveEngine({

  riskPacket,
  executionPacket,
  intelligencePacket,

  volatilityRegime,
  liquidityStability,
  momentumRegime,

  avgSpread,

}) {

  return {

    // =========================
    // ADAPTIVE ENGINE
    // =========================

    adaptiveEntryState:

      riskPacket.killSwitch

        ? "BLOCKED"

        : executionPacket.latency > 120

        ? "BLOCKED"

        : liquidityStability === "COLLAPSING"

        ? "LIMITED"

        : volatilityRegime === "EXTREME VOL"

        ? "LIMITED"

        : "ALLOWED",

    adaptiveRiskLevel:

      intelligencePacket.spoofProbability > 80 ||

      executionPacket.latency > 120 ||

      volatilityRegime === "EXTREME VOL"

        ? "CRITICAL"

        : intelligencePacket.spoofProbability > 50 ||

          liquidityStability === "COLLAPSING"

        ? "HIGH"

        : "NORMAL",

    executionPermission:

      !riskPacket.killSwitch &&

      executionPacket.latency < 120 &&

      liquidityStability !== "COLLAPSING",

    emergencyState:

      riskPacket.killSwitch ||

      executionPacket.latency > 150 ||

      intelligencePacket.spoofProbability > 90,

    aiDecision:

      riskPacket.killSwitch

        ? "EMERGENCY BLOCK"

        : executionPacket.latency > 120

        ? "EXECUTION BLOCK"

        : liquidityStability === "COLLAPSING"

        ? "LIMIT ENTRY"

        : volatilityRegime === "EXTREME VOL"

        ? "RISK CONTROL"

        : momentumRegime === "EXPLOSIVE"

        ? "TREND ENTRY"

        : "NORMAL FLOW",

    // =========================
    // AUTO DEFENSE
    // =========================

    autoDefenseState:

      intelligencePacket.spreadExplosion ||

      executionPacket.latency > 150 ||

      intelligencePacket.spoofProbability > 90

        ? "ACTIVE"

        : "NORMAL",

    dynamicRiskMultiplier:

      volatilityRegime === "EXTREME VOL"

        ? 0.25

        : liquidityStability === "COLLAPSING"

        ? 0.5

        : executionPacket.latency > 100

        ? 0.7

        : 1,

    autoCooldownTrigger:

      executionPacket.latency > 120 ||

      intelligencePacket.spreadExplosion ||

      intelligencePacket.spoofProbability > 80,

    spreadDefenseMode:

      avgSpread > 2

        ? "EMERGENCY"

        : avgSpread > 1

        ? "DEFENSIVE"

        : "NORMAL",

    executionThrottle:

      executionPacket.latency > 150

        ? "HARD LIMIT"

        : executionPacket.latency > 100

        ? "SOFT LIMIT"

        : "FULL SPEED",

    defenseReason:

      intelligencePacket.spreadExplosion

        ? "SPREAD EXPLOSION"

        : intelligencePacket.spoofProbability > 90

        ? "SPOOF DETECTED"

        : executionPacket.latency > 150

        ? "LATENCY CRITICAL"

        : liquidityStability === "COLLAPSING"

        ? "LIQUIDITY COLLAPSE"

        : "NONE",

  };

}