import { expect, test } from "@playwright/test";

const SAFE_START_PAYLOAD = {
    symbol: "XRPUSDT",
    exchange: "kucoin",
    risk_percent: 1,
    position_size: 100,
    max_drawdown_pct: 5,
    sl_percent: 1,
    tp_percent: 1,
    leverage: 5,
    timeframe: "1m",
    dry_run: true,
    mode: "paper",
};

const getStatus = async (request) => {
    const response = await request.get("/api/bot/status");
    expect(response.ok()).toBeTruthy();
    return response.json();
};

const waitForStatus = async (request, read, expected) => {
    await expect.poll(async () => {
        const status = await getStatus(request);
        return read(status);
    }, {
        timeout: 45_000,
    }).toEqual(expected);
};

const emergencyTimelineFor = (status, operationId) => (
    status.runtime_health?.timeline ?? []
).filter((event) => (
    event.type === "EMERGENCY"
    && event.operationId === operationId
));

const ensureReady = async (request) => {
    await request.post("/api/bot/stop");

    let status = await getStatus(request);
    if (status.emergency?.state === "LOCKED") {
        const unlockResponse = await request.post(
            "/api/governance/emergency/unlock",
        );
        expect(unlockResponse.ok()).toBeTruthy();
    }

    await waitForStatus(
        request,
        (current) => ({
            bot: current.status,
            loopEnabled: current.loopEnabled,
            emergencyState: current.emergency?.state,
        }),
        {
            bot: "STOPPED",
            loopEnabled: false,
            emergencyState: "READY",
        },
    );
};

