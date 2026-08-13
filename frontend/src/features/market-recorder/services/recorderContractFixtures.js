function deepFreeze(value) {
    if (value !== null && typeof value === "object") {
        Object.freeze(value);
        Object.keys(value).forEach(function (key) {
            deepFreeze(value[key]);
        });
    }
    return value;
}

export var RECORDER_CONTRACT_FIXTURES = Object.freeze({
    "health.success": deepFreeze({
        ok: true,
        data: {
            status: "ok",
            contract_version: "0.1.0",
            uptime_seconds: 12345,
        },
        error: null,
    }),

    "status.running": deepFreeze({
        ok: true,
        data: {
            status: "running",
            connection_state: "connected",
            pid: 12345,
            uptime_seconds: 5025,
            subscribed_streams: 5,
            messages_received: 1250000,
            bytes_received: 250000000,
            reconnect_count: 0,
            sequence_anomaly_count: 0,
            active_files: [
                "/opt/market-recorder/active/BTCUSDT-2026-07-31.jsonl.part",
                "/opt/market-recorder/active/ETHUSDT-2026-07-31.jsonl.part",
            ],
            last_message_at: "2026-07-31T12:34:56Z",
            last_error: null,
            process_started_at: "2026-07-31T00:00:00Z",
            observed_at: "2026-07-31T12:35:00Z",
        },
        error: null,
    }),

    "status.unavailable": deepFreeze({
        ok: true,
        data: {
            status: "stopped",
            connection_state: "disconnected",
            pid: null,
            uptime_seconds: 0,
            subscribed_streams: 0,
            messages_received: 0,
            bytes_received: 0,
            reconnect_count: 3,
            sequence_anomaly_count: 0,
            active_files: [],
            last_message_at: null,
            last_error: "connection lost",
            process_started_at: null,
            observed_at: "2026-07-31T12:35:00Z",
        },
        error: null,
    }),

    "storage.success": deepFreeze({
        ok: true,
        data: {
            filesystem: "/dev/sda1",
            total_bytes: 536870912000,
            used_bytes: 251792850944,
            free_bytes: 285078061056,
            usage_percent: 46.9,
            archive_bytes: 13244702720,
            active_bytes: 5242880000,
            manifest_bytes: 20971520,
            quarantine_count: 0,
            observed_at: "2026-07-31T12:35:00Z",
        },
        error: null,
    }),

    "archives.empty": deepFreeze({
        ok: true,
        data: {
            entries: [],
            page: 1,
            page_size: 10,
            total_count: 0,
            total_pages: 0,
        },
        error: null,
    }),

    "archives.page1": deepFreeze({
        ok: true,
        data: {
            entries: [
                {
                    id: "arch-001",
                    stream: "btcusdt@trade",
                    symbol: "BTCUSDT",
                    period: "2026-07-31",
                    start_time: "2026-07-31T00:00:00Z",
                    end_time: "2026-07-31T23:59:59Z",
                    record_count: 5000000,
                    compressed_bytes: 257589411,
                    uncompressed_bytes: 1048576000,
                    verification_status: "completed",
                    manifest_status: "complete",
                    downloadable: true,
                    deletion_eligible: true,
                },
            ],
            page: 1,
            page_size: 10,
            total_count: 1,
            total_pages: 1,
        },
        error: null,
    }),

    "error.invalid_query": deepFreeze({
        ok: false,
        data: null,
        error: "invalid_query",
    }),

    "error.runtime_unavailable": deepFreeze({
        ok: false,
        data: null,
        error: "runtime_unavailable",
    }),

    "error.storage_unavailable": deepFreeze({
        ok: false,
        data: null,
        error: "storage_unavailable",
    }),

    "error.archive_inventory_unavailable": deepFreeze({
        ok: false,
        data: null,
        error: "archive_inventory_unavailable",
    }),
});
