export function formatMoneyManagementAxisTimestamp(timestamp) {
    if (typeof timestamp !== "string") return timestamp;

    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(timestamp);
    return match ? `${match[2]}/${match[3]}` : timestamp;
}
