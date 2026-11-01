export const PROP_ACCOUNTS_VIEW_SCHEMA = "tradingai-prop-accounts-view/v1";

const ACCOUNT_TYPES = new Set(["NORMAL", "PROP"]);
const ENVIRONMENTS = new Set(["PAPER", "EXTERNAL_SIMULATION", "LIVE"]);
const CONNECTION_STATES = new Set([
    "NOT_CONFIGURED",
    "EXTERNAL_REQUIREMENT_PENDING",
    "CREDENTIAL_REFERENCE_MISSING",
    "NOT_CONNECTED",
    "CONNECTED_READ_ONLY",
    "AUTH_FAILED",
    "SCOPE_MISMATCH",
]);
const QUALITY_STATES = new Set(["COMPLETE", "PARTIAL", "STALE", "FAILED", "UNKNOWN"]);
const RULE_STATES = new Set(["READY", "BLOCKED", "RULES_UNKNOWN", "NOT_APPLICABLE"]);
const DECIMAL = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const ACCOUNT_ID = /^acc_[0-9a-f]{32}$/;
const INVALID_AMOUNT = Object.freeze({ status: "INVALID_AMOUNT" });

const record = (value) => (
    value && typeof value === "object" && !Array.isArray(value) ? value : null
);
const text = (value) => (
    typeof value === "string" && value.trim() ? value.trim() : null
);
const enumValue = (value, allowed) => (
    typeof value === "string" && allowed.has(value) ? value : null
);
const stringList = (value) => (
    Array.isArray(value) ? value.filter((item) => typeof item === "string" && item.trim()) : []
);
const timestamp = (value) => (
    typeof value === "string" && Number.isFinite(Date.parse(value)) ? value : null
);

export const isDecimalString = (value) => typeof value === "string" && DECIMAL.test(value);

export function formatDecimalString(value) {
    if (!isDecimalString(value)) return null;
    const negative = value.startsWith("-");
    const unsigned = negative ? value.slice(1) : value;
    const [integer, fraction] = unsigned.split(".");
    const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return `${negative ? "−" : ""}${grouped}${fraction === undefined ? "" : `.${fraction}`}`;
}

export function normalizeAmount(value) {
    if (value === null || value === undefined) return null;
    const source = record(value);
    if (!source || !isDecimalString(source.amount)) return INVALID_AMOUNT;
    const currency = text(source.currency);
    const unit = text(source.unit);
    if (!currency || !unit || !["ASSET", "USD_EQUIVALENT"].includes(unit)) return INVALID_AMOUNT;
    return Object.freeze({ amount: source.amount, currency, unit });
}

export function displayAmount(value) {
    if (value === null || value === undefined) return "未取得";
    const amount = normalizeAmount(value);
    if (amount === INVALID_AMOUNT) return "未取得（不正な値）";
    const suffix = amount.unit === "USD_EQUIVALENT"
        ? `${amount.currency}相当`
        : amount.currency;
    return `${formatDecimalString(amount.amount)} ${suffix}`;
}

export function displayQuantity(value, unit) {
    if (value === null || value === undefined) return "未取得";
    const formatted = formatDecimalString(value);
    if (!formatted) return "未取得（不正な値）";
    return `${formatted} ${text(unit) ?? "units"}`;
}

export function displayTimestamp(value, timeZone = "Asia/Tokyo") {
    const valid = timestamp(value);
    if (!valid) return "未取得";
    try {
        return new Intl.DateTimeFormat("ja-JP", {
            dateStyle: "medium",
            timeStyle: "medium",
            timeZone,
        }).format(new Date(valid));
    } catch {
        return valid;
    }
}

const normalizeCollection = (value, itemNormalizer) => {
    const source = record(value);
    const sourceItems = Array.isArray(source?.items) ? source.items : null;
    const normalizedItems = sourceItems?.map(itemNormalizer) ?? [];
    const items = normalizedItems.filter(Boolean);
    const invalidItemCount = normalizedItems.length - items.length;
    let quality = enumValue(source?.quality, QUALITY_STATES) ?? "UNKNOWN";
    const missingFields = stringList(source?.missingFields);
    if (sourceItems === null && quality === "COMPLETE") {
        quality = "UNKNOWN";
        missingFields.push("items");
    }
    if (invalidItemCount > 0) {
        quality = items.length === 0 ? "FAILED" : "PARTIAL";
        missingFields.push("invalidItems");
    }
    return Object.freeze({
        quality,
        items,
        invalidItemCount,
        missingFields: Object.freeze([...new Set(missingFields)]),
    });
};

