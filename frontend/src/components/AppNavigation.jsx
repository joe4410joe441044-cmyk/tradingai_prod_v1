import { useEffect, useRef, useState } from "react";

import { navigateTo } from "../utils/appNavigation";
import { PROP_ISOLATED_DEMO_ENABLED } from "../features/prop-accounts/propIsolatedDemoFeature.js";

import {
    loadNavigationItems,
    reorderAndPersistNavigationItems,
} from "./appNavigationModel";
import { buildNavigationItems, resolveNavigationPath } from "./appNavigationRoutes.js";

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

const resolveNavigationStorage = () => {
    try {
        return window.localStorage;
    } catch {
        return null;
    }
};

export default function AppNavigation({
    currentPath,
    onPathChange,
    propDemoEnabled = PROP_ISOLATED_DEMO_ENABLED,
}) {
    const [items, setItems] = useState(() => (
        loadNavigationItems(buildNavigationItems(propDemoEnabled), resolveNavigationStorage())
    ));
    const [draggedPath, setDraggedPath] = useState(null);
    const draggedPathRef = useRef(null);
    const lastDragTargetRef = useRef(null);
    const suppressClickRef = useRef(false);

    useEffect(() => {
        const syncPath = () => {
            const resolvedPath = resolveNavigationPath(window.location.pathname, propDemoEnabled);

            if (resolvedPath !== window.location.pathname) {
                window.history.replaceState({}, "", resolvedPath);
            }

            onPathChange(resolvedPath);
        };

        syncPath();
        window.addEventListener("popstate", syncPath);

        return () => window.removeEventListener("popstate", syncPath);
    }, [onPathChange, propDemoEnabled]);

    const navigate = (event, path) => {
        if (suppressClickRef.current) {
            event.preventDefault();
            event.stopPropagation();
            return;
        }

        if (path === currentPath) {
            return;
        }

        navigateTo(path);
    };

    const moveDraggedTab = (targetPath) => {
        const sourcePath = draggedPathRef.current;
        if (!sourcePath || sourcePath === targetPath) {
            return;
        }
        setItems((current) => (
            reorderAndPersistNavigationItems(
                current,
                sourcePath,
                targetPath,
                resolveNavigationStorage(),
            )
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
