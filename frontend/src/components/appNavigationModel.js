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