const normalizePosition = (value) => {
    const source = record(value);
    const symbol = text(source?.symbol);
    const side = enumValue(source?.side, new Set(["LONG", "SHORT"]));
    if (!symbol || !side || !isDecimalString(source?.quantity)) return null;
    return Object.freeze({
        symbol,
        side,
        quantity: source.quantity,
        quantityUnit: text(source.quantityUnit) ?? "contracts",
        entryPrice: normalizeAmount(source.entryPrice),
        markPrice: normalizeAmount(source.markPrice),
        unrealizedPnl: normalizeAmount(source.unrealizedPnl),
        status: text(source.status) ?? "OPEN",
    });
};

const normalizeOrder = (value) => {
    const source = record(value);
    const symbol = text(source?.symbol);
    const side = enumValue(source?.side, new Set(["BUY", "SELL"]));
    if (!symbol || !side || !isDecimalString(source?.quantity)) return null;
    return Object.freeze({
        symbol,
        side,
        quantity: source.quantity,
        quantityUnit: text(source.quantityUnit) ?? "contracts",
        price: normalizeAmount(source.price),
        status: text(source.status) ?? "UNKNOWN",
    });
};

const normalizeLimit = (value) => {
    const source = record(value);
    const code = text(source?.code);
    if (!code) return null;
    return Object.freeze({
        code,
        state: text(source.state) ?? "UNKNOWN",
        threshold: normalizeAmount(source.threshold),
        actual: normalizeAmount(source.actual),
        headroom: normalizeAmount(source.headroom),
    });
};

