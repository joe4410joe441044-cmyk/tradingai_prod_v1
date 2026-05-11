import {
  createExchangeAdapter
} from "../exchangeAdapter";

export function createKucoinAdapter() {

  const baseAdapter =
    createExchangeAdapter({
      exchangeName: "KUCOIN",
    });

  function connectKucoin() {

    return baseAdapter.connectExchange();

  }

  function disconnectKucoin() {

    return baseAdapter.disconnectExchange();

  }

  function authenticateKucoin({
    apiKey,
    apiSecret,
    apiPassphrase,
  } = {}) {

    return baseAdapter.authenticateExchange({
      apiKey,
      apiSecret,
      passphrase:
        apiPassphrase,
    });

  }

  function placeKucoinOrder({
    symbol,
    side,
    quantity,
    leverage = 1,
    reduceOnly = false,
    marginMode = "cross",
    orderType = "MARKET",
  } = {}) {

    return baseAdapter.placeOrder({
      symbol,
      side,
      quantity,
      reduceOnly,
      orderType,
      leverage,
      marginMode,
    });

  }

  function closeKucoinPosition({
    symbol,
  } = {}) {

    return baseAdapter.closePosition({
      symbol,
    });

  }

  function reduceKucoinPosition({
    symbol,
    reductionSize,
  } = {}) {

    return baseAdapter.reducePosition({
      symbol,
      reductionSize,
    });

  }

  function cancelKucoinOrder({
    orderId,
  } = {}) {

    return baseAdapter.cancelOrder({
      orderId,
    });

  }

  function syncKucoinPosition({
    position,
  } = {}) {

    return baseAdapter.syncExchangePosition({
      position,
    });

  }

  function syncKucoinBalance({
    balance,
  } = {}) {

    return baseAdapter.syncExchangeBalance({
      balance,
    });

  }

  function verifyKucoinExecution({
    localExecution,
    exchangeExecution,
  } = {}) {

    return baseAdapter.verifyExchangeExecution({
      localExecution,
      exchangeExecution,
    });

  }

  function createKucoinTelemetryPacket() {

    return {

      exchange:
        "KUCOIN",

      ...baseAdapter.createExchangeTelemetryPacket(),

    };

  }

  function getKucoinState() {

    return baseAdapter.getExchangeState();

  }

  return {

    connectKucoin,

    disconnectKucoin,

    authenticateKucoin,

    placeKucoinOrder,

    closeKucoinPosition,

    reduceKucoinPosition,

    cancelKucoinOrder,

    syncKucoinPosition,

    syncKucoinBalance,

    verifyKucoinExecution,

    createKucoinTelemetryPacket,

    getKucoinState,

  };

}
