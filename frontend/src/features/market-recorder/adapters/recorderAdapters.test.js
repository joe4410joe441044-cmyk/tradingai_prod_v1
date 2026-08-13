import assert from "node:assert/strict";
import test from "node:test";

import {
    toRecorderStatusViewModel,
    toRecorderStorageViewModel,
    toRecorderArchiveViewModel,
    toRecorderArchivesViewModel,
} from "./recorderAdapters.js";
import { RECORDER_STATUS_STATE, ARCHIVE_STATUS } from "../contracts/recorderContracts.js";
import { ARCHIVE_DTO_STATUS } from "../services/recorderApiDtos.js";

test("toRecorderStatusViewModel maps valid running domain", function () {
    var domain = {
        status: RECORDER_STATUS_STATE.RUNNING,
        uptimeSeconds: 5025,
        activeFiles: ["BTCUSDT.jsonl.part"],
    };
    var vm = toRecorderStatusViewModel(domain);
    assert.equal(vm.status, RECORDER_STATUS_STATE.RUNNING);
    assert.equal(vm.recordingTime, "01:23:45");
    assert.equal(vm.currentFile, "BTCUSDT.jsonl.part");
});

test("status view model keeps event families separate from trading symbols", function () {
    var vm = toRecorderStatusViewModel({
        status: RECORDER_STATUS_STATE.RUNNING,
        subscribedStreams: ["trades", "orderbook", "ticker"],
        messagesReceived: 42,
        bytesReceived: 2048,
        sequenceAnomalyCount: 0,
        lastMessageAt: "2026-08-09T18:12:38Z",
    });
    assert.equal(vm.symbols, null);
    assert.equal(vm.eventFamilies, "orderbook, ticker, trades");
    assert.equal(vm.messagesReceived, 42);
    assert.equal(vm.bytesReceived, "2.00 KB");
    assert.equal(vm.sequenceAnomalyCount, 0);
    assert.equal(vm.lastMessageAt, "2026-08-09T18:12:38Z");
});

test("storage view model distinguishes runtime and active recording bytes", function () {
    var vm = toRecorderStorageViewModel({ runtimeBytes: 0, activeBytes: 1048576 });
    assert.equal(vm.runtimeSize, "0");
    assert.equal(vm.runtimeSizeUnit, "B");
    assert.equal(vm.activeRecordingSize, "1.00");
    assert.equal(vm.activeRecordingSizeUnit, "MB");
});

test("toRecorderStatusViewModel maps valid stopped domain", function () {
    var domain = {
        status: RECORDER_STATUS_STATE.STOPPED,
        uptimeSeconds: 1459.955,
        activeFiles: [],
    };
    var vm = toRecorderStatusViewModel(domain);
    assert.equal(vm.status, RECORDER_STATUS_STATE.STOPPED);
    assert.equal(vm.recordingTime, null);
    assert.equal(vm.currentFile, null);
});

test("toRecorderStatusViewModel handles unknown status safely", function () {
    var domain = {
        status: "UNKNOWN_STATE",
        uptimeSeconds: 5025,
        activeFiles: ["file.part"],
    };
    var vm = toRecorderStatusViewModel(domain);
    assert.equal(vm.status, RECORDER_STATUS_STATE.UNAVAILABLE);
    assert.equal(vm.recordingTime, null);
});

test("toRecorderStatusViewModel handles null input", function () {
    var vm = toRecorderStatusViewModel(null);
    assert.equal(vm.status, RECORDER_STATUS_STATE.UNAVAILABLE);
    assert.equal(vm.recordingTime, null);
    assert.equal(vm.currentFile, null);
});

test("toRecorderStatusViewModel handles undefined input", function () {
    var vm = toRecorderStatusViewModel(undefined);
    assert.equal(vm.status, RECORDER_STATUS_STATE.UNAVAILABLE);
    assert.equal(vm.recordingTime, null);
});

test("toRecorderStatusViewModel does not mutate input", function () {
    var domain = { status: RECORDER_STATUS_STATE.RUNNING, uptimeSeconds: 60, activeFiles: ["f"] };
    var copy = JSON.parse(JSON.stringify(domain));
    toRecorderStatusViewModel(domain);
    assert.deepEqual(domain, copy);
});

test("toRecorderStatusViewModel uses basename-safe active file", function () {
    var domain = {
        status: RECORDER_STATUS_STATE.RUNNING,
        uptimeSeconds: 100,
        activeFiles: ["/opt/market-recorder/data/BTCUSDT.jsonl.part"],
    };
    var vm = toRecorderStatusViewModel(domain);
    assert.equal(vm.currentFile, "BTCUSDT.jsonl.part");
});

test("toRecorderStatusViewModel activeFiles with only path-safe entries", function () {
    var domain = {
        status: RECORDER_STATUS_STATE.RUNNING,
        uptimeSeconds: 0,
        activeFiles: [],
    };
    var vm = toRecorderStatusViewModel(domain);
    assert.equal(vm.currentFile, null);
});

