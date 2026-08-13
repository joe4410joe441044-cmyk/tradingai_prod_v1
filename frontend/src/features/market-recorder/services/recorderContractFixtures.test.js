import assert from "node:assert/strict";
import test from "node:test";

import {
    validateCommonResponse,
    validateHealthDto,
    validateStatusDto,
    validateStorageDto,
    validateArchivesDto,
    normalizeHealthDomain,
    normalizeStatusDomain,
    normalizeStorageDomain,
    normalizeArchivesDomain,
} from "./recorderApiDtos.js";
import {
    toRecorderStatusViewModel,
    toRecorderStorageViewModel,
    toRecorderArchivesViewModel,
} from "../adapters/recorderAdapters.js";
import { RECORDER_CONTRACT_FIXTURES } from "./recorderContractFixtures.js";
import { RECORDER_ERROR_CODE } from "../contracts/recorderError.js";
import { RECORDER_STATUS_STATE } from "../contracts/recorderContracts.js";

function fixture(name) {
    return RECORDER_CONTRACT_FIXTURES[name];
}

test("fixtures: all 10 required samples are present", function () {
    var expected = [
        "health.success",
        "status.running",
        "status.unavailable",
        "storage.success",
        "archives.empty",
        "archives.page1",
        "error.invalid_query",
        "error.runtime_unavailable",
        "error.storage_unavailable",
        "error.archive_inventory_unavailable",
    ];
    expected.forEach(function (name) {
        assert.ok(fixture(name) !== undefined, "missing fixture: " + name);
    });
});

test("fixtures are frozen (input immutability contract)", function () {
    var names = Object.keys(RECORDER_CONTRACT_FIXTURES);
    names.forEach(function (name) {
        assert.ok(Object.isFrozen(RECORDER_CONTRACT_FIXTURES[name]));
    });
});

test("health.success passes common envelope and health DTO validator", function () {
    var dto = validateCommonResponse(fixture("health.success"));
    var validated = validateHealthDto(dto);
    var domain = normalizeHealthDomain(validated);
    assert.equal(domain.status, "ok");
    assert.equal(domain.contractVersion, "0.1.0");
    assert.equal(domain.uptimeSeconds, 12345);
});

test("status.running passes validators and converts to domain and view model", function () {
    var envelope = fixture("status.running");
    var dto = validateCommonResponse(envelope);
    var validated = validateStatusDto(dto);
    var domain = normalizeStatusDomain(validated);
    var vm = toRecorderStatusViewModel(domain);

    assert.equal(domain.status, RECORDER_STATUS_STATE.RUNNING);
    assert.equal(domain.uptimeSeconds, 5025);
    assert.equal(domain.activeFileCount, 2);
    assert.equal(vm.status, RECORDER_STATUS_STATE.RUNNING);
    assert.ok(typeof vm.recordingTime === "string" && vm.recordingTime.length > 0);
});

test("status.running hides raw active file paths", function () {
    var dto = validateCommonResponse(fixture("status.running"));
    var domain = normalizeStatusDomain(validateStatusDto(dto));
    var vm = toRecorderStatusViewModel(domain);

    domain.activeFiles.forEach(function (file) {
        assert.ok(!file.includes("/"), "basename leaked into domain: " + file);
        assert.ok(!file.startsWith("opt/"), "path prefix leaked: " + file);
    });
    assert.equal(domain.activeFiles[0], "BTCUSDT-2026-07-31.jsonl.part");
    assert.equal(vm.currentFile, "BTCUSDT-2026-07-31.jsonl.part");
    assert.ok(!vm.currentFile.includes("/"));
});

test("status.unavailable converts to stopped view model with no current file", function () {
    var dto = validateCommonResponse(fixture("status.unavailable"));
    var domain = normalizeStatusDomain(validateStatusDto(dto));
    var vm = toRecorderStatusViewModel(domain);

    assert.equal(domain.status, RECORDER_STATUS_STATE.STOPPED);
    assert.equal(domain.activeFiles.length, 0);
    assert.equal(domain.lastError, "connection lost");
    assert.equal(vm.status, RECORDER_STATUS_STATE.STOPPED);
    assert.equal(vm.currentFile, null);
});

test("storage.success passes validators and converts to domain and view model", function () {
    var dto = validateCommonResponse(fixture("storage.success"));
    var domain = normalizeStorageDomain(validateStorageDto(dto));
    var vm = toRecorderStorageViewModel(domain);

    assert.equal(domain.totalBytes, 536870912000);
    assert.equal(domain.archiveBytes, 13244702720);
    assert.equal(domain.usagePercent, 46.9);
    assert.ok(typeof vm.total === "string" && vm.total.length > 0);
    assert.ok(typeof vm.totalUnit === "string" && vm.totalUnit.length > 0);
    assert.equal(vm.total, "500.00");
    assert.equal(vm.totalUnit, "GB");
});

test("archives.empty passes validators and produces empty view model", function () {
    var dto = validateCommonResponse(fixture("archives.empty"));
    var domain = normalizeArchivesDomain(validateArchivesDto(dto));
    var vm = toRecorderArchivesViewModel(domain.entries);

    assert.ok(Array.isArray(domain.entries));
    assert.equal(domain.entries.length, 0);
    assert.equal(domain.totalCount, 0);
    assert.equal(vm.length, 0);
});

