export function createExchangeAdapter({
    exchangeName = "GENERIC",
} = {}) {

    const exchangeState = {

        exchangeName,

        connected: false,

        authenticated: false,

        exchangeStatus: "DISCONNECTED",

        exchangeLatency: 0,

        lastExchangeSync: 0,

        lastOrderId: null,

        activeOrders: [],

        exchangePosition: null,

        exchangeBalance: 0,

        verificationFailures: 0,

        lastVerificationStatus: "UNKNOWN",

        lastExecutionVerification: null,

        lastBalanceSync: null,

        lastPositionSync: null,

        exchangePositionVerified: false,

        exchangeBalanceVerified: false,

        exchangeMismatchDetected: false,

        exchangeReconciliationStatus: "NOT_SYNCED",

        lastExchangeSyncPacket: null,

        lastMismatchReport: null,

        authoritativePosition: null,

        authoritativeBalance: 0,

        reconciliationLatency: 0,

        verificationTimestamp: 0,

    };

    function connectExchange() {

        exchangeState.connected = true;

        exchangeState.exchangeStatus =
            "CONNECTED";

        exchangeState.lastExchangeSync =
            Date.now();

        return createExchangeTelemetryPacket();

    }

    function disconnectExchange() {

        exchangeState.connected = false;

        exchangeState.authenticated = false;

        exchangeState.exchangeStatus =
            "DISCONNECTED";

        return createExchangeTelemetryPacket();

    }

    function authenticateExchange({
        apiKey,
        apiSecret,
        passphrase,
    } = {}) {

        if (
            !apiKey ||
            !apiSecret
        ) {

            exchangeState.authenticated = false;

            exchangeState.exchangeStatus =
                "AUTH_FAILED";

            return {
                success: false,
                reason: "MISSING_CREDENTIALS",
            };

        }

        exchangeState.authenticated = true;

        exchangeState.exchangeStatus =
            "AUTHENTICATED";

        exchangeState.lastExchangeSync =
            Date.now();

        return {
            success: true,
            passphraseProvided:
                Boolean(passphrase),
        };

    }

    function placeOrder({
        symbol,
        side,
        quantity,
        orderType = "MARKET",
        reduceOnly = false,
    } = {}) {

        const orderId =
            `SIM_${Date.now()}`;

        const orderPacket = {

            orderId,

            symbol,

            side,

            quantity,

            orderType,

            reduceOnly,

            status: "SIMULATED_ACCEPTED",

            createdAt: Date.now(),

        };

        exchangeState.lastOrderId =
            orderId;

        exchangeState.activeOrders.push(
            orderPacket
        );

        exchangeState.lastExchangeSync =
            Date.now();

        return {
            success: true,
            simulated: true,
            order: orderPacket,
        };

    }

    function closePosition({
        symbol,
    } = {}) {

        exchangeState.exchangePosition =
            null;

        exchangeState.authoritativePosition =
            null;

        exchangeState.lastPositionSync = {
            symbol,
            closedAt: Date.now(),
        };

        return {
            success: true,
            simulated: true,
            symbol,
            action: "CLOSE_POSITION",
        };

    }

    function reducePosition({
        symbol,
        reductionSize,
    } = {}) {

        return {
            success: true,
            simulated: true,
            symbol,
            reductionSize,
            action: "REDUCE_POSITION",
        };

    }

    function cancelOrder({
        orderId,
    } = {}) {

        exchangeState.activeOrders =
            exchangeState.activeOrders.filter(
                (order) =>
                    order.orderId !== orderId
            );

        exchangeState.lastExchangeSync =
            Date.now();

        return {
            success: true,
            simulated: true,
            orderId,
            action: "CANCEL_ORDER",
        };

    }

    function syncExchangePosition({
        position = null,
    } = {}) {

        exchangeState.exchangePosition =
            position;

        exchangeState.authoritativePosition =
            position;

        exchangeState.lastPositionSync = {
            syncedAt: Date.now(),
            position,
        };

        exchangeState.lastExchangeSync =
            Date.now();

        return {
            success: true,
            position,
        };

    }

    function syncExchangeBalance({
        balance = 0,
    } = {}) {

        exchangeState.exchangeBalance =
            Number(balance) || 0;

        exchangeState.authoritativeBalance =
            Number(balance) || 0;

        exchangeState.lastBalanceSync = {
            syncedAt: Date.now(),
            balance:
                exchangeState.exchangeBalance,
        };

        exchangeState.lastExchangeSync =
            Date.now();

        return {
            success: true,
            balance:
                exchangeState.exchangeBalance,
        };

    }

    function verifyExchangePosition({
        localPosition,
        exchangePosition,
    } = {}) {

        const localSide =
            localPosition?.side || null;

        const exchangeSide =
            exchangePosition?.side || null;

        const localQuantity =
            Number(
                localPosition?.quantity || 0
            );

        const exchangeQuantity =
            Number(
                exchangePosition?.quantity || 0
            );

        const localSymbol =
            localPosition?.symbol || null;

        const exchangeSymbol =
            exchangePosition?.symbol || null;

        const quantityDifference =
            Math.abs(
                localQuantity -
                exchangeQuantity
            );

        const sideMismatch =
            localSide !== exchangeSide;

        const symbolMismatch =
            localSymbol !== exchangeSymbol;

        const quantityMismatch =
            quantityDifference > 0.00001;

        const missingExchangePosition =
            localQuantity > 0 &&
            exchangeQuantity <= 0;

        const ghostExchangePosition =
            localQuantity <= 0 &&
            exchangeQuantity > 0;

        const verified =
            !sideMismatch &&
            !symbolMismatch &&
            !quantityMismatch &&
            !missingExchangePosition &&
            !ghostExchangePosition;

        exchangeState.exchangePositionVerified =
            verified;

        exchangeState.verificationTimestamp =
            Date.now();

        exchangeState.lastPositionSync = {

            verified,

            sideMismatch,

            symbolMismatch,

            quantityMismatch,

            missingExchangePosition,

            ghostExchangePosition,

            quantityDifference,

            checkedAt: Date.now(),

            localPosition,

            exchangePosition,

        };

        exchangeState.lastVerificationStatus =
            verified
                ? "POSITION_VERIFIED"
                : "POSITION_MISMATCH";

        if (!verified) {

            exchangeState.verificationFailures += 1;

        }

        return {

            verified,

            sideMismatch,

            symbolMismatch,

            quantityMismatch,

            missingExchangePosition,

            ghostExchangePosition,

            quantityDifference,

            localPosition,

            exchangePosition,

            checkedAt: Date.now(),

        };

    }

    function verifyExchangeBalance({
        localBalance = 0,
        exchangeBalance = 0,
        allowedDifference = 0.00001,
    } = {}) {

        const normalizedLocalBalance =
            Number(localBalance || 0);

        const normalizedExchangeBalance =
            Number(exchangeBalance || 0);

        const balanceDifference =
            Math.abs(
                normalizedLocalBalance -
                normalizedExchangeBalance
            );

        const verified =
            balanceDifference <=
            allowedDifference;

        exchangeState.exchangeBalanceVerified =
            verified;

        exchangeState.verificationTimestamp =
            Date.now();

        if (!verified) {

            exchangeState.verificationFailures += 1;

            exchangeState.lastVerificationStatus =
                "BALANCE_MISMATCH";

        } else {

            exchangeState.lastVerificationStatus =
                "BALANCE_VERIFIED";

        }

        exchangeState.lastBalanceSync = {
            verified,
            localBalance:
                normalizedLocalBalance,
            exchangeBalance:
                normalizedExchangeBalance,
            balanceDifference,
            checkedAt: Date.now(),
        };

        return {
            verified,
            localBalance:
                normalizedLocalBalance,
            exchangeBalance:
                normalizedExchangeBalance,
            balanceDifference,
            checkedAt: Date.now(),
        };

    }

    function verifyExchangeExecution({
        localExecution,
        exchangeExecution,
    } = {}) {

        const localOrderId =
            localExecution?.orderId;

        const exchangeOrderId =
            exchangeExecution?.orderId;

        const verified =
            Boolean(localOrderId) &&
            localOrderId === exchangeOrderId;

        if (!verified) {

            exchangeState.verificationFailures += 1;

            exchangeState.lastVerificationStatus =
                "FAILED";

        } else {

            exchangeState.lastVerificationStatus =
                "VERIFIED";

        }

        exchangeState.lastExecutionVerification = {
            verified,
            verifiedAt: Date.now(),
            localOrderId,
            exchangeOrderId,
        };

        return {
            verified,
            verificationFailures:
                exchangeState.verificationFailures,
        };

    }

    function detectExchangeMismatch({
        localPosition = null,
        exchangePosition = null,
        localBalance = 0,
        exchangeBalance = 0,
        localExecution = null,
        exchangeExecution = null,
        reconciliationTimeout = 10000,
    } = {}) {

        const currentTimestamp =
            Date.now();

        const positionVerification =
            verifyExchangePosition({
                localPosition,
                exchangePosition,
            });

        const balanceVerification =
            verifyExchangeBalance({
                localBalance,
                exchangeBalance,
            });

        const executionVerification =
            verifyExchangeExecution({
                localExecution,
                exchangeExecution,
            });

        const lastVerificationTime =
            exchangeState.lastExecutionVerification
                ?.verifiedAt || 0;

        const staleStateDetected =
            currentTimestamp -
            lastVerificationTime >
            reconciliationTimeout;

        const positionMismatch =
            !positionVerification.verified;

        const balanceMismatch =
            !balanceVerification.verified;

        const executionMismatch =
            !executionVerification.verified;

        const exchangeMismatchDetected =
            positionMismatch ||
            balanceMismatch ||
            executionMismatch ||
            staleStateDetected;

        exchangeState.exchangeMismatchDetected =
            exchangeMismatchDetected;

        exchangeState.exchangeReconciliationStatus =
            exchangeMismatchDetected
                ? "RECONCILIATION_REQUIRED"
                : "RECONCILED";

        exchangeState.lastMismatchReport = {
            positionMismatch,
            balanceMismatch,
            executionMismatch,
            staleStateDetected,
            checkedAt: currentTimestamp,
            reconciliationTimeout,
        };

        return {
            positionMismatch,
            balanceMismatch,
            executionMismatch,
            staleStateDetected,
            exchangeMismatchDetected,
            reconciliationStatus:
                exchangeState.exchangeReconciliationStatus,
            checkedAt: currentTimestamp,
        };

    }

    function reconcileExchangeState({
        localPosition = null,
        exchangePosition = null,
        localBalance = 0,
        exchangeBalance = 0,
        localExecution = null,
        exchangeExecution = null,
    } = {}) {

        const reconciliationStartedAt =
            Date.now();

        const mismatchReport =
            detectExchangeMismatch({
                localPosition,
                exchangePosition,
                localBalance,
                exchangeBalance,
                localExecution,
                exchangeExecution,
            });

        exchangeState.authoritativePosition =
            exchangePosition;

        exchangeState.authoritativeBalance =
            Number(exchangeBalance || 0);

        exchangeState.reconciliationLatency =
            Date.now() -
            reconciliationStartedAt;

        exchangeState.lastExchangeSync =
            Date.now();

        return {
            reconciled:
                !mismatchReport.exchangeMismatchDetected,
            mismatchReport,
            reconciliationLatency:
                exchangeState.reconciliationLatency,
            authoritativePosition:
                exchangeState.authoritativePosition,
            authoritativeBalance:
                exchangeState.authoritativeBalance,
        };

    }

    function createExchangeSyncPacket() {

        const packet = {

            exchangeName:
                exchangeState.exchangeName,

            exchangeConnected:
                exchangeState.connected,

            exchangeAuthenticated:
                exchangeState.authenticated,

            exchangeStatus:
                exchangeState.exchangeStatus,

            exchangePositionVerified:
                exchangeState.exchangePositionVerified,

            exchangeBalanceVerified:
                exchangeState.exchangeBalanceVerified,

            exchangeMismatchDetected:
                exchangeState.exchangeMismatchDetected,

            exchangeReconciliationStatus:
                exchangeState.exchangeReconciliationStatus,

            authoritativePosition:
                exchangeState.authoritativePosition,

            authoritativeBalance:
                exchangeState.authoritativeBalance,

            reconciliationLatency:
                exchangeState.reconciliationLatency,

            verificationTimestamp:
                exchangeState.verificationTimestamp,

            lastVerificationStatus:
                exchangeState.lastVerificationStatus,

            lastExecutionVerification:
                exchangeState.lastExecutionVerification,

            lastMismatchReport:
                exchangeState.lastMismatchReport,

            lastExchangeSync:
                exchangeState.lastExchangeSync,

            generatedAt:
                Date.now(),

        };

        exchangeState.lastExchangeSyncPacket =
            packet;

        return packet;

    }

    function createExchangeTelemetryPacket() {

        return {

            exchangeName:
                exchangeState.exchangeName,

            connected:
                exchangeState.connected,

            authenticated:
                exchangeState.authenticated,

            exchangeStatus:
                exchangeState.exchangeStatus,

            exchangeLatency:
                exchangeState.exchangeLatency,

            lastExchangeSync:
                exchangeState.lastExchangeSync,

            lastOrderId:
                exchangeState.lastOrderId,

            activeOrders:
                exchangeState.activeOrders,

            exchangePosition:
                exchangeState.exchangePosition,

            exchangeBalance:
                exchangeState.exchangeBalance,

            verificationFailures:
                exchangeState.verificationFailures,

            lastVerificationStatus:
                exchangeState.lastVerificationStatus,

            lastExecutionVerification:
                exchangeState.lastExecutionVerification,

            lastBalanceSync:
                exchangeState.lastBalanceSync,

            lastPositionSync:
                exchangeState.lastPositionSync,

            exchangePositionVerified:
                exchangeState.exchangePositionVerified,

            exchangeBalanceVerified:
                exchangeState.exchangeBalanceVerified,

            exchangeMismatchDetected:
                exchangeState.exchangeMismatchDetected,

            exchangeReconciliationStatus:
                exchangeState.exchangeReconciliationStatus,

            lastExchangeSyncPacket:
                exchangeState.lastExchangeSyncPacket,

            authoritativePosition:
                exchangeState.authoritativePosition,

            authoritativeBalance:
                exchangeState.authoritativeBalance,

            reconciliationLatency:
                exchangeState.reconciliationLatency,

            verificationTimestamp:
                exchangeState.verificationTimestamp,

            lastMismatchReport:
                exchangeState.lastMismatchReport,

        };

    }

    function getExchangeState() {

        return exchangeState;

    }

    return {

        connectExchange,

        disconnectExchange,

        authenticateExchange,

        placeOrder,

        closePosition,

        reducePosition,

        cancelOrder,

        syncExchangePosition,

        syncExchangeBalance,

        verifyExchangePosition,

        verifyExchangeBalance,

        verifyExchangeExecution,

        detectExchangeMismatch,

        reconcileExchangeState,

        createExchangeSyncPacket,

        createExchangeTelemetryPacket,

        getExchangeState,

    };

}
