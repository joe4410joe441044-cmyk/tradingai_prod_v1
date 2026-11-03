export const DEFAULT_ACCOUNT_INPUT = Object.freeze({
    label: "架空PROP Challenge口座",
    phase: "CHALLENGE",
    currency: "USDT",
});

export const DEFAULT_EVALUATION_INPUT = Object.freeze({
    initialBalance: "100000.00000000",
    maximumLossPct: "6.0",
    dailyLossPct: "4.0",
    profitTargetPct: "10.0",
    referenceValue: "100000.00000000",
    tradingDay: "2026-11-04",
    timezone: "UTC",
    dayBoundaryLocalTime: "00:00:00",
    balance: "101000.00000000",
    equity: "100500.00000000",
    realizedPnl: "1000.00000000",
    unrealizedPnl: "-500.00000000",
    observedAt: "2026-11-04T02:00:00Z",
    receivedAt: "2026-11-04T02:00:01Z",
    evaluatedAt: "2026-11-04T02:00:02Z",
});

export function buildEvaluationRequest({ requestId, account, input }) {
    return {
        requestId,
        accountId: account.identity.account_id,
        identityRevision: account.identity.revision,
        rules: {
            initialBalance: input.initialBalance,
            maximumLossPct: input.maximumLossPct,
            dailyLossPct: input.dailyLossPct,
            profitTargetPct: input.profitTargetPct,
        },
        baseline: {
            referenceValue: input.referenceValue,
            tradingDay: input.tradingDay,
            timezone: input.timezone,
            dayBoundaryLocalTime: input.dayBoundaryLocalTime,
        },
        observation: {
            balance: input.balance === "" ? null : input.balance,
            equity: input.equity === "" ? null : input.equity,
            realizedPnl: input.realizedPnl === "" ? null : input.realizedPnl,
            unrealizedPnl: input.unrealizedPnl === "" ? null : input.unrealizedPnl,
            observedAt: input.observedAt,
            receivedAt: input.receivedAt,
        },
        evaluation: { evaluatedAt: input.evaluatedAt },
    };
}

export function responseMatchesScope(response, expected) {
    return Boolean(
        response
        && response.requestId === expected.requestId
        && response.accountId === expected.accountId
        && response.identityRevision === expected.identityRevision
        && expected.generation === expected.currentGeneration
    );
}

export function requestIsCurrent(controller, currentController, mounted) {
    return Boolean(mounted && controller === currentController);
}
