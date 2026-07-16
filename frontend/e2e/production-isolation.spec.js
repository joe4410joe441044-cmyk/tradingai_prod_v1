import { expect, test } from "@playwright/test";

import {
    createNetworkIsolation,
} from "./support/networkIsolation.js";

const loadLocalProbePage = async (page) => {
    const response = await page.goto("/favicon.svg");
    expect(response.ok()).toBeTruthy();
};

test.describe("Playwright production network isolation", () => {
    test("blocks production IP HTTP probes before network egress", async ({
        page,
    }) => {
        const isolation = createNetworkIsolation({
            failOnViolation: false,
        });

        await isolation.install(page);
        await loadLocalProbePage(page);

        const result = await page.evaluate(async () => {
            try {
                await fetch("http://35.194.104.74");
                return "resolved";
            } catch (error) {
                return error.name || error.message;
            }
        });

        expect(result).not.toBe("resolved");
        expect(isolation.getCounts()).toMatchObject({
            externalHttpRequests: 1,
            externalWebSocketRequests: 0,
            unmockedApiRequests: 0,
            productionIpRequests: 1,
        });
    });

    test("blocks unmocked local API requests without proxy fallback", async ({
        page,
    }) => {
        const isolation = createNetworkIsolation({
            failOnViolation: false,
        });

        await isolation.install(page);
        await loadLocalProbePage(page);

        const result = await page.evaluate(async () => {
            const response = await fetch("/api/not-mocked");
            const body = await response.json();

            return {
                status: response.status,
                body,
            };
        });

        expect(result).toEqual({
            status: 599,
            body: {
                error: "UNMOCKED_API_REQUEST",
                path: "/api/not-mocked",
            },
        });
        expect(isolation.getCounts()).toMatchObject({
            externalHttpRequests: 0,
            externalWebSocketRequests: 0,
            unmockedApiRequests: 1,
            productionIpRequests: 0,
        });
    });

    test("allows localhost frontend assets", async ({ page }) => {
        const isolation = createNetworkIsolation();

        await isolation.install(page);
        await loadLocalProbePage(page);

        isolation.assertClean(expect);
    });

    test("blocks production IP WebSocket constructors", async ({ page }) => {
        const isolation = createNetworkIsolation({
            failOnViolation: false,
        });

        await isolation.install(page);
        await loadLocalProbePage(page);

        const result = await page.evaluate(() => {
            try {
                new WebSocket("ws://35.194.104.74/ws");
                return "opened";
            } catch (error) {
                return error.message;
            }
        });

        expect(result).toContain("EXTERNAL_WEBSOCKET_REQUEST");
        await expect.poll(() => (
            isolation.getCounts().externalWebSocketRequests
        )).toBe(1);
        expect(isolation.getCounts()).toMatchObject({
            externalHttpRequests: 0,
            externalWebSocketRequests: 1,
            unmockedApiRequests: 0,
            productionIpRequests: 1,
        });
    });
});
