import {
    PROP_ISOLATED_DEMO_ENABLED,
    PROP_ISOLATED_DEMO_PATH,
} from "../features/prop-accounts/propIsolatedDemoFeature.js";

const NAVIGATION_ITEMS = [
    { label: "DASHBOARD", path: "/" },
    { label: "MARKET INTELLIGENCE", path: "/market-intelligence" },
    { label: "AI ADVISOR", path: "/ai-advisor" },
    { label: "MONEY MANAGEMENT", path: "/money-management" },
    { label: "MARKET RECORDER", path: "/market-recorder" },
    { label: "SUPERVISOR", path: "/supervisor" },
    { label: "ACCOUNT STATUS", path: "/account-status" },
    { label: "PARAMETER SETTINGS", path: "/parameter-settings" },
    { label: "TRADE HISTORY / 取引履歴", path: "/trade-history" },
];

export const buildNavigationItems = (propDemoEnabled = PROP_ISOLATED_DEMO_ENABLED) => (
    propDemoEnabled
        ? [...NAVIGATION_ITEMS, { label: "PROP隔離デモ", path: PROP_ISOLATED_DEMO_PATH }]
        : NAVIGATION_ITEMS
);

export const resolveNavigationPath = (pathname, propDemoEnabled = PROP_ISOLATED_DEMO_ENABLED) => (
    buildNavigationItems(propDemoEnabled).some(({ path }) => path === pathname)
        ? pathname
        : "/"
);
