/**
 * Frontend mirror of backend/app/digital_twin/limits.py — the single Python
 * source of truth for twin/API numeric limits. Update both files together.
 *
 * The resolution list here is only a FALLBACK for before the first state
 * poll; the authoritative set is `state.resolution.allowed` from the server.
 */

export const FALLBACK_ALLOWED_RESOLUTIONS = [1024, 2048, 4096];
export const DEFAULT_RESOLUTION = 1024;

/** Resolution reserved for offline capture (Save TIFF) — Live mode is
 *  disabled at this window because frames take seconds to minutes. */
export const OFFLINE_CAPTURE_RESOLUTION = 4096;

export const DRIFT_MAX_NM_PER_S = 50;
export const DRIFT_MAX_JITTER_NM = 5;
export const CONTAMINATION_MAX_RATE = 20;
export const DAMAGE_MAX_RATE = 10;
