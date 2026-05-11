const safeNumber = (
  value,
  fallback = null
) => {

  if (
    value === null ||
    value === undefined
  ) {

    return fallback;

  }

  const n = Number(value);

  return Number.isFinite(n)
    ? n
    : fallback;

};

const safeBoolean = (
  value,
  fallback = false
) => {

  if (
    typeof value === "boolean"
  ) {

    return value;

  }

  if (
    value === "true" ||
    value === "1" ||
    value === 1
  ) {

    return true;

  }

  if (
    value === "false" ||
    value === "0" ||
    value === 0
  ) {

    return false;

  }

  return fallback;

};

const safeTimestamp = (
  value
) => {

  if (!value) {
    return null;
  }

  const ts =
    Number(value);

  if (
    Number.isFinite(ts)
  ) {

    return ts;

  }

  const parsed =
    new Date(value).getTime();

  return Number.isFinite(parsed)
    ? parsed
    : null;

};

export function realtimePacketBuilder(data) {

  // =========================
  // TIMESTAMP
  // =========================

  const timestamp =

    safeTimestamp(

      data.timestamp ??
      data.ts ??
      data.time

    );

  // =========================
  // SYNTHETIC PRICE
  // =========================

  const normalizedPrice =

    safeNumber(

      data.price ??

      data.markPrice ??

      data.lastPrice ??

      data.close ??

      data.c

    );

  // =========================
  // SYNTHETIC SPREAD
  // =========================

  const syntheticSpread =

    (
      safeNumber(data.ask) !== null &&
      safeNumber(data.bid) !== null
    )

      ? Math.abs(

        safeNumber(data.ask) -
        safeNumber(data.bid)

      )

      : null;

  const normalizedSpread =

    safeNumber(

      data.spread,

      syntheticSpread

    );

  // =========================
  // SYNTHETIC IMBALANCE
  // =========================

  const bidVolume =
    safeNumber(
      data.bidVolume ??
      data.bidQty ??
      data.bids
    );

  const askVolume =
    safeNumber(
      data.askVolume ??
      data.askQty ??
      data.asks
    );

  const syntheticImbalance =

    (
      bidVolume !== null &&
      askVolume !== null
    )

      ? (

        (
          bidVolume -
          askVolume
        ) /

        Math.max(
          1,
          bidVolume + askVolume
        )

      )

      : null;

  const normalizedImbalance =

    safeNumber(

      data.imbalance,

      syntheticImbalance

    );

  // =========================
  // SYNTHETIC MOMENTUM
  // =========================

  const normalizedMomentum =

    safeNumber(

      data.momentum ??

      data.priceChangePercent ??

      data.priceChange ??

      data.changePercent

    );

  // =========================
  // SYNTHETIC DELTA
  // =========================

  const syntheticDelta =

    (
      bidVolume !== null &&
      askVolume !== null
    )

      ? (
        bidVolume -
        askVolume
      )

      : null;

  const normalizedDelta =

    safeNumber(

      data.delta,

      syntheticDelta

    );

  // =========================
  // SYNTHETIC EDGE
  // =========================

  const syntheticEdge =

    (
      normalizedMomentum !== null &&
      normalizedImbalance !== null &&
      normalizedSpread !== null
    )

      ? (

        (
          Math.abs(
            normalizedMomentum
          ) * 0.4
        ) +

        (
          Math.abs(
            normalizedImbalance
          ) * 0.4
        ) +

        (
          normalizedSpread > 0
            ? (
              1 /
              (
                normalizedSpread * 100
              )
            )
            : 0
        ) * 0.2

      )

      : null;

  // =========================
  // MARKET PACKET
  // =========================

  const marketPacket = {

    timestamp,

    price:
      normalizedPrice,

    pnl:
      safeNumber(data.pnl),

    balance:
      safeNumber(
        data.balance,
        null
      ),

    equity:
      safeNumber(
        data.equity,
        null
      ),

    position:
      data.position ?? null,

    entryPrice:
      safeNumber(
        data.entryPrice
      ),

    botStatus:
      data.botStatus ??
      data.status ??
      null,

  };

  // =========================
  // STRATEGY PACKET
  // =========================

  const strategyPacket = {

    timestamp,

    imbalance:
      normalizedImbalance,

    momentum:
      normalizedMomentum,

    spread:
      normalizedSpread,

    edge:
      safeNumber(
        data.edge,
        syntheticEdge
      ),

    delta:
      normalizedDelta,

    cooldown:
      safeBoolean(
        data.cooldown
      ),

    entryReady:
      safeBoolean(
        data.entryReady
      ),

    signal:

      data.signal?.side === "BUY"

        ? "ENTER_LONG"

        : data.signal?.side === "SELL"

        ? "ENTER_SHORT"

        : null,

  };

  // =========================
  // EXECUTION PACKET
  // =========================

  const executionPacket = {

    timestamp,

    latency:
      safeNumber(
        data.latency ??
        data.ping
      ),

    orderStatus:
      data.orderStatus ?? null,

    wsStatus:
      data.wsStatus ?? null,

    engineStatus:
      data.engineStatus ?? null,

    executionMode:
      data.executionMode ?? null,

  };

  // =========================
  // RISK PACKET
  // =========================

  const riskPacket = {

    timestamp,

    currentDD:
      safeNumber(data.currentDD),

    dailyLoss:
      safeNumber(data.dailyLoss),

    lossStreak:
      safeNumber(data.lossStreak),

    riskLevel:
      data.riskLevel ?? null,

    killSwitch:
      safeBoolean(
        data.killSwitch
      ),

  };

  // =========================
  // INTELLIGENCE PACKET
  // =========================

  const intelligencePacket = {

    fakeWall:
      safeBoolean(
        data.fakeWall
      ),

    liquidityGrab:
      safeBoolean(
        data.liquidityGrab
      ),

    spoofProbability:
      safeNumber(

        data.spoofProbability ??

        data.manipulationRisk ??

        data.spoofRisk

      ),

    absorption:
      safeBoolean(
        data.absorption
      ),

    spreadExplosion:

      data.spreadExplosion !==
        undefined

        ? safeBoolean(
          data.spreadExplosion
        )

        : (
          normalizedSpread !== null &&
          normalizedSpread > 0.05
        ),

    confidenceScore:

      safeNumber(

        data.confidenceScore,

        syntheticEdge !== null

          ? Math.min(
            100,
            Math.round(
              syntheticEdge * 25
            )
          )

          : null

      ),

  };

  return {

    marketPacket,

    strategyPacket,

    executionPacket,

    riskPacket,

    intelligencePacket,

  };

}