test("toRecorderStorageViewModel maps valid domain with bytes", function () {
    var domain = {
        totalBytes: 536870912000,
        usedBytes: 251792850944,
        freeBytes: 285078061056,
        archiveBytes: 13244702720,
    };
    var vm = toRecorderStorageViewModel(domain);
    assert.equal(vm.total, "500.00");
    assert.equal(vm.totalUnit, "GB");
    assert.equal(vm.used, "234.50");
    assert.equal(vm.usedUnit, "GB");
    assert.equal(vm.free, "265.50");
    assert.equal(vm.freeUnit, "GB");
    assert.equal(vm.recorderSize, "12.34");
    assert.equal(vm.recorderSizeUnit, "GB");
});

test("toRecorderStorageViewModel handles null input", function () {
    var vm = toRecorderStorageViewModel(null);
    assert.equal(vm.total, null);
    assert.equal(vm.totalUnit, null);
    assert.equal(vm.used, null);
});

test("toRecorderStorageViewModel handles undefined input", function () {
    var vm = toRecorderStorageViewModel(undefined);
    assert.equal(vm.total, null);
});

test("toRecorderStorageViewModel handles missing optional fields", function () {
    var domain = { totalBytes: 0 };
    var vm = toRecorderStorageViewModel(domain);
    assert.equal(vm.total, "0");
    assert.equal(vm.totalUnit, "B");
    assert.equal(vm.used, null);
});

test("toRecorderStorageViewModel handles non-number bytes as null", function () {
    var domain = { totalBytes: null, usedBytes: NaN, freeBytes: undefined, archiveBytes: -1 };
    var vm = toRecorderStorageViewModel(domain);
    assert.equal(vm.total, null);
    assert.equal(vm.used, null);
    assert.equal(vm.free, null);
    assert.equal(vm.recorderSize, null);
});

test("toRecorderStorageViewModel bytes format with MB scale", function () {
    var domain = { totalBytes: 1048576 };
    var vm = toRecorderStorageViewModel(domain);
    assert.equal(vm.total, "1.00");
    assert.equal(vm.totalUnit, "MB");
});

test("toRecorderArchiveViewModel maps completed domain entry", function () {
    var domain = {
        id: "arch-001",
        symbol: "BTCUSDT",
        startTime: "2026-07-31T00:00:00Z",
        compressedBytes: 257589411,
        verificationStatus: ARCHIVE_DTO_STATUS.COMPLETED,
        downloadable: true,
        deletionEligible: true,
    };
    var vm = toRecorderArchiveViewModel(domain, 0);
    assert.equal(vm.id, "arch-001");
    assert.equal(vm.date, "2026-07-31");
    assert.equal(vm.file, "BTCUSDT-2026-07-31.jsonl.gz");
    assert.equal(vm.compressedSize, "245.66 MB");
    assert.equal(vm.status, ARCHIVE_STATUS.COMPLETED);
    assert.equal(vm.downloadable, true);
    assert.equal(vm.deletionEligible, true);
});

test("toRecorderArchiveViewModel downloadable false for recording", function () {
    var domain = {
        id: "arch-002",
        symbol: "ETHUSDT",
        startTime: "2026-07-31T00:00:00Z",
        compressedBytes: 100000000,
        verificationStatus: ARCHIVE_DTO_STATUS.RECORDING,
        downloadable: false,
        deletionEligible: false,
    };
    var vm = toRecorderArchiveViewModel(domain, 0);
    assert.equal(vm.status, ARCHIVE_STATUS.RECORDING);
    assert.equal(vm.downloadable, false);
    assert.equal(vm.deletionEligible, false);
});

test("toRecorderArchiveViewModel deletionEligible true for failed", function () {
    var domain = {
        id: "arch-003",
        symbol: "ETHUSDT",
        startTime: "2026-07-31T00:00:00Z",
        compressedBytes: 0,
        verificationStatus: ARCHIVE_DTO_STATUS.FAILED,
        downloadable: false,
        deletionEligible: true,
    };
    var vm = toRecorderArchiveViewModel(domain, 0);
    assert.equal(vm.status, ARCHIVE_STATUS.FAILED);
    assert.equal(vm.downloadable, false);
    assert.equal(vm.deletionEligible, true);
});

test("toRecorderArchiveViewModel uses domain id when present", function () {
    var domain = {
        id: "archive-123",
        symbol: "BTCUSDT",
        startTime: "2026-07-31T00:00:00Z",
        compressedBytes: 100,
        verificationStatus: ARCHIVE_DTO_STATUS.COMPLETED,
        downloadable: true,
        deletionEligible: true,
    };
    var vm = toRecorderArchiveViewModel(domain, 5);
    assert.equal(vm.id, "archive-123");
});

test("toRecorderArchiveViewModel handles null input", function () {
    var vm = toRecorderArchiveViewModel(null, 0);
    assert.equal(vm.id, null);
    assert.equal(vm.date, null);
    assert.equal(vm.file, null);
    assert.equal(vm.downloadable, false);
    assert.equal(vm.deletionEligible, false);
});

