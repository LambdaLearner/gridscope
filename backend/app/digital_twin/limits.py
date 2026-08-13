"""Shared numeric limits for the digital twin and its HTTP API.

Single Python source of truth for values that must agree between the twin
server (which enforces them at the RPC layer) and the FastAPI routes (which
enforce them at the HTTP boundary, giving 422s before any RPC round-trip).
The frontend mirrors these in src/api/limits.ts — update both together.

This module is deliberately dependency-free (no twisted, no numpy) so the
FastAPI process can import it without pulling in the twin's runtime.
"""

# Discrete acquisition windows (pixels per side). 512 was removed in v3;
# the default detector window is the smallest allowed value.
ALLOWED_RESOLUTIONS = (1024, 2048, 4096)
DEFAULT_RESOLUTION = ALLOWED_RESOLUTIONS[0]

# Mechanical stage drift (physical nm/s interface). TEM-realistic drift is
# 0-10 nm/s; the cap leaves headroom so the effect is clearly visible at
# moderate fields of view without allowing absurd values from scripts.
DRIFT_MAX_NM_PER_S = 50.0
DRIFT_MAX_JITTER_NM = 5.0

# Specimen degradation. Contamination rate 0-5 is the "typical" band the
# twin's model was calibrated on; the cap gives demo headroom. Damage rate
# ~1 is nominal.
CONTAMINATION_MAX_RATE = 20.0
DAMAGE_MAX_RATE = 10.0
DAMAGE_DOSE_THRESHOLD_MIN = 1.0        # e-/A^2
DAMAGE_DOSE_THRESHOLD_MAX = 1.0e8     # e-/A^2
