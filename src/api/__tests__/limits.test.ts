/**
 * Tests for the condition-limits module — clamp() is the only guard between
 * a pasted value and the twin server, so its edge cases matter.
 */

import { describe, it, expect } from 'vitest';
import { clamp, FALLBACK_LIMITS } from '../limits';

describe('clamp', () => {
  const bound = { min: 0.1, max: 300 };

  it('passes a value inside the bound through unchanged', () => {
    expect(clamp(42, bound)).toBe(42);
    expect(clamp(0.1, bound)).toBe(0.1);
    expect(clamp(300, bound)).toBe(300);
  });

  it('caps a value above max at max', () => {
    expect(clamp(301, bound)).toBe(300);
    expect(clamp(1e9, bound)).toBe(300);
  });

  it('raises a value below min to min', () => {
    expect(clamp(0, bound)).toBe(0.1);
    expect(clamp(-50, bound)).toBe(0.1);
  });

  it('maps non-finite values (NaN, ±Infinity) to min', () => {
    expect(clamp(NaN, bound)).toBe(0.1);
    expect(clamp(Infinity, bound)).toBe(0.1);
    expect(clamp(-Infinity, bound)).toBe(0.1);
  });
});

describe('FALLBACK_LIMITS', () => {
  it('keeps the offline fallback bounds in sync with the backend', () => {
    expect(FALLBACK_LIMITS.drift.vx_nm_per_s.max).toBe(50);
    expect(FALLBACK_LIMITS.contamination.rate.max).toBe(1000);
    expect(FALLBACK_LIMITS.noise.dwell_us.min).toBe(0.1);
  });
});
