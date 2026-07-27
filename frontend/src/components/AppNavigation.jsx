import { useEffect } from "react";

const DASHBOARD_PATH = "/";
const MARKET_INTELLIGENCE_PATH = "/market-intelligence";
const AI_ADVISOR_PATH = "/ai-advisor";
const MONEY_MANAGEMENT_PATH = "/money-management";

const APP_PATHS = new Set([
    DASHBOARD_PATH,
    MARKET_INTELLIGENCE_PATH,
    AI_ADVISOR_PATH,
    MONEY_MANAGEMENT_PATH,
]);

const resolveAppPath = (pathname) => (
    APP_PATHS.has(pathname) ? pathname : DASHBOARD_PATH
);

const NAVIGATION_ITEMS = [
    { label: "DASHBOARD", path: DASHBOARD_PATH },
    { label: "MARKET INTELLIGENCE", path: MARKET_INTELLIGENCE_PATH },
    { label: "AI ADVISOR", path: AI_ADVISOR_PATH },
    { label: "MONEY MANAGEMENT", path: MONEY_MANAGEMENT_PATH },
];

export default function AppNavigation({ currentPath, onPathChange }) {
    useEffect(() => {
        const syncPath = () => {
            const resolvedPath = resolveAppPath(window.location.pathname);

            if (resolvedPath !== window.location.pathname) {
                window.history.replaceState({}, "", resolvedPath);
            }

            onPathChange(resolvedPath);
        };

        syncPath();
        window.addEventListener("popstate", syncPath);

        return () => window.removeEventListener("popstate", syncPath);
    }, [onPathChange]);

    const navigate = (path) => {
        if (path === currentPath) {
            return;
        }

        window.history.pushState({}, "", path);
        onPathChange(path);
    };

    return (
        <nav aria-label="Primary" className="mi-app-navigation">
            {NAVIGATION_ITEMS.map(({ label, path }) => {
                const isActive = currentPath === path;

                return (
                    <button
                        aria-current={isActive ? "page" : undefined}
                        className={isActive
                            ? "mi-app-navigation__item mi-app-navigation__item--active"
                            : "mi-app-navigation__item"
                        }
                        key={path}
                        onClick={() => navigate(path)}
                        type="button"
                    >
                        {label}
                    </button>
                );
            })}
        </nav>
    );
}
