"""SIMULATION routes — twin-only configuration with no real-HW counterpart.

The Sample Settings window talks exclusively to this router: sample registry
and registration, acquisition conditions (drift, contamination, detector
noise, autofocus limits), and specimen reset. Keeping these off the
/microscope surface preserves the "test here, deploy there" boundary:
generated automation scripts never reference anything served here.

There are no environment presets. A session states its conditions as numbers
through the explicit setters below; GET /limits publishes the bounds the
widgets enforce (and this layer re-enforces with 422s, since the twin server
itself validates almost nothing).
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from ..digital_twin import limits
from ..digital_twin.limits import (
    AF_MIN_CONTRAST_MAX,
    AF_MIN_CONTRAST_MIN,
    CONTAMINATION_MAX_RATE_PCT,
    DRIFT_MAX_DT_S,
    DRIFT_MAX_JITTER_NM,
    DRIFT_MAX_NM_PER_S,
    NOISE_DQE_MAX,
    NOISE_DQE_MIN,
    NOISE_DWELL_US_MAX,
    NOISE_DWELL_US_MIN,
    NOISE_READOUT_E_MAX,
    NOISE_SIGMA_MAX,
)
from ..services import twin_session as ts

router = APIRouter(prefix="/simulation", tags=["simulation"])

# Volume caps: a D x H x W float32 volume is D*H*W*4 bytes (128 x 1024 x 1024
# is already ~0.5 GB). These endpoints are also hit by generated scripts, so
# the caps live here at the API boundary, not just in UI widget ranges.
MAX_VOLUME_D = 128
MAX_VOLUME_HW = 1024
# These samples stamp a 12-slice band around D/2 and need the depth for it.
MIN_DEPTH_12_SAMPLES = {"polycrystal_grains", "dislocation_crystal"}

MAX_SEED = 2**31 - 1


# ===== Request models =====

class RegisterSampleRequest(BaseModel):
    name: str
    params: Dict[str, Any] = Field(default_factory=dict)
    # Volume resolution; defaults match the twin's canonical sizes.
    D: Optional[int] = Field(None, ge=1, le=MAX_VOLUME_D)
    H: Optional[int] = Field(None, ge=32, le=MAX_VOLUME_HW)
    W: Optional[int] = Field(None, ge=32, le=MAX_VOLUME_HW)
    # Working-thickness selection (see /thickness for post-load changes).
    thickness_nm: Optional[float] = Field(None, gt=0.0, le=1000.0)
    thickness_seed: Optional[int] = Field(None, ge=0, le=MAX_SEED)

    @model_validator(mode="after")
    def _volume_consistent(self):
        if self.H is not None and self.W is not None and self.H != self.W:
            raise ValueError("volume must be square in-plane (H == W)")
        if self.name in MIN_DEPTH_12_SAMPLES and self.D is not None and self.D < 12:
            raise ValueError(
                f"sample '{self.name}' needs volume depth D >= 12 "
                f"(it stamps a 12-slice structural band)")
        return self


class ContaminationSettings(BaseModel):
    # `rate` is a percentage of the calibrated nominal rate: 100 = nominal,
    # 200 = twice as fast, 0 = off.
    enabled: Optional[bool] = None
    rate: Optional[float] = Field(None, ge=0.0, le=CONTAMINATION_MAX_RATE_PCT)


class NoiseSettings(BaseModel):
    dwell_us: Optional[float] = Field(
        None, ge=NOISE_DWELL_US_MIN, le=NOISE_DWELL_US_MAX)
    dqe: Optional[float] = Field(None, ge=NOISE_DQE_MIN, le=NOISE_DQE_MAX)
    readout_e: Optional[float] = Field(None, ge=0.0, le=NOISE_READOUT_E_MAX)
    use_dose_model: Optional[bool] = None
    noise_sigma: Optional[float] = Field(None, ge=0.0, le=NOISE_SIGMA_MAX)


class AutofocusLimitsSettings(BaseModel):
    min_contrast: Optional[float] = Field(
        None, ge=AF_MIN_CONTRAST_MIN, le=AF_MIN_CONTRAST_MAX)


class DriftSettings(BaseModel):
    # Physical interface (preferred): TEM-realistic drift is 0.1-5 nm/s;
    # the cap leaves headroom for stress tests without allowing absurdity.
    vx_nm_per_s: Optional[float] = Field(None, ge=0.0, le=DRIFT_MAX_NM_PER_S)
    vy_nm_per_s: Optional[float] = Field(None, ge=0.0, le=DRIFT_MAX_NM_PER_S)
    line_jitter_nm: Optional[float] = Field(None, ge=0.0, le=DRIFT_MAX_JITTER_NM)
    # Legacy volume-pixel interface (kept for back-compat). Bounded too:
    # 1 volume px is ~26 nm, so 50 px/s already far exceeds the physical cap.
    vx_px_per_s: Optional[float] = Field(None, ge=0.0, le=50.0)
    vy_px_per_s: Optional[float] = Field(None, ge=0.0, le=50.0)
    line_jitter_px: Optional[float] = Field(None, ge=0.0, le=5.0)
    # Per-frame elapsed-time cap (idle-jump guard); raise for a deliberate
    # long-gap drift study.
    max_dt_s: Optional[float] = Field(None, ge=0.0, le=DRIFT_MAX_DT_S)
    enabled: Optional[bool] = None
    reset_accum: bool = False


class SetThicknessRequest(BaseModel):
    thickness_nm: Optional[float] = Field(None, gt=0.0, le=1000.0)
    thickness_seed: Optional[int] = Field(None, ge=0, le=MAX_SEED)


# ===== Endpoints =====

@router.get("/limits")
def get_limits():
    """Bounds for every free-form acquisition-condition field. The frontend
    fetches this at connect time for widget ranges and pre-RPC clamping;
    src/api/limits.ts holds offline fallbacks only."""
    return limits.as_dict()


@router.get("/samples")
def list_samples():
    """The sample registry: names, descriptions, and parameter schemas.
    Registry metadata is cheap — no volume is instantiated here."""
    samples = ts.twin_call(ts.get_harness().list_samples)
    return {"samples": samples, "count": len(samples)}


@router.get("/sample")
def get_current_sample():
    current = ts.twin_call(ts.get_harness().get_current_sample)
    return {"sample": current, "registered": current.get("name") is not None}


@router.post("/sample/register")
def register_sample(request: RegisterSampleRequest):
    """Register a sample: loads it into the twin as the active specimen and
    resets degradation history (fresh specimen). Acquisition conditions are
    independent of registration — set them via /drift, /contamination,
    /noise, and /autofocus-limits."""
    ts.require_idle()
    harness = ts.get_harness()
    result = ts.twin_call(
        harness.load_sample,
        request.name,
        params=request.params,
        D=request.D, H=request.H, W=request.W,
        thickness_nm=request.thickness_nm,
        thickness_seed=request.thickness_seed,
    )
    ts.twin_call(harness.reset_specimen)
    return {
        "success": True,
        "registered": result.get("loaded"),
        "shape": result.get("shape"),
        "params": result.get("params"),
        "thickness": result.get("thickness"),
    }


@router.get("/thickness")
def get_thickness():
    """Current working-thickness selection {total_nm, working_nm, z_start_nm, seed}."""
    return ts.twin_call(ts.get_harness().get_thickness)


@router.post("/thickness")
def set_thickness(request: SetThicknessRequest):
    """Re-pick the working thickness / thickness seed without regenerating the
    sample (simulates navigating to a differently-thick region). 409 if no
    sample is registered."""
    ts.require_idle()
    result = ts.twin_call(
        lambda: ts.get_harness().set_thickness(
            thickness_nm=request.thickness_nm,
            thickness_seed=request.thickness_seed,
        )
    )
    return {"success": True, **result}


@router.get("/specimen")
def get_specimen():
    return ts.twin_call(ts.get_harness().get_specimen)


@router.post("/contamination")
def set_contamination(settings: ContaminationSettings):
    ts.require_idle()
    return {"success": True, **ts.twin_call(
        lambda: ts.get_harness().set_contamination(
            enabled=settings.enabled, rate=settings.rate))}


@router.post("/noise")
def set_noise(settings: NoiseSettings):
    """Detector / dose parameters. NOTE: writes only the keys you pass —
    an omitted key keeps its current server-side value."""
    ts.require_idle()
    kwargs = {k: v for k, v in settings.model_dump().items() if v is not None}
    return {"success": True, **ts.twin_call(
        lambda: ts.get_harness().set_noise(**kwargs))}


@router.post("/autofocus-limits")
def set_autofocus_limits(settings: AutofocusLimitsSettings):
    ts.require_idle()
    return {"success": True, **ts.twin_call(
        lambda: ts.get_control().set_autofocus_limits(
            min_contrast=settings.min_contrast))}


@router.post("/specimen/reset")
def reset_specimen():
    ts.require_idle()
    return {"success": True, **ts.twin_call(ts.get_harness().reset_specimen)}


@router.get("/drift")
def get_drift():
    return ts.twin_call(ts.get_harness().get_drift)


@router.post("/drift")
def set_drift(settings: DriftSettings):
    ts.require_idle()
    kwargs = settings.model_dump()
    return {"success": True, "drift": ts.twin_call(lambda: ts.get_harness().set_drift(**kwargs))}
