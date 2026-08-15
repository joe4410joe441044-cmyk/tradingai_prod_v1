import { useEffect, useRef, useState } from "react";

import { reorderNavigationItems } from "./appNavigationModel";

const DASHBOARD_PATH = "/";
const MARKET_INTELLIGENCE_PATH = "/market-intelligence";
const AI_ADVISOR_PATH = "/ai-advisor";
const MONEY_MANAGEMENT_PATH = "/money-management";
const MARKET_RECORDER_PATH = "/market-recorder";
const SUPERVISOR_PATH = "/supervisor";

const APP_PATHS = new Set([
    DASHBOARD_PATH,
    MARKET_INTELLIGENCE_PATH,
    AI_ADVISOR_PATH,
    MONEY_MANAGEMENT_PATH,
    MARKET_RECORDER_PATH,
    SUPERVISOR_PATH,
]);

const resolveAppPath = (pathname) => (
    APP_PATHS.has(pathname) ? pathname : DASHBOARD_PATH
);

const NAVIGATION_ITEMS = [
    { label: "DASHBOARD", path: DASHBOARD_PATH },
    { label: "MARKET INTELLIGENCE", path: MARKET_INTELLIGENCE_PATH },
    { label: "AI ADVISOR", path: AI_ADVISOR_PATH },
    { label: "MONEY MANAGEMENT", path: MONEY_MANAGEMENT_PATH },
    { label: "MARKET RECORDER", path: MARKET_RECORDER_PATH },
    { label: "SUPERVISOR", path: SUPERVISOR_PATH },
];

export function NavigationTabs({
    currentPath,
    draggedPath,
    items,
    navigate,
    onDragEnd,
    onDragEnter,
    onDragOver,
    onDragStart,
    onDrop,
}) {
    return items.map(({ label, path }) => {
        const isActive = currentPath === path;
        const isDragged = draggedPath === path;

        return (
            <button
                aria-current={isActive ? "page" : undefined}
                className={[
                    "mi-app-navigation__item",
                    isActive ? "mi-app-navigation__item--active" : "",
                    isDragged ? "mi-app-navigation__item--dragged" : "",
                ].filter(Boolean).join(" ")}
                draggable="true"
                key={path}
                onClick={(event) => navigate(event, path)}
                onDragEnd={onDragEnd}
                onDragEnter={() => onDragEnter(path)}
                onDragOver={onDragOver}
                onDragStart={(event) => onDragStart(event, path)}
                onDrop={(event) => onDrop(event, path)}
                type="button"
            >
                {label}
            </button>
        );
    });
}

export default function AppNavigation({ currentPath, onPathChange }) {
    const [items, setItems] = useState(() => [...NAVIGATION_ITEMS]);
    const [draggedPath, setDraggedPath] = useState(null);
    const draggedPathRef = useRef(null);
    const lastDragTargetRef = useRef(null);
    const suppressClickRef = useRef(false);

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

    const navigate = (event, path) => {
        if (suppressClickRef.current) {
            event.preventDefault();
            event.stopPropagation();
            return;
        }

        if (path === currentPath) {
            return;
        }

        window.history.pushState({}, "", path);
        onPathChange(path);
    };

    const moveDraggedTab = (targetPath) => {
        const sourcePath = draggedPathRef.current;
        if (!sourcePath || sourcePath === targetPath) {
            return;
        }
        setItems((current) => (
            reorderNavigationItems(current, sourcePath, targetPath)
        ));
    };

    const handleDragStart = (event, path) => {
        draggedPathRef.current = path;
        lastDragTargetRef.current = path;
        suppressClickRef.current = true;
        setDraggedPath(path);
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", path);
    };

    const handleDragEnter = (path) => {
        if (lastDragTargetRef.current === path) {
            return;
        }
        lastDragTargetRef.current = path;
        moveDraggedTab(path);
    };

    const handleDragOver = (event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
    };

    const handleDrop = (event) => {
        event.preventDefault();
        draggedPathRef.current = null;
        lastDragTargetRef.current = null;
        setDraggedPath(null);
    };

    const handleDragEnd = () => {
        draggedPathRef.current = null;
        lastDragTargetRef.current = null;
        setDraggedPath(null);
        window.setTimeout(() => {
            suppressClickRef.current = false;
        }, 0);
    };

    return (
        <nav aria-label="Primary" className="mi-app-navigation">
            <NavigationTabs
                currentPath={currentPath}
                draggedPath={draggedPath}
                items={items}
                navigate={navigate}
                onDragEnd={handleDragEnd}
                onDragEnter={handleDragEnter}
                onDragOver={handleDragOver}
                onDragStart={handleDragStart}
                onDrop={handleDrop}
            />
        </nav>
    );
}
