export const NAVIGATION_ORDER_STORAGE_KEY = "tradingai.navigation.tabOrder.v1";

export const reorderNavigationItems = (items, draggedPath, targetPath) => {
    const fromIndex = items.findIndex(({ path }) => path === draggedPath);
    const toIndex = items.findIndex(({ path }) => path === targetPath);

    if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) {
        return items;
    }

    const reordered = [...items];
    const [draggedItem] = reordered.splice(fromIndex, 1);
    reordered.splice(toIndex, 0, draggedItem);
    return reordered;
};

export const restoreNavigationItems = (canonicalItems, serializedOrder) => {
    let savedPaths;
    try {
        savedPaths = JSON.parse(serializedOrder);
    } catch {
        return [...canonicalItems];
    }

    if (!Array.isArray(savedPaths)) {
        return [...canonicalItems];
    }

    const canonicalByPath = new Map(
        canonicalItems.map((item) => [item.path, item]),
    );
    const restored = [];
    const includedPaths = new Set();

    savedPaths.forEach((path) => {
        if (
            typeof path === "string"
            && canonicalByPath.has(path)
            && !includedPaths.has(path)
        ) {
            restored.push(canonicalByPath.get(path));
            includedPaths.add(path);
        }
    });

    canonicalItems.forEach((item) => {
        if (!includedPaths.has(item.path)) {
            restored.push(item);
        }
    });

    return restored;
};

export const loadNavigationItems = (canonicalItems, storage) => {
    try {
        const serializedOrder = storage?.getItem(NAVIGATION_ORDER_STORAGE_KEY);
        if (serializedOrder === null || serializedOrder === undefined) {
            return [...canonicalItems];
        }
        return restoreNavigationItems(canonicalItems, serializedOrder);
    } catch {
        return [...canonicalItems];
    }
};

export const persistNavigationItems = (items, storage) => {
    try {
        storage?.setItem(
            NAVIGATION_ORDER_STORAGE_KEY,
            JSON.stringify(items.map(({ path }) => path)),
        );
        return Boolean(storage);
    } catch {
        return false;
    }
};

export const reorderAndPersistNavigationItems = (
    items,
    draggedPath,
    targetPath,
    storage,
) => {
    const reordered = reorderNavigationItems(items, draggedPath, targetPath);
    if (reordered !== items) {
        persistNavigationItems(reordered, storage);
    }
    return reordered;
};
