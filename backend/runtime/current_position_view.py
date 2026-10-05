"""Display-only projections. Never queried by execution or risk authorities.

Timestamps are Unix seconds; durations are milliseconds. Missing facts remain
None. KuCoin fields follow the Classic Futures Get Position List contract:
https://www.kucoin.com/docs-new/rest/futures-trading/positions/get-position-list
"""
import math


def numeric(value, *, positive=False):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) and (not positive or result > 0) else None


def timestamp(value):
    value = numeric(value, positive=True)
    return value / 1000 if value is not None and value >= 1e12 else value


def direction(value):
    return {"BUY": ("LONG", "BUY"), "LONG": ("LONG", "BUY"),
            "SELL": ("SHORT", "SELL"), "SHORT": ("SHORT", "SELL")}.get(
                str(value).upper(), (None, None))


def control(value):
    return value if value in ("MANUAL", "BOT") else "UNKNOWN"


def kucoin_position_observation(rows, observed_at):
    """Retain all rows from an already completed GET, without another request.

    Invalid quantity/shape invalidates coverage: it must not become a flat
    account. No raw account payload or credentials are exposed.
    """
    if not isinstance(rows, list):
        return {"positions": None, "sourceUpdatedAt": observed_at}
    positions = []
    fields = ("id", "symbol", "currentQty", "avgEntryPrice", "markPrice",
              "markValue", "unrealisedPnl", "realLeverage", "posMargin",
              "liquidationPrice", "openingTimestamp", "isInverse", "positionSide")
    for row in rows:
        if not isinstance(row, dict) or numeric(row.get("currentQty")) is None:
            return {"positions": None, "sourceUpdatedAt": observed_at}
        if numeric(row["currentQty"]) != 0:
            positions.append({key: row[key] for key in fields if key in row})
    return {"positions": positions, "sourceUpdatedAt": observed_at}


def empty_position(mode, now):
    result = dict.fromkeys((
        "symbol", "side", "orderSide", "quantity", "quantityUnit",
        "contractQuantity", "coinQuantity", "entryPrice", "markPrice",
        "markPriceSource", "positionValue", "unrealizedPnl", "unrealizedPnlSource",
        "leverage", "marginUsed", "liquidationPrice", "entryTime", "holdingMs",
        "sourceUpdatedAt", "positionId"))
    result.update(status="UNKNOWN", mode=mode, control="UNKNOWN",
                  source="PAPER_SIMULATION" if mode == "PAPER" else
                  "KUCOIN_FUTURES" if mode == "LIVE" else "UNKNOWN",
                  freshness="UNKNOWN", generatedAt=now, reason=None, positions=[])
    return result