test("toRecorderArchiveViewModel constructs filename from symbol and date", function () {
    var domain = {
        symbol: "ETHUSDT",
        startTime: "2026-07-28T00:00:00Z",
        compressedBytes: 164508574,
        verificationStatus: ARCHIVE_DTO_STATUS.COMPLETED,
        downloadable: true,
        deletionEligible: true,
    };
    var vm = toRecorderArchiveViewModel(domain, 0);
    assert.equal(vm.file, "ETHUSDT-2026-07-28.jsonl.gz");
});

test("toRecorderArchivesViewModel returns empty array for null", function () {
    var vm = toRecorderArchivesViewModel(null);
    assert.deepEqual(vm, []);
});

test("toRecorderArchivesViewModel returns empty array for empty list", function () {
    var vm = toRecorderArchivesViewModel([]);
    assert.deepEqual(vm, []);
});

test("toRecorderArchivesViewModel maps multiple domain entries", function () {
    var domain = [
        { id: "a1", symbol: "BTCUSDT", startTime: "2026-07-31T00:00:00Z", compressedBytes: 100, verificationStatus: ARCHIVE_DTO_STATUS.COMPLETED, downloadable: true, deletionEligible: true },
        { id: "a2", symbol: "ETHUSDT", startTime: "2026-07-30T00:00:00Z", compressedBytes: 200, verificationStatus: ARCHIVE_DTO_STATUS.COMPLETED, downloadable: true, deletionEligible: true },
    ];
    var vm = toRecorderArchivesViewModel(domain);
    assert.equal(vm.length, 2);
    assert.equal(vm[0].id, "a1");
    assert.equal(vm[1].id, "a2");
    assert.equal(vm[0].date, "2026-07-31");
    assert.equal(vm[1].date, "2026-07-30");
});

test("toRecorderArchivesViewModel does not mutate input array", function () {
    var domain = [{ id: "x", symbol: "BTCUSDT", startTime: "2026-07-31T00:00:00Z", compressedBytes: 100, verificationStatus: ARCHIVE_DTO_STATUS.COMPLETED, downloadable: true, deletionEligible: true }];
    var copy = JSON.parse(JSON.stringify(domain));
    toRecorderArchivesViewModel(domain);
    assert.deepEqual(domain, copy);
});

test("toRecorderArchiveViewModel handles unknown verification status safely", function () {
    var domain = {
        id: "x",
        symbol: "BTCUSDT",
        startTime: "2026-07-31T00:00:00Z",
        compressedBytes: 100,
        verificationStatus: "UNKNOWN_STATUS",
        downloadable: true,
        deletionEligible: true,
    };
    var vm = toRecorderArchiveViewModel(domain, 0);
    assert.equal(vm.status, ARCHIVE_STATUS.COMPLETED);
    assert.equal(vm.downloadable, true);
});

test("toRecorderArchiveViewModel handles missing optional fields", function () {
    var domain = {
        verificationStatus: ARCHIVE_DTO_STATUS.COMPLETED,
        downloadable: true,
        deletionEligible: true,
    };
    var vm = toRecorderArchiveViewModel(domain, 0);
    assert.equal(vm.date, "--");
    assert.equal(vm.file, null);
    assert.equal(vm.compressedSize, null);
});

test("toRecorderArchiveViewModel downloadable false when domain says false even if status is completed", function () {
    var domain = {
        id: "x",
        symbol: "BTCUSDT",
        startTime: "2026-07-31T00:00:00Z",
        compressedBytes: 100,
        verificationStatus: ARCHIVE_DTO_STATUS.COMPLETED,
        downloadable: false,
        deletionEligible: true,
    };
    var vm = toRecorderArchiveViewModel(domain, 0);
    assert.equal(vm.downloadable, false);
});

test("toRecorderArchiveViewModel uses index fallback when id missing", function () {
    var domain = {
        symbol: "BTCUSDT",
        startTime: "2026-07-31T00:00:00Z",
        compressedBytes: 100,
        verificationStatus: ARCHIVE_DTO_STATUS.COMPLETED,
        downloadable: true,
        deletionEligible: true,
    };
    var vm = toRecorderArchiveViewModel(domain, 3);
    assert.equal(vm.id, "3");
});

test("toRecorderStatusViewModel handles null uptimeSeconds", function () {
    var domain = {
        status: RECORDER_STATUS_STATE.RUNNING,
        uptimeSeconds: null,
        activeFiles: [],
    };
    var vm = toRecorderStatusViewModel(domain);
    assert.equal(vm.recordingTime, null);
});

test("toRecorderStatusViewModel handles negative uptimeSeconds", function () {
    var domain = {
        status: RECORDER_STATUS_STATE.RUNNING,
        uptimeSeconds: -5,
        activeFiles: [],
    };
    var vm = toRecorderStatusViewModel(domain);
    assert.equal(vm.recordingTime, null);
});
