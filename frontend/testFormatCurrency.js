import { strict as assert } from 'node:assert';
import { describe, it } from 'node:test';
import { formatCurrency } from '../src/components/operation/OperationPreparation.jsx';

describe('formatCurrency', () => {
  it('should format standard currency with two decimal places', () => {
    assert.equal(formatCurrency("10000.00"), "$10,000.00");
  });

  it('should preserve single decimal place', () => {
    assert.equal(formatCurrency("0.10"), "$0.10");
  });

  it('should handle negative values correctly', () => {
    assert.equal(formatCurrency("-25.50"), "-$25.50");
  });

  it('should preserve very large numbers with high precision', () => {
    assert.equal(formatCurrency("9007199254740993.01"), "$9,007,199,254,740,993.01");
  });

  it('should handle extremely large numbers with many digits', () => {
    assert.equal(formatCurrency("123456789012345678901234567890.12"), "$123,456,789,012,345,678,901,234,567,890.12");
  });

  it('should preserve very small decimal values', () => {
    assert.equal(formatCurrency("0.00000001"), "$0.00000001");
  });

  it('should preserve trailing zeros in decimal places', () => {
    assert.equal(formatCurrency("1.2300"), "$1.2300");
  });

  it('should handle null values', () => {
    assert.equal(formatCurrency(null), "UNAVAILABLE");
  });

  it('should handle undefined values', () => {
    assert.equal(formatCurrency(undefined), "UNAVAILABLE");
  });

  it('should handle empty string', () => {
    assert.equal(formatCurrency(""), "UNAVAILABLE");
  });

  it('should handle non-numeric strings', () => {
    assert.equal(formatCurrency("abc"), "UNAVAILABLE");
  });

  it('should handle NaN', () => {
    assert.equal(formatCurrency(NaN), "UNAVAILABLE");
  });

  it('should handle Infinity', () => {
    assert.equal(formatCurrency(Infinity), "UNAVAILABLE");
  });

  it('should handle positive infinity', () => {
    assert.equal(formatCurrency(Number.POSITIVE_INFINITY), "UNAVAILABLE");
  });

  it('should handle negative infinity', () => {
    assert.equal(formatCurrency(Number.NEGATIVE_INFINITY), "UNAVAILABLE");
  });
});