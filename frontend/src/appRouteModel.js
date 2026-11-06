import {
    PROP_ISOLATED_DEMO_ENABLED,
    PROP_ISOLATED_DEMO_PATH,
} from "./features/prop-accounts/propIsolatedDemoFeature.js";

const BASE_PATHS = new Set([
    "/market-intelligence",
    "/ai-advisor",
    "/money-management",
    "/market-recorder",
    "/supervisor",
    "/account-status",
    "/parameter-settings",
    "/trade-history",
]);

export const resolveAppPath = (pathname, propDemoEnabled = PROP_ISOLATED_DEMO_ENABLED) => {
    if (propDemoEnabled && pathname === PROP_ISOLATED_DEMO_PATH) {
        return PROP_ISOLATED_DEMO_PATH;
    }
    return BASE_PATHS.has(pathname) ? pathname : "/";
};
