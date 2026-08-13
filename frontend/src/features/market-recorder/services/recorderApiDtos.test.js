import assert from "node:assert/strict";
import test from "node:test";

import {
    validateCommonResponse,
    validateHealthDto,
    validateStatusDto,
    validateStorageDto,
    validateArchivesDto,
    validateControlDto,
    normalizeHealthDomain,
    normalizeStatusDomain,
    normalizeStorageDomain,
    normalizeArchiveEntryDomain,
    normalizeArchivesDomain,
    normalizeControlDomain,
    ARCHIVE_DTO_STATUS,
} from "./recorderApiDtos.js";
import { RECORDER_ERROR_CODE } from "../contracts/recorderError.js";
import { RECORDER_STATUS_STATE } from "../contracts/recorderContracts.js";

test("normalizeControlDomain preserves completed and rejected semantics", function () {
    var completed = normalizeControlDomain(validateControlDto({
        operation_id: "start-1", operation: "start", result: "completed",
        previous_state: "stopped", current_state: "running",
    }));
    var rejected = normalizeControlDomain(validateControlDto({
        operation_id: "stop-1", operation: "stop", result: "rejected",
        previous_state: "running", current_state: "running",
        message: "invalid_state_transition",
    }));
    assert.equal(completed.successful, true);
    assert.equal(completed.currentState, "running");
    assert.equal(rejected.successful, false);
    assert.equal(rejected.message, "invalid_state_transition");
});

test("validateControlDto rejects unrelated success payload", function () {
    assert.throws(function () { validateControlDto({ unrelated: true }); });
});
test("validateCommonResponse accepts valid ok=true response", function () {
    var data = validateCommonResponse({ ok: true, data: { key: "val" }, error: null });
    assert.deepEqual(data, { key: "val" });
});

test("validateCommonResponse rejects null", function () {
    assert.throws(
        function () { validateCommonResponse(null); },
        function (err) {
            assert.equal(err.code, RECORDER_ERROR_CODE.PARSE);
            assert.ok(err.message.includes("invalid_response"));
            return true;
        },
    );
});

test("validateCommonResponse rejects non-object", function () {
    assert.throws(
        function () { validateCommonResponse("string"); },
        function (err) {
            assert.equal(err.code, RECORDER_ERROR_CODE.PARSE);
            return true;
        },
    );
});

test("validateCommonResponse rejects ok=false", function () {
    assert.throws(
        function () { validateCommonResponse({ ok: false, error: "something broke", data: null }); },
        function (err) {
            assert.equal(err.code, RECORDER_ERROR_CODE.SERVER);
            assert.ok(err.message.includes("recorder_api_rejected"));
            return true;
        },
    );
});

test("validateCommonResponse rejects missing data field", function () {
    assert.throws(
        function () { validateCommonResponse({ ok: true }); },
        function (err) {
            assert.equal(err.code, RECORDER_ERROR_CODE.PARSE);
            assert.ok(err.message.includes("missing data"));
            return true;
        },
    );
});

test("validateCommonResponse accepts ok=true with error=null", function () {
    var data = validateCommonResponse({ ok: true, data: { x: 1 }, error: null });
    assert.deepEqual(data, { x: 1 });
});

test("validateStatusDto accepts valid status object", function () {
    var result = validateStatusDto({ status: "RUNNING" });
    assert.deepEqual(result, { status: "RUNNING" });
});

test("validateStatusDto rejects null", function () {
    assert.throws(
        function () { validateStatusDto(null); },
        function (err) {
            assert.equal(err.code, RECORDER_ERROR_CODE.PARSE);
            return true;
        },
    );
});

test("validateStatusDto rejects non-object", function () {
    assert.throws(
        function () { validateStatusDto([1, 2, 3]); },
        function (err) {
            assert.equal(err.code, RECORDER_ERROR_CODE.PARSE);
            return true;
        },
    );
});

