const DECIMAL_PATTERN = /^-?\d+(?:\.\d+)?$/;

function parseParts(value) {
  if (typeof value !== "string" || !DECIMAL_PATTERN.test(value)) {
    return null;
  }
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [integerPart, fractionPart = ""] = unsigned.split(".");
  const integer = integerPart.replace(/^0+(?=\d)/, "");
  const fraction = fractionPart.replace(/0+$/, "");
  const zero = /^0+$/.test(integer) && fraction.length === 0;
  return {
    negative: negative && !zero,
    integer,
    fraction,
  };
}

export function isStrictDecimalString(value) {
  return parseParts(value) !== null;
}

export function normalizeDecimalString(value) {
  const parts = parseParts(value);
  if (!parts) {
    return null;
  }
  return `${parts.negative ? "-" : ""}${parts.integer}${
    parts.fraction ? `.${parts.fraction}` : ""
  }`;
}

function compareUnsigned(left, right) {
  if (left.integer.length !== right.integer.length) {
    return left.integer.length < right.integer.length ? -1 : 1;
  }
  if (left.integer !== right.integer) {
    return left.integer < right.integer ? -1 : 1;
  }
  const length = Math.max(left.fraction.length, right.fraction.length);
  const leftFraction = left.fraction.padEnd(length, "0");
  const rightFraction = right.fraction.padEnd(length, "0");
  if (leftFraction === rightFraction) {
    return 0;
  }
  return leftFraction < rightFraction ? -1 : 1;
}

export function compareDecimalStrings(leftValue, rightValue) {
  const left = parseParts(leftValue);
  const right = parseParts(rightValue);
  if (!left || !right) {
    throw new TypeError("strict decimal strings required");
  }
  if (left.negative !== right.negative) {
    return left.negative ? -1 : 1;
  }
  const comparison = compareUnsigned(left, right);
  return left.negative ? -comparison : comparison;
}

export function isBackendPercentage(value) {
  return (
    isStrictDecimalString(value) &&
    compareDecimalStrings(value, "0") > 0 &&
    compareDecimalStrings(value, "100") <= 0
  );
}