test.describe("Emergency Stop and Unlock E2E", () => {
    test.beforeEach(async ({ request }) => {
        await ensureReady(request);
    });

    test.afterEach(async ({ request }) => {
        await request.post("/api/bot/stop");
        const status = await getStatus(request);
        if (status.emergency?.state === "LOCKED") {
            await request.post("/api/governance/emergency/unlock");
        }
    });

    test("locks after emergency stop and unlocks without restarting execution", async ({
        page,
        request,
    }) => {
        const initial = await getStatus(request);
        expect(initial.selectedMode).toBe("PAPER");
        expect(initial.dryRun).toBe(true);
        expect(initial.realOrderAllowed).toBe(false);
        expect(initial.executionMode).toBe("SIMULATION");
        expect(initial.status).toBe("STOPPED");
        expect(initial.loopEnabled).toBe(false);
        expect(initial.autoTradeEnabled).toBe(false);
        expect(initial.executionEnabled).toBe(false);
        expect(initial.emergency).toMatchObject({
            active: false,
            locked: false,
            state: "READY",
        });
        expect(initial.runtime_health?.timeline ?? []).toHaveLength(0);

        await page.goto("/");
        await expect(page.getByText("EMERGENCY STATUS")).toBeVisible();
        await expect(
            page.locator(".operation-emergency-status__state"),
        ).toHaveText("READY");
        await expect(page.getByText("NO EVENTS", { exact: true })).toBeVisible();
        await expect(
            page.getByRole("button", { name: "緊急状態を解除" }),
        ).toHaveCount(0);

        const startResponse = await request.post(
            "/api/bot/start",
            {
                data: SAFE_START_PAYLOAD,
            },
        );
        expect(startResponse.ok()).toBeTruthy();

        await waitForStatus(
            request,
            (current) => ({
                bot: current.status,
                loopEnabled: current.loopEnabled,
                emergencyState: current.emergency?.state,
                realOrderAllowed: current.realOrderAllowed,
            }),
            {
                bot: "RUNNING",
                loopEnabled: true,
                emergencyState: "READY",
                realOrderAllowed: false,
            },
        );

        await page.reload();
        await expect(page.getByText("EMERGENCY STATUS")).toBeVisible();
        const emergencyButton = page.getByRole(
            "button",
            {
                name: /EMERGENCY STOP/,
            },
        );
        await expect(emergencyButton).toBeEnabled();

        await emergencyButton.click();
        const emergencyDialog = page.getByRole(
            "dialog",
            {
                name: "Confirm emergency stop",
            },
        );
        await expect(emergencyDialog).toBeVisible();

        const emergencyResponsePromise = page.waitForResponse((response) => (
            response.url().endsWith("/api/governance/emergency-orchestrate")
            && response.request().method() === "POST"
        ));
        await emergencyDialog.getByRole(
            "button",
            {
                name: "CONFIRM EMERGENCY",
            },
        ).click();

        const emergencyResponse = await emergencyResponsePromise;
        expect(emergencyResponse.ok()).toBeTruthy();
        const emergencyResult = await emergencyResponse.json();
        expect(emergencyResult).toMatchObject({
            success: true,
            completed: true,
            partial: false,
            state_unknown: false,
            position_remaining: false,
            path: "paper",
            retryable: false,
        });

        await waitForStatus(
            request,
            (current) => ({
                bot: current.status,
                loopEnabled: current.loopEnabled,
                loopState: current.loopState,
                autoTradeEnabled: current.autoTradeEnabled,
                executionEnabled: current.executionEnabled,
                emergencyActive: current.emergency?.active,
                emergencyLocked: current.emergency?.locked,
                emergencyState: current.emergency?.state,
            }),
            {
                bot: "STOPPED",
                loopEnabled: false,
                loopState: "STOPPED",
                autoTradeEnabled: false,
                executionEnabled: false,
                emergencyActive: true,
                emergencyLocked: true,
                emergencyState: "LOCKED",
            },
        );

        let lockedStatus = await getStatus(request);
        const operationId = lockedStatus.emergency.lastResult.operationId;
        expect(lockedStatus.emergency.lastResult).toMatchObject({
            state: "LOCKED",
            result: "SUCCESS",
            path: "paper",
            positionRemaining: false,
            stateUnknown: false,
            retryable: false,
        });

        const guardResponse = await request.post(
            "/api/governance/execution",
            {
                data: {
                    enabled: true,
                },
            },
        );
        expect(guardResponse.status()).toBe(409);
        const guardBody = await guardResponse.json();
        expect(guardBody.detail.reason).toBe(
            "AUTO_TRADE_BLOCKED_BY_EMERGENCY_LOCK",
        );

        await page.reload();
        await expect(page.getByText("EMERGENCY STATUS")).toBeVisible();
        await expect(
            page.locator(".operation-emergency-status__state"),
        ).toHaveText("STOPPED SAFELY");
        await expect(page.getByText("BOT STOPPED")).toBeVisible();
        await expect(page.getByText("EXECUTION DISABLED")).toBeVisible();
        await expect(page.getByText("Execution path: PAPER")).toBeVisible();
        await expect(page.getByText("EMERGENCY STOPPED SAFELY")).toBeVisible();
        await expect(
            page.getByRole("switch", { name: "Toggle trading loop" }),
        ).toBeDisabled();
        await expect(
            page.getByRole("switch", { name: "Toggle automatic trading" }),
        ).toBeDisabled();
        await expect(emergencyButton).toBeDisabled();

        const unlockButton = page.getByRole(
            "button",
            {
                name: "緊急状態を解除",
            },
        );
        await expect(unlockButton).toBeEnabled();
        await unlockButton.click();
        const unlockDialog = page.getByRole(
            "dialog",
            {
                name: "緊急状態を解除しますか？",
            },
        );
        await expect(unlockDialog).toHaveAttribute("aria-modal", "true");
        await expect(unlockDialog).toContainText(
            "解除後もBOTは起動しません。",
        );
        await expect(unlockDialog).toContainText(
            "LOOPとAUTO TRADEもOFFのままです。",
        );
        await unlockDialog.getByRole(
            "button",
            {
                name: "キャンセル",
            },
        ).click();

        lockedStatus = await getStatus(request);
        expect(lockedStatus.emergency).toMatchObject({
            active: true,
            locked: true,
            state: "LOCKED",
        });

        await unlockButton.click();
        const unlockConfirmDialog = page.getByRole(
            "dialog",
            {
                name: "緊急状態を解除しますか？",
            },
        );
        const unlockResponsePromise = page.waitForResponse((response) => (
            response.url().endsWith("/api/governance/emergency/unlock")
            && response.request().method() === "POST"
        ));
        await unlockConfirmDialog.getByRole(
            "button",
            {
                name: "緊急状態を解除",
            },
        ).click();

        const unlockResponse = await unlockResponsePromise;
        expect(unlockResponse.ok()).toBeTruthy();
        const unlockResult = await unlockResponse.json();
        expect(unlockResult).toMatchObject({
            success: true,
            unlocked: true,
            emergency_stop: false,
            emergency_state: "READY",
            execution_enabled: false,
        });

        await waitForStatus(
            request,
            (current) => ({
                bot: current.status,
                loopEnabled: current.loopEnabled,
                loopState: current.loopState,
                autoTradeEnabled: current.autoTradeEnabled,
                executionEnabled: current.executionEnabled,
                emergencyActive: current.emergency?.active,
                emergencyLocked: current.emergency?.locked,
                emergencyState: current.emergency?.state,
                operationId: current.emergency?.lastResult?.operationId,
            }),
            {
                bot: "STOPPED",
                loopEnabled: false,
                loopState: "STOPPED",
                autoTradeEnabled: false,
                executionEnabled: false,
                emergencyActive: false,
                emergencyLocked: false,
                emergencyState: "READY",
                operationId,
            },
        );

        const finalStatus = await getStatus(request);
        const emergencyEvents = emergencyTimelineFor(
            finalStatus,
            operationId,
        );
        expect(emergencyEvents.map((event) => event.event)).toEqual([
            "EMERGENCY_STARTED",
            "EMERGENCY_COMPLETED",
            "EMERGENCY_UNLOCKED",
        ]);
        expect(
            emergencyEvents.filter((event) => event.event === "EMERGENCY_STARTED"),
        ).toHaveLength(1);
        expect(
            emergencyEvents.filter((event) => event.event === "EMERGENCY_COMPLETED"),
        ).toHaveLength(1);
        expect(
            emergencyEvents.filter((event) => event.event === "EMERGENCY_UNLOCKED"),
        ).toHaveLength(1);
        expect(
            emergencyEvents.some((event) => event.event === "EMERGENCY_ACTION_REQUIRED"),
        ).toBe(false);

        await page.reload();
        await expect(page.getByText("EMERGENCY STATUS")).toBeVisible();
        await expect(
            page.locator(".operation-emergency-status__state"),
        ).toHaveText("READY");
        await expect(page.getByText("EMERGENCY UNLOCKED")).toBeVisible();
        const loopSwitch = page.getByRole(
            "switch",
            {
                name: "Toggle trading loop",
            },
        );
        const autoTradeSwitch = page.getByRole(
            "switch",
            {
                name: "Toggle automatic trading",
            },
        );
        await expect(loopSwitch).toBeEnabled();
        await expect(loopSwitch).toHaveAttribute("aria-checked", "false");
        await expect(autoTradeSwitch).toHaveAttribute("aria-checked", "false");
        await expect(
            page.getByRole("button", { name: /EMERGENCY STOP/ }),
        ).toBeEnabled();
    });
});