test("validateStorageDto accepts valid storage object", function () {
    var result = validateStorageDto({ total_bytes: 100 });
    assert.deepEqual(result, { total_bytes: 100 });
});

test("validateStorageDto rejects null", function () {
    assert.throws(
        function () { validateStorageDto(null); },
        function (err) {
            assert.equal(err.code, RECORDER_ERROR_CODE.PARSE);
            return true;
        },
    );
});

test("validateArchivesDto accepts valid archives response", function () {
    var result = validateArchivesDto({ entries: [] });
    assert.deepEqual(result, { entries: [] });
});

test("validateArchivesDto rejects missing entries array", function () {
    assert.throws(
        function () { validateArchivesDto({ entries: "not an array" }); },
        function (err) {
            assert.equal(err.code, RECORDER_ERROR_CODE.PARSE);
            return true;
        },
    );
});

test("validateHealthDto accepts valid health object", function () {
    var result = validateHealthDto({ status: "ok", contract_version: "0.1.0" });
    assert.equal(result.status, "ok");
});

test("validateHealthDto rejects null", function () {
    assert.throws(
        function () { validateHealthDto(null); },
        function (err) {
            assert.equal(err.code, RECORDER_ERROR_CODE.PARSE);
            return true;
        },
    );
});

test("validateHealthDto rejects non-object", function () {
    assert.throws(
        function () { validateHealthDto("ok"); },
        function (err) {
            assert.equal(err.code, RECORDER_ERROR_CODE.PARSE);
            return true;
        },
    );
});

test("normalizeHealthDomain normalizes fields", function () {
    var domain = normalizeHealthDomain({
        status: "ok",
        contract_version: "0.1.0",
        uptime_seconds: 12345,
    });
    assert.equal(domain.status, "ok");
    assert.equal(domain.contractVersion, "0.1.0");
    assert.equal(domain.uptimeSeconds, 12345);
});

test("normalizeHealthDomain handles missing and invalid fields", function () {
    var domain = normalizeHealthDomain({});
    assert.equal(domain.status, null);
    assert.equal(domain.contractVersion, null);
    assert.equal(domain.uptimeSeconds, null);
    var invalid = normalizeHealthDomain({ uptime_seconds: -5 });
    assert.equal(invalid.uptimeSeconds, null);
});

test("normalizeStatusDomain maps running status", function () {
    var dto = { status: "RUNNING" };
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.status, RECORDER_STATUS_STATE.RUNNING);
});

test("normalizeStatusDomain maps stopped status", function () {
    var dto = { status: "STOPPED" };
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.status, RECORDER_STATUS_STATE.STOPPED);
});

test("normalizeStatusDomain maps lowercase running", function () {
    var dto = { status: "running" };
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.status, RECORDER_STATUS_STATE.RUNNING);
});

test("normalizeStatusDomain maps recording as running", function () {
    var dto = { status: "RECORDING" };
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.status, RECORDER_STATUS_STATE.RUNNING);
});

test("normalizeStatusDomain handles unknown status", function () {
    var dto = { status: "UNKNOWN" };
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.status, RECORDER_STATUS_STATE.UNAVAILABLE);
});

test("normalizeStatusDomain handles missing status field", function () {
    var dto = {};
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.status, RECORDER_STATUS_STATE.UNAVAILABLE);
});

test("normalizeStatusDomain normalizes fractional uptime_seconds", function () {
    var dto = { status: "RUNNING", uptime_seconds: 5025.75 };
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.uptimeSeconds, 5025.75);
});

test("normalizeStatusDomain handles negative uptime_seconds", function () {
    var dto = { status: "RUNNING", uptime_seconds: -1 };
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.uptimeSeconds, null);
});

test("normalizeStatusDomain handles NaN uptime_seconds", function () {
    var dto = { status: "RUNNING", uptime_seconds: NaN };
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.uptimeSeconds, null);
});