export function normalizeAccount(value) {
    const source = record(value);
    const summary = record(source?.accountSummary);
    const accountId = text(summary?.accountId);
    const accountType = enumValue(summary?.accountType, ACCOUNT_TYPES);
    const environment = enumValue(summary?.environment, ENVIRONMENTS);
    const label = text(summary?.label);
    const platform = text(summary?.platform);
    if (!accountId || !ACCOUNT_ID.test(accountId) || !accountType || !environment || !label || !platform) {
        return null;
    }

    const connectionSource = record(source.connection);
    const observationSource = record(source.observation);
    const rulesSource = record(source.propRules);
    const authoritySource = record(source.executionCapability);
    const contextSource = record(source.aiContext);
    const normalizedLimits = Array.isArray(rulesSource?.limits)
        ? rulesSource.limits.map(normalizeLimit)
        : [];
    const invalidLimitCount = normalizedLimits.filter((limit) => limit === null).length;
    const ruleLimits = normalizedLimits.filter(Boolean);
    const ruleUnknownFields = stringList(rulesSource?.unknownFields);
    if (invalidLimitCount > 0) ruleUnknownFields.push("invalidRuleLimits");
    const connectionState = enumValue(connectionSource?.state, CONNECTION_STATES) ?? "NOT_CONNECTED";
    const dataQuality = enumValue(observationSource?.quality, QUALITY_STATES) ?? "UNKNOWN";
    let ruleReadiness = enumValue(rulesSource?.readiness, RULE_STATES) ?? "RULES_UNKNOWN";
    if (accountType === "PROP" && (dataQuality !== "COMPLETE" || connectionState !== "CONNECTED_READ_ONLY")) {
        ruleReadiness = "RULES_UNKNOWN";
    }
    if (invalidLimitCount > 0) ruleReadiness = "RULES_UNKNOWN";
    if (accountType === "NORMAL") ruleReadiness = "NOT_APPLICABLE";

    return Object.freeze({
        accountSummary: Object.freeze({
            accountId,
            label,
            accountType,
            platform,
            phase: accountType === "PROP" ? (text(summary.phase) ?? "UNKNOWN") : "NOT_APPLICABLE",
            environment,
        }),
        connection: Object.freeze({
            state: connectionState,
            readOnly: connectionSource?.readOnly === true,
            keyEligibility: text(connectionSource?.keyEligibility) ?? "UNKNOWN",
            safeReasonCode: text(connectionSource?.safeReasonCode) ?? "NOT_AVAILABLE",
        }),
        observation: Object.freeze({
            quality: dataQuality,
            freshness: text(observationSource?.freshness) ?? "UNKNOWN",
            observedAt: timestamp(observationSource?.observedAt),
            oldestSourceAt: timestamp(observationSource?.oldestSourceAt),
            newestSourceAt: timestamp(observationSource?.newestSourceAt),
            source: text(observationSource?.source) ?? "FIXTURE",
            balance: normalizeAmount(observationSource?.balance),
            equity: normalizeAmount(observationSource?.equity),
            realizedPnl: normalizeAmount(observationSource?.realizedPnl),
            unrealizedPnl: normalizeAmount(observationSource?.unrealizedPnl),
            missingFields: stringList(observationSource?.missingFields),
        }),
        positions: normalizeCollection(source.positions, normalizePosition),
        openOrders: normalizeCollection(source.openOrders, normalizeOrder),
        propRules: Object.freeze({
            readiness: ruleReadiness,
            ruleSetId: text(rulesSource?.ruleSetId),
            revision: text(rulesSource?.revision),
            phase: accountType === "PROP" ? (text(rulesSource?.phase) ?? "UNKNOWN") : "NOT_APPLICABLE",
            sampleCalculated: rulesSource?.sampleCalculated === true,
            explanation: text(rulesSource?.explanation) ?? "公式ルール・評価は未実装です。",
            limits: ruleLimits,
            unknownFields: Object.freeze([...new Set(ruleUnknownFields)]),
        }),
        executionCapability: Object.freeze({
            authorityState: "DISABLED",
            grantsExecutionAuthority: false,
            reasons: [
                "FIXTURE_ONLY",
                "EXECUTION_ADAPTER_NOT_IMPLEMENTED",
                ...stringList(authoritySource?.reasons),
            ].filter((value, index, values) => values.indexOf(value) === index),
        }),
        aiContext: Object.freeze({
            status: "NOT_INTEGRATED",
            targetAccountId: accountId,
            freshness: text(contextSource?.freshness) ?? "UNKNOWN",
            missingFields: stringList(contextSource?.missingFields),
            grantsExecutionAuthority: false,
        }),
    });
}

export function normalizePropAccountsView(value) {
    const source = record(value);
    if (source?.schemaVersion !== PROP_ACCOUNTS_VIEW_SCHEMA || source?.fixture?.enabled !== true) {
        return Object.freeze({ status: "INVALID", errorCode: "INVALID_FIXTURE_ENVELOPE", accounts: [] });
    }
    const accounts = Array.isArray(source.accounts)
        ? source.accounts.map(normalizeAccount).filter(Boolean)
        : [];
    const ids = accounts.map((account) => account.accountSummary.accountId);
    if (accounts.length === 0 || new Set(ids).size !== ids.length || accounts.length !== source.accounts.length) {
        return Object.freeze({ status: "INVALID", errorCode: "INVALID_ACCOUNT_SCOPE", accounts: [] });
    }
    const viewedAccountId = text(source.viewedAccountId);
    if (!ids.includes(viewedAccountId)) {
        return Object.freeze({ status: "INVALID", errorCode: "VIEWED_ACCOUNT_NOT_FOUND", accounts: [] });
    }
    return Object.freeze({
        status: "READY",
        schemaVersion: source.schemaVersion,
        generatedAt: timestamp(source.generatedAt),
        displayTimezone: text(source.displayTimezone) ?? "Asia/Tokyo",
        fixture: Object.freeze({ enabled: true, label: "サンプル表示 / 実口座未接続" }),
        viewedAccountId,
        accounts: Object.freeze(accounts),
    });
}

export const selectedAccount = (viewModel) => (
    viewModel?.status === "READY"
        ? viewModel.accounts.find(({ accountSummary }) => (
            accountSummary.accountId === viewModel.viewedAccountId
        )) ?? null
        : null
);
