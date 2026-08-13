var ALLOWED_SORT_FIELDS = new Set([
    "start_time",
    "end_time",
    "record_count",
    "compressed_bytes",
    "verification_status",
]);

var ALLOWED_ORDER_VALUES = new Set(["asc", "desc"]);

var ALLOWED_VERIFICATION_STATUS_VALUES = new Set([
    "recording",
    "completed",
    "failed",
    "verified",
]);

function buildParam(params, key, value) {
    if (value === undefined || value === null) {
        return;
    }

    if (key === "page_size") {
        var ps = Number(value);
        if (!Number.isFinite(ps) || ps < 1 || ps > 200) {
            return;
        }
        params.append("page_size", String(Math.floor(ps)));
        return;
    }

    if (key === "page") {
        var p = Number(value);
        if (!Number.isFinite(p) || p < 1) {
            return;
        }
        params.append("page", String(Math.floor(p)));
        return;
    }

    if (key === "sort") {
        if (typeof value === "string" && ALLOWED_SORT_FIELDS.has(value)) {
            params.append("sort", value);
        }
        return;
    }

    if (key === "order") {
        if (typeof value === "string" && ALLOWED_ORDER_VALUES.has(value)) {
            params.append("order", value);
        }
        return;
    }

    if (key === "verification_status") {
        if (typeof value === "string" && ALLOWED_VERIFICATION_STATUS_VALUES.has(value)) {
            params.append("verification_status", value);
        }
        return;
    }

    if (key === "downloadable") {
        if (typeof value === "boolean") {
            params.append("downloadable", value ? "true" : "false");
        }
        return;
    }

    if (key === "stream") {
        if (typeof value === "string" && value.length > 0) {
            params.append("stream", value);
        }
        return;
    }

    if (key === "symbol") {
        if (typeof value === "string" && value.length > 0) {
            params.append("symbol", value);
        }
        return;
    }

    if (key === "from") {
        if (typeof value === "string" && value.length > 0) {
            params.append("from", value);
        }
        return;
    }

    if (key === "to") {
        if (typeof value === "string" && value.length > 0) {
            params.append("to", value);
        }
        return;
    }
}

export function buildArchivesQuery(query) {
    var params = new URLSearchParams();

    if (query === null || typeof query !== "object") {
        return "";
    }

    buildParam(params, "page", query.page);
    buildParam(params, "page_size", query.page_size);
    buildParam(params, "stream", query.stream);
    buildParam(params, "symbol", query.symbol);
    buildParam(params, "from", query.from);
    buildParam(params, "to", query.to);
    buildParam(params, "verification_status", query.verification_status);
    buildParam(params, "downloadable", query.downloadable);
    buildParam(params, "sort", query.sort);
    buildParam(params, "order", query.order);

    var queryString = params.toString();
    return queryString.length > 0 ? "?" + queryString : "";
}
