"""Shared numeric limits for the digital twin and its HTTP API.

Single Python source of truth for values that must agree between the twin
server (which enforces them at the RPC layer) and the FastAPI routes (which
enforce them at the HTTP boundary, giving 422s before any RPC round-trip).
The frontend fetches these at connect time via GET /simulation/limits;
src/api/limits.ts carries offline fallbacks only.

These are PROTECTIVE bounds, not realism caps: the acquisition-condition
fields are free-form by design (the presets are gone), so the job here is to
block crash-inducing or absurd values (negatives, zeros where they divide,
1e6 from a stray paste), not to enforce what a well-adjusted instrument
would do. Realistic stage drift is 0.1-5 nm/s; the cap is 10x that.

This module is deliberately dependency-free (no twisted, no numpy) so the
FastAPI process can import it without pulling in the twin's runtime.
"""

# Discrete acquisition windows (pixels per side). 512 was removed in v3;
# the default detector window is the smallest allowed value.
ALLOWED_RESOLUTIONS = (1024, 2048, 4096)
DEFAULT_RESOLUTION = ALLOWED_RESOLUTIONS[0]

# Mechanical stage drift (physical nm/s interface).
DRIFT_MAX_NM_PER_S = 50.0
DRIFT_MAX_JITTER_NM = 5.0
# Cap on per-frame elapsed drift time (idle-jump guard); settable so a long
# deliberate wait can accumulate, bounded to one hour.
DRIFT_MAX_DT_S = 3600.0

# Contamination rate is a PERCENTAGE of the calibrated nominal rate
# (100 = nominal, 0 = off). 1000% = 10x nominal is stress-test headroom.
CONTAMINATION_MAX_RATE_PCT = 1000.0

# Detector / dose noise. dwell_us = 0 would zero the dose (division-free but
# meaningless); dqe = 0 likewise. use_dose_model is boolean-ish (0/1).
NOISE_DWELL_US_MIN = 0.1
NOISE_DWELL_US_MAX = 1000.0
NOISE_DQE_MIN = 0.01
NOISE_DQE_MAX = 1.0
NOISE_READOUT_E_MAX = 100.0
NOISE_SIGMA_MAX = 1000.0

# Autofocus acceptance: peak/floor contrast ratio for convergence.
AF_MIN_CONTRAST_MIN = 0.0
AF_MIN_CONTRAST_MAX = 1.0


def as_dict():
    """Structured bounds for GET /simulation/limits — the single payload the
    frontend uses for widget ranges and pre-RPC clamping."""
    return {
        "resolutions": {"allowed": list(ALLOWED_RESOLUTIONS),
                        "default": DEFAULT_RESOLUTION},
        "drift": {
            "vx_nm_per_s": {"min": 0.0, "max": DRIFT_MAX_NM_PER_S},
            "vy_nm_per_s": {"min": 0.0, "max": DRIFT_MAX_NM_PER_S},
            "line_jitter_nm": {"min": 0.0, "max": DRIFT_MAX_JITTER_NM},
            "max_dt_s": {"min": 0.0, "max": DRIFT_MAX_DT_S},
        },
        "contamination": {
            "rate": {"min": 0.0, "max": CONTAMINATION_MAX_RATE_PCT},
        },
        "noise": {
            "dwell_us": {"min": NOISE_DWELL_US_MIN, "max": NOISE_DWELL_US_MAX},
            "dqe": {"min": NOISE_DQE_MIN, "max": NOISE_DQE_MAX},
            "readout_e": {"min": 0.0, "max": NOISE_READOUT_E_MAX},
            "noise_sigma": {"min": 0.0, "max": NOISE_SIGMA_MAX},
        },
        "autofocus": {
            "min_contrast": {"min": AF_MIN_CONTRAST_MIN,
                             "max": AF_MIN_CONTRAST_MAX},
        },
    }
