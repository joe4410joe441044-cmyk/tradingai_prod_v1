const UTC_ISO_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|\+00:00)$/;

export function isValidUtcIsoTimestamp(value) {
  if (typeof value !== "string") {
    return false;
  }
  const match = UTC_ISO_PATTERN.exec(value);
  if (!match) {
    return false;
  }
  const [, year, month, day, hour, minute, second] = match;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) {
    return false;
  }
  const date = new Date(timestamp);
  return (
    date.getUTCFullYear() === Number(year) &&
    date.getUTCMonth() + 1 === Number(month) &&
    date.getUTCDate() === Number(day) &&
    date.getUTCHours() === Number(hour) &&
    date.getUTCMinutes() === Number(minute) &&
    date.getUTCSeconds() === Number(second)
  );
}

export function timestampAgeMs(value, now = Date.now()) {
  if (!isValidUtcIsoTimestamp(value) || !Number.isFinite(now)) {
    return null;
  }
  return now - Date.parse(value);
}