test("archives.page1 passes validators and converts to domain and view model", function () {
    var dto = validateCommonResponse(fixture("archives.page1"));
    var domain = normalizeArchivesDomain(validateArchivesDto(dto));
    var vm = toRecorderArchivesViewModel(domain.entries);

    assert.equal(domain.page, 1);
    assert.equal(domain.pageSize, 10);
    assert.equal(domain.totalCount, 1);
    assert.equal(domain.totalPages, 1);
    assert.equal(domain.entries.length, 1);
    assert.equal(domain.entries[0].verificationStatus, "completed");

    assert.equal(vm.length, 1);
    assert.equal(vm[0].id, "arch-001");
    assert.equal(vm[0].date, "2026-07-31");
    assert.equal(vm[0].file, "BTCUSDT-2026-07-31.jsonl.gz");
    assert.equal(vm[0].status, "Completed");
    assert.equal(vm[0].downloadable, true);
    assert.equal(vm[0].deletionEligible, true);
});

test("archives.page1 hides raw paths from view model", function () {
    var dto = validateCommonResponse(fixture("archives.page1"));
    var domain = normalizeArchivesDomain(validateArchivesDto(dto));
    var vm = toRecorderArchivesViewModel(domain.entries);

    assert.ok(!vm[0].file.includes("/"));
    assert.ok(!vm[0].file.startsWith("archive/"));
    assert.ok(vm[0].file.includes("jsonl.gz"));
});

test("error samples are safely rejected by the common envelope", function () {
    var errorNames = [
        "error.invalid_query",
        "error.runtime_unavailable",
        "error.storage_unavailable",
        "error.archive_inventory_unavailable",
    ];
    errorNames.forEach(function (name) {
        var sample = fixture(name);
        assert.throws(
            function () { validateCommonResponse(sample); },
            function (err) {
                assert.equal(err.code, RECORDER_ERROR_CODE.SERVER);
                assert.ok(err.message.includes("recorder_api_rejected"));
                assert.equal(err.retryable, false);
                assert.equal(err.source, "server");
                assert.ok(Object.prototype.hasOwnProperty.call(err, "code"));
                assert.ok(Object.prototype.hasOwnProperty.call(err, "message"));
                assert.ok(Object.prototype.hasOwnProperty.call(err, "retryable"));
                assert.ok(Object.prototype.hasOwnProperty.call(err, "source"));
                return true;
            },
            "expected safe rejection for " + name,
        );
    });
});

test("error samples do not expose raw server internals in the error surface", function () {
    var errorNames = [
        "error.invalid_query",
        "error.runtime_unavailable",
        "error.storage_unavailable",
        "error.archive_inventory_unavailable",
    ];
    errorNames.forEach(function (name) {
        var sample = fixture(name);
        var caught = null;
        try {
            validateCommonResponse(sample);
        } catch (err) {
            caught = err;
        }
        assert.ok(caught !== null, "expected throw for " + name);
        var serialized = JSON.stringify(caught);
        assert.ok(!serialized.includes("stack"));
        assert.ok(!serialized.includes("/opt/"));
        assert.ok(!serialized.includes("traceback"));
    });
});

test("all fixtures are deterministic across repeated runs", function () {
    var pipelineByFixture = {
        "status.running": function (sample) {
            return normalizeStatusDomain(validateStatusDto(validateCommonResponse(sample)));
        },
        "status.unavailable": function (sample) {
            return normalizeStatusDomain(validateStatusDto(validateCommonResponse(sample)));
        },
        "storage.success": function (sample) {
            return normalizeStorageDomain(validateStorageDto(validateCommonResponse(sample)));
        },
        "archives.page1": function (sample) {
            return normalizeArchivesDomain(validateArchivesDto(validateCommonResponse(sample)));
        },
        "archives.empty": function (sample) {
            return normalizeArchivesDomain(validateArchivesDto(validateCommonResponse(sample)));
        },
    };
    Object.keys(pipelineByFixture).forEach(function (name) {
        var run = function () { return JSON.stringify(pipelineByFixture[name](fixture(name))); };
        assert.equal(run(), run(), "non-deterministic: " + name);
    });
});

test("fixtures are not mutated by validators and normalizers", function () {
    var names = Object.keys(RECORDER_CONTRACT_FIXTURES);
    names.forEach(function (name) {
        var snapshot = JSON.stringify(RECORDER_CONTRACT_FIXTURES[name]);
        var sample = RECORDER_CONTRACT_FIXTURES[name];
        if (sample.ok === false) {
            assert.throws(function () { validateCommonResponse(sample); });
        } else {
            var data = validateCommonResponse(sample);
            if (Array.isArray(data.entries)) {
                normalizeArchivesDomain(validateArchivesDto(data));
            } else if (data.status !== undefined && data.active_files !== undefined) {
                normalizeStatusDomain(validateStatusDto(data));
            } else if (data.status !== undefined && data.contract_version !== undefined) {
                normalizeHealthDomain(validateHealthDto(data));
            } else {
                normalizeStorageDomain(validateStorageDto(data));
            }
        }
        assert.equal(JSON.stringify(RECORDER_CONTRACT_FIXTURES[name]), snapshot, "input mutated: " + name);
    });
});

test("health.success maps to a health domain model", function () {
    var dto = validateCommonResponse(fixture("health.success"));
    var domain = normalizeHealthDomain(validateHealthDto(dto));
    assert.equal(domain.status, "ok");
    assert.equal(domain.contractVersion, "0.1.0");
    assert.equal(domain.uptimeSeconds, 12345);
});
