import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
    testDir: "./e2e",
    fullyParallel: false,
    workers: 1,
    timeout: 60_000,
    expect: {
        timeout: 15_000,
    },
    reporter: "line",
    outputDir: "/tmp/tradingai-playwright-results",
    use: {
        baseURL: "http://127.0.0.1:4174",
        trace: "retain-on-failure",
        screenshot: "only-on-failure",
    },
    projects: [
        {
            name: "chromium",
            use: {
                ...devices["Desktop Chrome"],
                channel: "chromium",
            },
        },
    ],
    webServer: {
        command: "VITE_API_BASE=/api VITE_WS_BASE=ws://127.0.0.1:4174 VITE_WS_URL=ws://127.0.0.1:4174/ws npx vite --config vite.playwright.config.js --host 127.0.0.1 --port 4174 --strictPort",
        url: "http://127.0.0.1:4174",
        reuseExistingServer: false,
        timeout: 30_000,
    },
});