def current_position(account, mode, *, now, symbol=None, current_price=None,
                     observation=None, maximum_age=90):
    """Pure projection of one mode's canonical snapshot, never an order side.

    positions contains all observed LIVE positions. Ambiguous selection yields
    UNKNOWN with reason MULTIPLE_POSITIONS, without changing execution's model.
    """
    mode = str(mode).upper()
    view = empty_position(mode if mode in ("PAPER", "LIVE") else None, now)
    if mode not in ("PAPER", "LIVE") or not isinstance(account, dict):
        return view
    paper = mode == "PAPER"
    observed = isinstance(observation, dict) and not paper
    updated = timestamp(observation.get("sourceUpdatedAt") if observed else
                        account.get("lastUpdate" if paper else "lastSync"))
    view["sourceUpdatedAt"] = updated
    if account.get("stale") is True or (updated is not None and now - updated > maximum_age):
        view.update(freshness="STALE", reason="STALE_SOURCE")
        return view
    if updated is None or updated > now:
        view["reason"] = "SOURCE_NOT_CURRENT"
        return view
    if (paper and account.get("available") is not True) or (
            not paper and account.get("authenticated") is not True):
        return view
    if observed:
        rows = observation.get("positions")
    elif paper:
        rows = account.get("positions")
        if rows is None and "position" in account:
            rows = [] if account["position"] is None else [account["position"]]
    else:
        rows = account.get("positions")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        view["reason"] = "POSITION_SOURCE_UNAVAILABLE"
        return view
    view["freshness"] = "FRESH"
    if not rows:
        if paper and account.get("positionState") != "FLAT":
            view["reason"] = "POSITION_STATE_AMBIGUOUS"
        else:
            view["status"] = "FLAT"
        return view

    projections = []
    for position in rows:
        item = empty_position(mode, now)
        item.pop("positions")
        item.update(freshness="FRESH", sourceUpdatedAt=updated)
        context = position.get("runtimeSymbolContext")
        context = context if isinstance(context, dict) else {}
        item["symbol"] = position.get("symbol") or (context.get("symbol") or
                            context.get("exchangeSymbol") or symbol if paper else None)
        qty = numeric(position.get("currentQty" if observed else "qty"))
        side = ("BUY" if qty > 0 else "SELL") if observed and qty else position.get("side")
        if observed and position.get("positionSide") in ("LONG", "SHORT"):
            side = position["positionSide"]
        item["side"], item["orderSide"] = direction(side)
        item["contractQuantity"] = abs(qty) if qty is not None and qty != 0 else None
        if paper:
            coin = numeric(position.get("coin_qty"), positive=True)
            multiplier = numeric(position.get("multiplier"), positive=True)
            if coin is None and multiplier is not None and item["contractQuantity"] is not None:
                coin = numeric(multiplier * item["contractQuantity"], positive=True)
            item["coinQuantity"] = coin
        item["quantity"] = item["coinQuantity"] if item["coinQuantity"] is not None else item["contractQuantity"]
        item["quantityUnit"] = ("coin" if item["coinQuantity"] is not None else
                                "contract" if item["contractQuantity"] is not None else None)
        item["entryPrice"] = numeric(position.get("avgEntryPrice" if observed else "entry_price"), positive=True)
        item["markPrice"] = numeric(current_price if paper and item["symbol"] == symbol else
                                    position.get("markPrice") if observed else None, positive=True)
        if item["markPrice"] is not None:
            item["markPriceSource"] = "SIMULATION_CURRENT_PRICE" if paper else "KUCOIN_MARK_PRICE"
        if paper and item["coinQuantity"] is not None and item["markPrice"] is not None:
            item["positionValue"] = numeric(item["coinQuantity"] * item["markPrice"])
        elif observed:
            value = numeric(position.get("markValue"))
            item["positionValue"] = abs(value) if value is not None else None
        item["unrealizedPnl"] = numeric(account.get("unrealizedPnl") if paper and len(rows) == 1 else
                                        position.get("unrealisedPnl") if observed else None)
        if item["unrealizedPnl"] is not None:
            item["unrealizedPnlSource"] = "PAPER_SIMULATION" if paper else "KUCOIN_POSITION"
        if observed:
            for target, source in (("leverage", "realLeverage"), ("marginUsed", "posMargin"),
                                   ("liquidationPrice", "liquidationPrice")):
                value = numeric(position.get(source))
                item[target] = value if value is not None and value >= 0 else None
        item["entryTime"] = timestamp(position.get("entry_time") if paper else
                                      position.get("openingTimestamp") if observed else None)
        if item["entryTime"] is not None and item["entryTime"] <= now:
            item["holdingMs"] = (now - item["entryTime"]) * 1000
        elif item["entryTime"] is not None:
            item["entryTime"] = None
        item["control"] = control(position.get("entry_authority")) if paper else "UNKNOWN"
        identity = position.get("id") if observed else position.get("position_id") or position.get("order_id")
        item["positionId"] = str(identity) if identity is not None else None
        if item["symbol"] and item["side"] and item["quantity"] is not None:
            item["status"] = "OPEN"
        projections.append(item)
    view["positions"] = projections if not paper else []
    candidates = [item for item in projections if item["symbol"] == symbol] if symbol else projections
    if len(candidates) != 1:
        view["reason"] = "MULTIPLE_POSITIONS" if len(projections) > 1 else "SYMBOL_CONTEXT_MISMATCH"
        return view
    return {**candidates[0], "positions": view["positions"]}


def last_position_event(service, mode):
    """Latest completed trade only; no new store and no inferred OPEN event."""
    mode = str(mode).upper()
    view = dict.fromkeys(("symbol", "side", "orderSide", "quantity", "entryPrice", "exitPrice",
                          "openedAt", "closedAt", "holdingMs", "realizedPnl", "exitReason", "tradeId"))
    view.update(event="UNKNOWN", mode=mode if mode in ("PAPER", "LIVE") else None,
                control="UNKNOWN", source="PARAMETER_PERFORMANCE_TRADE_HISTORY",
                quantityUnit=None, realizedPnlAuthoritative=None)
    if mode not in ("PAPER", "LIVE"):
        return view
    try:
        result = service.history(mode=mode.lower(), scope=mode, period="all",
                                 sort="exitTimestamp", direction="desc", page_size=1)
        records = result.get("records")
        if getattr(getattr(service, "store", None), "read_failed", False) is True:
            return view
        if not isinstance(records, list):
            return view
        if not records:
            view["event"] = "NONE"
            return view
        row = records[0]
        if row.get("mode") != mode.lower() or timestamp(row.get("exitTimestamp")) is None:
            return view
        view.update(event="CLOSED", symbol=row.get("symbol"), control=control(row.get("controlSource")),
                    tradeId=row.get("tradeId"), exitReason=row.get("exitReason"), quantityUnit="coin")
        view["side"], view["orderSide"] = direction(row.get("side"))
        for key in ("quantity", "entryPrice", "exitPrice", "holdingMs"):
            view[key] = numeric(row.get(key))
        view["openedAt"] = timestamp(row.get("entryTimestamp"))
        view["closedAt"] = timestamp(row.get("exitTimestamp"))
        authoritative = row.get("realizedPnlAuthoritative") is True
        view["realizedPnlAuthoritative"] = authoritative
        if mode == "PAPER" or authoritative:
            view["realizedPnl"] = numeric(row.get("realizedPnl"))
    except Exception:
        # Observation failures never affect execution or account availability.
        pass
    return view
