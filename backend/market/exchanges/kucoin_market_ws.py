# -*- coding: utf-8 -*-

import websocket
import json
import threading
import time
import requests
import uuid
import math

from backend.utils.log_buffer import add_log, logger, ws_debug


def normalize_futures_symbol(symbol):

    normalized_symbol = str(symbol).strip().upper()

    mapping = {
        "BTCUSDT": "XBTUSDTM",
        "XBTUSDT": "XBTUSDTM",
        "ETHUSDT": "ETHUSDTM",
        "XRPUSDT": "XRPUSDTM",
    }

    if normalized_symbol in mapping:
        return mapping[normalized_symbol]

    if normalized_symbol.endswith("USDTM"):
        return normalized_symbol

    if normalized_symbol.endswith("USDT"):
        return f"{normalized_symbol}M"

    return normalized_symbol


class OrderBookWS:

    MARKET_TYPE = "FUTURES"
    BROWSER_BOOK_DEPTH = 20

    def normalize_symbol(self, symbol):

        normalized = normalize_futures_symbol(symbol)

        ws_debug(
            "KuCoin symbol map '%s' -> '%s'",
            symbol,
            normalized,
        )

        return normalized

    def __init__(
        self,
        symbol,
        on_update,
        runtime_id,
    ):

        self.original_symbol = symbol.upper()

        self.symbol = self.normalize_symbol(
            self.original_symbol
        )

        self.url = None

        self.on_update = on_update

        self.runtime_id = runtime_id

        self.ws = None

        self.last_price = 0.0

        self.best_bid = 0.0

        self.best_ask = 0.0

        self.spread = 0.0

        # =========================
        # LAST VALID BOOK
        # =========================

        self.last_valid_bid = 0.0

        self.last_valid_ask = 0.0

        self.connected = False

        self.last_price_update = time.time()

        # Debug-only counters for tracing the accepted WS price path.
        self.ws_update_count = 0

        self.last_ws_receive_time = None

        self.running = False

        # =========================
        # LOCAL ORDERBOOK
        # =========================

        self.bids = {}

        self.asks = {}

        # =========================
        # SEQUENCE
        # =========================

        self.snapshot_loaded = False

        self.orderbook_initialized = False

        self.snapshot_sequence = 0

        self.last_sequence_end = None

        self.resnapshot_required = False

        self.is_orderbook_synced = False

        self.cached_diffs = []

        self.sequence_gap_count = 0

        self.last_sequence_gap = None

        self.resync_count = 0

        self.cached_diff_count = 0

        self.replayed_diff_count = 0

        self.dropped_old_diff_count = 0

        self._orderbook_lock = threading.RLock()

        self._sync_in_progress = False

        self._sync_generation = 0

    # =========================
    # LOAD SNAPSHOT
    # =========================

    def load_snapshot(self, is_resync=False, generation=None):

        if generation is None:
            generation = self._sync_generation

        with self._orderbook_lock:
            if generation != self._sync_generation:
                return False

            self.snapshot_loaded = False
            self.is_orderbook_synced = False

        try:

            url = (
                "https://api-futures.kucoin.com"
                f"/api/v1/level2/snapshot?symbol={self.symbol}"
            )

            ws_debug(
                "Requesting KuCoin orderbook snapshot url=%s",
                url,
            )

            response = requests.get(
                url,
                timeout=10
            )

            data = response.json()

            ws_debug(
                "KuCoin snapshot response=%s",
                data,
            )

            snapshot = data.get("data", {})
            snapshot_sequence = int(snapshot["sequence"])
            snapshot_bids = {
                float(price): float(size)
                for price, size in snapshot.get("bids", [])
            }
            snapshot_asks = {
                float(price): float(size)
                for price, size in snapshot.get("asks", [])
            }

            if not snapshot_bids or not snapshot_asks:
                raise ValueError("snapshot orderbook is empty")

            replayed_diff = None

            with self._orderbook_lock:
                if generation != self._sync_generation:
                    return False

                self.bids = snapshot_bids
                self.asks = snapshot_asks
                self.snapshot_sequence = snapshot_sequence
                self.last_sequence_end = snapshot_sequence

                cached_diffs = sorted(
                    self.cached_diffs,
                    key=lambda item: (
                        item["sequence_start"],
                        item["sequence_end"],
                    ),
                )
                self.cached_diffs = []

                for diff in cached_diffs:
                    result = self._apply_sequenced_diff_locked(
                        diff,
                        replay=True,
                    )

                    if result == "gap":
                        self.bids = {}
                        self.asks = {}
                        self.last_sequence_end = None
                        self.resnapshot_required = True
                        return False

                    if result == "applied":
                        replayed_diff = diff

                if not self._refresh_book_metrics_locked():
                    raise ValueError("snapshot replay produced invalid book")

                self.snapshot_loaded = True
                self.orderbook_initialized = True
                self.is_orderbook_synced = True
                self.resnapshot_required = False

                if is_resync:
                    self.resync_count += 1

                debug = self._get_orderbook_debug_locked()

            add_log(
                f"📸 SNAPSHOT SYNCED "
                f"bids={len(snapshot_bids)} "
                f"asks={len(snapshot_asks)} "
                f"snapshotSequence={debug['snapshotSequence']} "
                f"lastSequenceEnd={debug['lastSequenceEnd']} "
                f"sequenceGapCount={debug['sequenceGapCount']} "
                f"resyncCount={debug['resyncCount']}"
            )

            ws_debug(
                "KuCoin snapshot bid_levels=%s ask_levels=%s debug=%s",
                sorted(self.bids.keys(), reverse=True)[:10],
                sorted(self.asks.keys())[:10],
                debug,
            )

            if replayed_diff is not None:
                self._publish_current_book(replayed_diff)

            return True

        except Exception as e:

            add_log(
                f"❌ SNAPSHOT LOAD ERROR: {e}",
                "error"
            )

            return False

    def _start_snapshot_sync(self, is_resync=False):

        with self._orderbook_lock:
            if self._sync_in_progress:
                return

            is_resync = is_resync or self.resnapshot_required
            self._sync_in_progress = True
            generation = self._sync_generation

        threading.Thread(
            target=self._snapshot_sync_worker,
            args=(generation, is_resync),
            daemon=True,
        ).start()

    def _snapshot_sync_worker(self, generation, is_resync):

        try:
            resync_attempt = is_resync

            for attempt in range(3):
                if self.load_snapshot(
                    is_resync=resync_attempt,
                    generation=generation,
                ):
                    return

                with self._orderbook_lock:
                    if generation != self._sync_generation:
                        return

                    resync_attempt = (
                        resync_attempt
                        or self.resnapshot_required
                    )

                if attempt < 2:
                    time.sleep(0.1)
        finally:
            with self._orderbook_lock:
                if generation == self._sync_generation:
                    self._sync_in_progress = False

    def _parse_diff(self, message_data):

        sequence = message_data.get("sequence")
        sequence_start = message_data.get(
            "sequenceStart",
            sequence,
        )
        sequence_end = message_data.get(
            "sequenceEnd",
            sequence,
        )

        if sequence_start is None or sequence_end is None:
            raise ValueError("delta missing sequence")

        change = message_data.get("change")

        if not change:
            raise ValueError("delta missing change")

        price, side, size = change.split(",")

        if side not in ("buy", "sell"):
            raise ValueError(f"unsupported side: {side}")

        return {
            "sequence_start": int(sequence_start),
            "sequence_end": int(sequence_end),
            "price": float(price),
            "side": side,
            "size": float(size),
        }

    def _record_sequence_gap_locked(self, diff):

        previous_sequence = self.last_sequence_end
        gap_size = (
            diff["sequence_start"]
            - previous_sequence
            - 1
        )

        self.sequence_gap_count += 1
        self.last_sequence_gap = {
            "previousLastSequenceEnd": previous_sequence,
            "incomingSequenceStart": diff["sequence_start"],
            "incomingSequenceEnd": diff["sequence_end"],
            "gapSize": gap_size,
            "timestamp": time.time(),
        }

        add_log(
            f"⚠️ KUCOIN SEQUENCE GAP "
            f"previous={previous_sequence} "
            f"incomingStart={diff['sequence_start']} "
            f"incomingEnd={diff['sequence_end']} "
            f"gapSize={gap_size}",
            "warning",
        )

    def _apply_sequenced_diff_locked(self, diff, replay=False):

        if self.last_sequence_end is None:
            return "gap"

        if diff["sequence_end"] <= self.last_sequence_end:
            self.dropped_old_diff_count += 1
            return "old"

        if diff["sequence_start"] > self.last_sequence_end + 1:
            self._record_sequence_gap_locked(diff)
            return "gap"

        book = self.bids if diff["side"] == "buy" else self.asks

        if diff["size"] <= 0:
            book.pop(diff["price"], None)
        else:
            book[diff["price"]] = diff["size"]

        self.last_sequence_end = diff["sequence_end"]

        if replay:
            self.replayed_diff_count += 1

        return "applied"

    def _refresh_book_metrics_locked(self):

        if not self.bids or not self.asks:
            return False

        self.best_bid = max(self.bids)
        self.best_ask = min(self.asks)

        if (
            self.best_bid <= 0
            or self.best_ask <= 0
            or self.best_bid >= self.best_ask
        ):
            return False

        self.spread = self.best_ask - self.best_bid
        self.last_price = (self.best_bid + self.best_ask) / 2
        return True

    def _get_orderbook_debug_locked(self):

        return {
            "snapshotSequence": self.snapshot_sequence,
            "lastSequenceEnd": self.last_sequence_end,
            "wsUpdateCount": self.ws_update_count,
            "sequenceGapCount": self.sequence_gap_count,
            "lastSequenceGap": self.last_sequence_gap,
            "resyncCount": self.resync_count,
            "isOrderbookSynced": self.is_orderbook_synced,
            "cachedDiffCount": self.cached_diff_count,
            "pendingCachedDiffCount": len(self.cached_diffs),
            "replayedDiffCount": self.replayed_diff_count,
            "droppedOldDiffCount": self.dropped_old_diff_count,
        }

    def _browser_book_snapshot_locked(self, timestamp):

        bids = sorted(
            self.bids.items(),
            key=lambda level: level[0],
            reverse=True,
        )[:self.BROWSER_BOOK_DEPTH]
        asks = sorted(
            self.asks.items(),
            key=lambda level: level[0],
        )[:self.BROWSER_BOOK_DEPTH]

        def valid_level(level):
            price, size = level
            return (
                math.isfinite(price)
                and math.isfinite(size)
                and price > 0
                and size >= 0
            )

        valid = (
            bool(bids)
            and bool(asks)
            and self.last_sequence_end is not None
            and all(valid_level(level) for level in bids)
            and all(valid_level(level) for level in asks)
            and bids[0][0] < asks[0][0]
        )

        return {
            "timestamp": timestamp,
            "sequence": self.last_sequence_end,
            "depth": max(len(bids), len(asks)),
            "bids": [
                {"price": price, "size": size}
                for price, size in bids
            ],
            "asks": [
                {"price": price, "size": size}
                for price, size in asks
            ],
            "dataQuality": "VALID" if valid else "INVALID",
            "syncState": "SYNCED" if valid else "UNSYNCED",
        }

    def get_orderbook_debug(self):

        with self._orderbook_lock:
            return self._get_orderbook_debug_locked()

    def _publish_current_book(self, diff):

        with self._orderbook_lock:
            if not self.is_orderbook_synced:
                return

            if not self._refresh_book_metrics_locked():
                self.snapshot_loaded = False
                self.is_orderbook_synced = False
                self.resnapshot_required = True
                trigger_resync = True
            else:
                trigger_resync = False
                self.last_price_update = time.time()
                self.last_valid_bid = self.best_bid
                self.last_valid_ask = self.best_ask
                self.last_ws_receive_time = time.time()
                self.ws_update_count += 1
                debug = self._get_orderbook_debug_locked()
                order_book = self._browser_book_snapshot_locked(
                    self.last_price_update
                )
                payload = {
                    "symbol": self.original_symbol,
                    "exchange_symbol": self.symbol,
                    "market_type": self.MARKET_TYPE,
                    "market_timestamp": self.last_price_update,
                    "sequence": self.last_sequence_end,
                    "best_bid": self.best_bid,
                    "best_ask": self.best_ask,
                    "spread": self.spread,
                    "price": self.last_price,
                    "order_book": order_book,
                    "bids": dict(self.bids),
                    "asks": dict(self.asks),
                    "price_path_debug": {
                        "lastWsPrice": self.last_price,
                        "lastWsReceiveTime": self.last_ws_receive_time,
                        "wsUpdateCount": self.ws_update_count,
                    },
                    "orderbook_sync_debug": debug,
                }

        if trigger_resync:
            add_log(
                "🔄 INVALID LOCAL BOOK RESNAPSHOT TRIGGER",
                "error",
            )
            self._start_snapshot_sync(is_resync=True)
            return

        ws_debug(
            "KuCoin delta sequenceStart=%s sequenceEnd=%s "
            "side=%s price=%s size=%s best_bid=%s best_ask=%s "
            "mid_price=%s spread=%s",
            diff["sequence_start"],
            diff["sequence_end"],
            diff["side"],
            diff["price"],
            diff["size"],
            payload["best_bid"],
            payload["best_ask"],
            payload["price"],
            payload["spread"],
        )

        self.on_update(
            self.original_symbol,
            payload,
            self.runtime_id,
        )


    # =========================
    # MESSAGE
    # =========================

    def on_message(self, ws, message):

        if not hasattr(self, "_first_msg"):
            ws_debug(
                "KuCoin first WebSocket message=%s",
                message[:300],
            )
            self._first_msg = True


        try:

            data = json.loads(message)

            # =========================
            # MESSAGE FILTER
            # =========================

            if data.get("type") != "message":

                return

            try:
                diff = self._parse_diff(data.get("data", {}))
            except Exception as e:
                add_log(
                    f"❌ CHANGE PARSE ERROR: {e}",
                    "error"
                )
                return

            trigger_resync = False
            trigger_initial_sync = False

            with self._orderbook_lock:
                if not self.is_orderbook_synced:
                    self.cached_diffs.append(diff)
                    self.cached_diff_count += 1
                    trigger_initial_sync = not self._sync_in_progress
                else:
                    result = self._apply_sequenced_diff_locked(diff)

                    if result == "gap":
                        self.snapshot_loaded = False
                        self.is_orderbook_synced = False
                        self.resnapshot_required = True
                        self.cached_diffs = []
                        trigger_resync = True
                    elif result == "old":
                        return

            if trigger_resync:
                self._start_snapshot_sync(is_resync=True)
                return

            if trigger_initial_sync:
                self._start_snapshot_sync()
                return

            if self.is_orderbook_synced:
                self._publish_current_book(diff)

        except Exception as e:

            add_log(
                f"❌ KUCOIN PARSE ERROR: "
                f"{e}",
                "error"
            )

    # =========================
    # OPEN
    # =========================

    def on_open(self, ws):
        self.connected = True

        add_log(
            "🟢 KUCOIN WS CONNECTED",
            "success"
        )

        subscribe_data = {

            "id": str(
                int(time.time() * 1000)
            ),

            "type": "subscribe",

            "topic": (
                f"/contractMarket/level2:"
                f"{self.symbol}"
            ),

            "privateChannel": False,

            "response": True
        }

        ws.send(
            json.dumps(
                subscribe_data
            )
        )

        add_log(
            f"📡 SUBSCRIBED: "
            f"{self.symbol}",
            "info"
        )

        with self._orderbook_lock:
            self._sync_generation += 1
            self._sync_in_progress = False
            self.snapshot_loaded = False
            self.orderbook_initialized = False
            self.is_orderbook_synced = False
            self.resnapshot_required = False
            self.snapshot_sequence = 0
            self.last_sequence_end = None
            self.cached_diffs = []
            self.bids = {}
            self.asks = {}

        self._start_snapshot_sync()

    # =========================
    # CLOSE
    # =========================

    def on_close(
        self,
        ws,
        close_status_code,
        close_msg,
    ):
        self.connected = False

        add_log(
            "🔴 ORDERBOOK WS CLOSED",
            "warning"
        )

        add_log(
            f"🔴 CLOSE STATUS: "
            f"{close_status_code}",
            "warning"
        )

        add_log(
            f"🔴 CLOSE MESSAGE: "
            f"{close_msg}",
            "warning"
        )

    # =========================
    # ERROR
    # =========================

    def on_error(self, ws, error):
        self.connected = False

        add_log(
            f"❌ ORDERBOOK WS ERROR: "
            f"{error}",
            "error"
        )

    # =========================
    # TOKEN
    # =========================

    def _get_ws_token(self):

        url = (
            "https://api-futures.kucoin.com"
            "/api/v1/bullet-public"
        )

        response = requests.post(
            url,
            timeout=10
        )

        data = response.json()

        token = data["data"]["token"]

        endpoint = (
            data["data"]
            ["instanceServers"][0]
            ["endpoint"]
        )

        return token, endpoint

    # =========================
    # START
    # =========================

    def start(self):

        if self.running:

            add_log(
                "⚠️ WS ALREADY RUNNING",
                "warning"
            )

            return

        self.running = True

        def run():

            while self.running:
                now = time.time()

                if (
                    self.connected
                    and
                    now - self.last_price_update > 15
                ):

                    add_log(
                        "⚠️ STALE MARKET DATA",
                        "warning"
                    )

                    self.connected = False

                    try:

                        if self.ws:

                            self.ws.close()

                    except Exception:

                        pass

                try:

                    token, endpoint = (
                        self._get_ws_token()
                    )

                    connect_id = str(
                        uuid.uuid4()
                    )

                    self.url = (
                        f"{endpoint}"
                        f"?token={token}"
                        f"&connectId={connect_id}"
                    )

                    ws_debug(
                        "Creating KuCoin WebSocket symbol=%s",
                        self.symbol,
                    )

                    self.ws = (
                        websocket.WebSocketApp(
                            self.url,

                            on_message=(
                                self.on_message
                            ),

                            on_open=(
                                self.on_open
                            ),

                            on_close=(
                                self.on_close
                            ),

                            on_error=(
                                self.on_error
                            ),
                        )
                    )

                    self.ws.run_forever(
                        ping_interval=20,
                        ping_timeout=10,
                    )
                    self.connected = False

                    add_log(
                        "⚠️ WS DISCONNECTED",
                        "warning"
                    )

                except Exception as e:

                    self.connected = False

                    add_log(
                        f"❌ WS THREAD ERROR: "
                        f"{e}",
                        "error"
                    )

                    logger.exception(
                        "[WS RECONNECT ERROR]"
                    )

                add_log(
                    "♻️ RECONNECT IN 5 SEC",
                    "warning"
                )

                time.sleep(5)

        threading.Thread(
            target=run,
            daemon=True
        ).start()

    # =========================
    # STOP
    # =========================

    def stop(self):

        self.running = False

        self.connected = False

        add_log(
            "🛑 WS STOP",
            "warning"
        )

        logger.warning(
            "[WS STOP]"
        )

        if self.ws:

            self.ws.close()
