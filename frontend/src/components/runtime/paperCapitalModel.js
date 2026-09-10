const MINIMUM_PAPER_CAPITAL = 0.01;
const MAXIMUM_PAPER_CAPITAL = 1_000_000_000;

export const PAPER_CAPITAL_ERRORS = Object.freeze({
    required: "Simulation capital is required.",
    invalid: "Enter a valid amount with up to 2 decimal places.",
    minimum: "Simulation capital must be at least 0.01 USDT.",
    maximum: "Simulation capital must not exceed 1,000,000,000.00 USDT.",
});

export const validatePaperCapitalInput = (value) => {
    const input = String(value ?? "").trim();

    if (!input) {
        return { valid: false, canonical: null, error: PAPER_CAPITAL_ERRORS.required };
    }

    if (!/^\d+(?:\.\d{1,2})?$/.test(input)) {
        return { valid: false, canonical: null, error: PAPER_CAPITAL_ERRORS.invalid };
    }

    const numericValue = Number(input);

    if (!Number.isFinite(numericValue) || numericValue < MINIMUM_PAPER_CAPITAL) {
        return { valid: false, canonical: null, error: PAPER_CAPITAL_ERRORS.minimum };
    }

    if (numericValue > MAXIMUM_PAPER_CAPITAL) {
        return { valid: false, canonical: null, error: PAPER_CAPITAL_ERRORS.maximum };
    }

    return {
        valid: true,
        canonical: numericValue.toFixed(2),
        error: null,
    };
};

export const normalizePaperCapitalPreset = (value) => {
    const numericValue = Number(value);

    if (!Number.isFinite(numericValue)) {
        return null;
    }

    return numericValue.toFixed(2);
};