test("normalizeStatusDomain handles Infinity uptime_seconds", function () {
    var dto = { status: "RUNNING", uptime_seconds: Infinity };
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.uptimeSeconds, null);
});

test("normalizeStatusDomain normalizes active_files to basenames", function () {
    var dto = { active_files: ["/opt/data/BTCUSDT.jsonl.part", "/opt/data/ETHUSDT.jsonl.part"] };
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.activeFiles.length, 2);
    assert.equal(domain.activeFiles[0], "BTCUSDT.jsonl.part");
    assert.equal(domain.activeFiles[1], "ETHUSDT.jsonl.part");
});

test("normalizeStatusDomain handles empty active_files", function () {
    var dto = { active_files: [] };
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.activeFiles.length, 0);
});

test("normalizeStatusDomain handles non-array active_files", function () {
    var dto = { active_files: "not-array" };
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.activeFiles.length, 0);
});

test("normalizeStatusDomain filters null entries from active_files", function () {
    var dto = { active_files: ["valid.part", null, ""] };
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.activeFiles.length, 1);
    assert.equal(domain.activeFiles[0], "valid.part");
});

test("normalizeStatusDomain validates timestamps", function () {
    var dto = { observed_at: "2026-07-31T12:35:00Z", last_message_at: "invalid" };
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.observedAt, "2026-07-31T12:35:00Z");
    assert.equal(domain.lastMessageAt, null);
});

test("normalizeStatusDomain handles non-string last_error", function () {
    var dto = { last_error: 12345 };
    var domain = normalizeStatusDomain(dto);
    assert.equal(domain.lastError, null);
});

test("normalizeStorageDomain normalizes byte fields", function () {
    var dto = { total_bytes: 1000, used_bytes: 500, free_bytes: 500, archive_bytes: 100 };
    var domain = normalizeStorageDomain(dto);
    assert.equal(domain.totalBytes, 1000);
    assert.equal(domain.usedBytes, 500);
    assert.equal(domain.freeBytes, 500);
    assert.equal(domain.archiveBytes, 100);
});

test("normalizeStorageDomain handles negative bytes", function () {
    var dto = { total_bytes: -1, archive_bytes: -5 };
    var domain = normalizeStorageDomain(dto);
    assert.equal(domain.totalBytes, null);
    assert.equal(domain.archiveBytes, null);
});

test("normalizeStorageDomain handles NaN bytes", function () {
    var dto = { total_bytes: NaN };
    var domain = normalizeStorageDomain(dto);
    assert.equal(domain.totalBytes, null);
});

test("normalizeStorageDomain handles Infinity bytes", function () {
    var dto = { total_bytes: Infinity };
    var domain = normalizeStorageDomain(dto);
    assert.equal(domain.totalBytes, null);
});

test("normalizeStorageDomain handles missing fields", function () {
    var dto = {};
    var domain = normalizeStorageDomain(dto);
    assert.equal(domain.totalBytes, null);
    assert.equal(domain.quarantineCount, null);
});

test("normalizeArchiveEntryDomain normalizes valid entry", function () {
    var dto = {
        id: "arch-001",
        symbol: "BTCUSDT",
        start_time: "2026-07-31T00:00:00Z",
        compressed_bytes: 257589411,
        verification_status: "completed",
        downloadable: true,
        deletion_eligible: true,
    };
    var entry = normalizeArchiveEntryDomain(dto);
    assert.equal(entry.id, "arch-001");
    assert.equal(entry.symbol, "BTCUSDT");
    assert.equal(entry.startTime, "2026-07-31T00:00:00Z");
    assert.equal(entry.compressedBytes, 257589411);
    assert.equal(entry.verificationStatus, ARCHIVE_DTO_STATUS.COMPLETED);
    assert.equal(entry.downloadable, true);
    assert.equal(entry.deletionEligible, true);
});

