/**
 * Bounds for the free-form acquisition-condition fields.
 *
 * The single source of truth is backend/app/digital_twin/limits.py, served
 * as GET /api/simulation/limits (fetchLimits below). The constants here are
 * OFFLINE FALLBACKS only — used until the first successful fetch, and kept
 * loosely in sync rather than authoritative.
 *
 * These are protective bounds, not realism caps: with the environment
 * presets gone every value arrives from a user-typed field and the twin
 * server itself validates almost nothing, so the widget range plus the
 * pre-RPC clamp is the only guard against crash-inducing values.
 */

import { apiGet } from './client';

export interface Bound {
  min: number;
  max: number;
}

export interface ConditionLimits {
  resolutions: { allowed: number[]; default: number };
  drift: {
    vx_nm_per_s: Bound;
    vy_nm_per_s: Bound;
    line_jitter_nm: Bound;
    max_dt_s: Bound;
  };
  contamination: { rate: Bound };
  noise: {
    dwell_us: Bound;
    dqe: Bound;
    readout_e: Bound;
    noise_sigma: Bound;
  };
  autofocus: { min_contrast: Bound };
}

export const FALLBACK_LIMITS: ConditionLimits = {
  resolutions: { allowed: [1024, 2048, 4096], default: 1024 },
  drift: {
    vx_nm_per_s: { min: 0, max: 50 },
    vy_nm_per_s: { min: 0, max: 50 },
    line_jitter_nm: { min: 0, max: 5 },
    max_dt_s: { min: 0, max: 3600 },
  },
  contamination: { rate: { min: 0, max: 1000 } },
  noise: {
    dwell_us: { min: 0.1, max: 1000 },
    dqe: { min: 0.01, max: 1 },
    readout_e: { min: 0, max: 100 },
    noise_sigma: { min: 0, max: 1000 },
  },
  autofocus: { min_contrast: { min: 0, max: 1 } },
};

/** Authoritative bounds from the backend (single source of truth). */
export function fetchLimits(): Promise<ConditionLimits> {
  return apiGet('/simulation/limits');
}

/** Clamp a value into a bound before it reaches an RPC — a pasted or
 *  programmatic value must not be able to bypass a slider's range. */
export function clamp(value: number, bound: Bound): number {
  if (!Number.isFinite(value)) return bound.min;
  return Math.min(bound.max, Math.max(bound.min, value));
}

export const FALLBACK_ALLOWED_RESOLUTIONS = FALLBACK_LIMITS.resolutions.allowed;
export const DEFAULT_RESOLUTION = FALLBACK_LIMITS.resolutions.default;

/** Resolution reserved for offline capture (Save TIFF) — Live mode is
 *  disabled at this window because frames take seconds to minutes. */
export const OFFLINE_CAPTURE_RESOLUTION = 4096;
