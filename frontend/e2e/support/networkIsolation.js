const DEFAULT_ALLOWED_HOSTS = [
    "127.0.0.1",
    "localhost",
];

const PRODUCTION_HOSTS = [
    "35.194.104.74",
];

const PASS_THROUGH_PROTOCOLS = new Set([
    "about:",
    "blob:",
    "data:",
]);

const jsonFulfill = async (route, body, status = 599) => {
    await route.fulfill({
        status,
        contentType: "application/json",
        headers: {
            "cache-control": "no-store",
        },
        body: JSON.stringify(body),
    });
};

const safeUrl = (rawUrl, baseUrl = "http://127.0.0.1") => {
    try {
        return new URL(rawUrl, baseUrl);
    } catch {
        return null;
    }
};

const unique = (values) => [...new Set(values)];

export const createNetworkIsolation = ({
    allowedHosts = DEFAULT_ALLOWED_HOSTS,
    apiHandler = null,
    failOnViolation = true,
} = {}) => {
    const allowedHostSet = new Set(allowedHosts);
    const externalHttpRequests = [];
    const externalWebSocketRequests = [];
    const unmockedApiRequests = [];
    const productionIpRequests = [];

    const isAllowedUrl = (url) => (
        url
        && (
            PASS_THROUGH_PROTOCOLS.has(url.protocol)
            || allowedHostSet.has(url.hostname)
        )
    );

    const recordProductionIfNeeded = (rawUrl) => {
        const url = safeUrl(rawUrl);

        if (
            url
            && PRODUCTION_HOSTS.includes(url.hostname)
        ) {
            productionIpRequests.push(rawUrl);
        }
    };

    const recordExternalHttp = (rawUrl) => {
        externalHttpRequests.push(rawUrl);
        recordProductionIfNeeded(rawUrl);
    };

    const recordExternalWebSocket = (rawUrl) => {
        externalWebSocketRequests.push(rawUrl);
        recordProductionIfNeeded(rawUrl);
    };

    const recordUnmockedApi = (path) => {
        unmockedApiRequests.push(path);
    };

    const installWebSocketGuard = async (page) => {
        await page.exposeBinding(
            "__tradingAiRecordNetworkViolation",
            (_source, payload) => {
                if (payload?.kind === "websocket" && payload.url) {
                    recordExternalWebSocket(payload.url);
                }
            },
        );

        await page.addInitScript((hosts) => {
            const allowed = new Set(hosts);
            const nativeWebSocket = window.WebSocket;

            const recordBlockedWebSocket = (url) => {
                window.__tradingAiNetworkIsolation =
                    window.__tradingAiNetworkIsolation || {
                        externalWebSocketRequests: [],
                    };
                window.__tradingAiNetworkIsolation
                    .externalWebSocketRequests
                    .push(url);

                if (window.__tradingAiRecordNetworkViolation) {
                    window.__tradingAiRecordNetworkViolation({
                        kind: "websocket",
                        url,
                    });
                }
            };

            function GuardedWebSocket(url, protocols) {
                const resolved = new URL(url, window.location.href);

                if (!allowed.has(resolved.hostname)) {
                    recordBlockedWebSocket(resolved.href);
                    throw new Error(
                        `EXTERNAL_WEBSOCKET_REQUEST ${resolved.href}`,
                    );
                }

                if (protocols === undefined) {
                    return new nativeWebSocket(url);
                }

                return new nativeWebSocket(url, protocols);
            }

            Object.setPrototypeOf(GuardedWebSocket, nativeWebSocket);
            GuardedWebSocket.prototype = nativeWebSocket.prototype;
            window.WebSocket = GuardedWebSocket;
        }, allowedHosts);

        page.on("websocket", (webSocket) => {
            const url = safeUrl(webSocket.url());

            if (!isAllowedUrl(url)) {
                recordExternalWebSocket(webSocket.url());
            }
        });
    };

    const install = async (page) => {
        await installWebSocketGuard(page);

        await page.route("**/*", async (route) => {
            const request = route.request();
            const rawUrl = request.url();
            const url = safeUrl(rawUrl);

            if (!isAllowedUrl(url)) {
                recordExternalHttp(rawUrl);
                await route.abort("blockedbyclient");

                if (failOnViolation) {
                    throw new Error(`EXTERNAL_HTTP_REQUEST ${rawUrl}`);
                }

                return;
            }

            if (url.pathname.startsWith("/api/")) {
                if (apiHandler) {
                    await apiHandler(route, {
                        path: url.pathname,
                        url,
                    });
                    return;
                }

                recordUnmockedApi(url.pathname);
                await jsonFulfill(route, {
                    error: "UNMOCKED_API_REQUEST",
                    path: url.pathname,
                });

                if (failOnViolation) {
                    throw new Error(`UNMOCKED_API_REQUEST ${url.pathname}`);
                }

                return;
            }

            await route.continue();
        });
    };

    const getCounts = () => ({
        externalHttpRequests: externalHttpRequests.length,
        externalWebSocketRequests: externalWebSocketRequests.length,
        unmockedApiRequests: unmockedApiRequests.length,
        productionIpRequests: productionIpRequests.length,
    });

    const assertClean = (expect) => {
        expect(unique(externalHttpRequests)).toEqual([]);
        expect(unique(externalWebSocketRequests)).toEqual([]);
        expect(unique(unmockedApiRequests)).toEqual([]);
        expect(unique(productionIpRequests)).toEqual([]);
    };

    return {
        install,
        assertClean,
        getCounts,
        getExternalHttpRequests() {
            return [...externalHttpRequests];
        },
        getExternalWebSocketRequests() {
            return [...externalWebSocketRequests];
        },
        getExternalRequests() {
            return [
                ...externalHttpRequests,
                ...externalWebSocketRequests,
            ];
        },
        getProductionIpRequests() {
            return [...productionIpRequests];
        },
        getUnmockedApiRequests() {
            return [...unmockedApiRequests];
        },
    };
};