test("normalizeArchiveEntryDomain handles null entry", function () {
    var entry = normalizeArchiveEntryDomain(null);
    assert.equal(entry, null);
});

test("normalizeArchiveEntryDomain handles non-object entry", function () {
    var entry = normalizeArchiveEntryDomain("string");
    assert.equal(entry, null);
});

test("normalizeArchiveEntryDomain defaults verification_status to completed", function () {
    var dto = { id: "x", compressed_bytes: 100 };
    var entry = normalizeArchiveEntryDomain(dto);
    assert.equal(entry.verificationStatus, ARCHIVE_DTO_STATUS.COMPLETED);
});

test("normalizeArchiveEntryDomain handles negative compressed_bytes", function () {
    var dto = { compressed_bytes: -100 };
    var entry = normalizeArchiveEntryDomain(dto);
    assert.equal(entry.compressedBytes, 0);
});

test("normalizeArchiveEntryDomain handles NaN compressed_bytes", function () {
    var dto = { compressed_bytes: NaN };
    var entry = normalizeArchiveEntryDomain(dto);
    assert.equal(entry.compressedBytes, 0);
});

test("normalizeArchiveEntryDomain handles false downloadable", function () {
    var dto = { compressed_bytes: 100, downloadable: false };
    var entry = normalizeArchiveEntryDomain(dto);
    assert.equal(entry.downloadable, false);
});

test("normalizeArchiveEntryDomain handles non-boolean downloadable as false", function () {
    var dto = { compressed_bytes: 100, downloadable: "true" };
    var entry = normalizeArchiveEntryDomain(dto);
    assert.equal(entry.downloadable, false);
});

test("normalizeArchiveEntryDomain generates fallback id when missing", function () {
    var dto = { compressed_bytes: 100 };
    var entry = normalizeArchiveEntryDomain(dto);
    assert.ok(typeof entry.id === "string");
    assert.ok(entry.id.length > 0);
});

test("normalizeArchiveEntryDomain rejects path components in id", function () {
    var dto = { id: "/etc/passwd", compressed_bytes: 100 };
    var entry = normalizeArchiveEntryDomain(dto);
    assert.notEqual(entry.id, "/etc/passwd");
});

test("normalizeArchivesDomain normalizes entries array", function () {
    var dto = {
        entries: [
            { id: "a", compressed_bytes: 100 },
            { id: "b", compressed_bytes: 200 },
        ],
        page: 1,
        page_size: 10,
        total_count: 2,
        total_pages: 1,
    };
    var domain = normalizeArchivesDomain(dto);
    assert.equal(domain.entries.length, 2);
    assert.equal(domain.entries[0].id, "a");
    assert.equal(domain.entries[1].id, "b");
    assert.equal(domain.page, 1);
    assert.equal(domain.pageSize, 10);
    assert.equal(domain.totalCount, 2);
    assert.equal(domain.totalPages, 1);
});

test("normalizeArchivesDomain filters null entries", function () {
    var dto = {
        entries: [{ id: "a", compressed_bytes: 100 }, null, { id: "b", compressed_bytes: 200 }],
    };
    var domain = normalizeArchivesDomain(dto);
    assert.equal(domain.entries.length, 2);
});

test("normalizeArchivesDomain handles invalid paging values", function () {
    var dto = { entries: [], page: -1, page_size: 0, total_count: -5 };
    var domain = normalizeArchivesDomain(dto);
    assert.equal(domain.page, 1);
    assert.equal(domain.pageSize, 0);
    assert.equal(domain.totalCount, 0);
});

test("normalizeArchivesDomain raw path is excluded from safeString", function () {
    var dto = {
        entries: [{ id: "ok", stream: "/opt/market-recorder/data", symbol: "/etc/hosts", compressed_bytes: 100 }],
    };
    var domain = normalizeArchivesDomain(dto);
    assert.equal(domain.entries[0].stream, null);
    assert.equal(domain.entries[0].symbol, null);
});
