"""SIMULATION routes — twin-only configuration with no real-HW counterpart.

The Sample Settings window talks exclusively to this router: sample registry
and registration, simulation environments, specimen degradation, and drift
injection. Keeping these off the /microscope surface preserves the
"test here, deploy there" boundary: generated automation scripts never
reference anything served here.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from ..services import abtem_service
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
    environment: Optional[str] = None
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


class SetEnvironmentRequest(BaseModel):
    name: str


class SpecimenSettings(BaseModel):
    beam_damage_enabled: Optional[bool] = None
    damage_dose_threshold: Optional[float] = None
    damage_rate: Optional[float] = None
    contamination_enabled: Optional[bool] = None
    contamination_rate: Optional[float] = None


class DriftSettings(BaseModel):
    # Physical interface (preferred): TEM-realistic drift is 0-10 nm/s;
    # the cap leaves headroom for stress tests without allowing absurdity.
    vx_nm_per_s: Optional[float] = Field(None, ge=0.0, le=50.0)
    vy_nm_per_s: Optional[float] = Field(None, ge=0.0, le=50.0)
    line_jitter_nm: Optional[float] = Field(None, ge=0.0, le=5.0)
    # Legacy volume-pixel interface (kept for back-compat)
    vx_px_per_s: Optional[float] = None
    vy_px_per_s: Optional[float] = None
    line_jitter_px: Optional[float] = None
    enabled: Optional[bool] = None
    reset_accum: bool = False


class SetThicknessRequest(BaseModel):
    thickness_nm: Optional[float] = Field(None, gt=0.0, le=1000.0)
    thickness_seed: Optional[int] = Field(None, ge=0, le=MAX_SEED)


class AbtemDiffractionRequest(BaseModel):
    # >0 adds thermal-diffuse background; each config multiplies runtime.
    num_frozen_phonons: int = Field(0, ge=0, le=abtem_service.MAX_FROZEN_PHONONS)
    half_width_um: float = Field(0.02, gt=0.0, le=1.0)
    depth_nm: float = Field(10.0, gt=0.0, le=200.0)
    # Extraction box; the service also enforces its own hard maxima.
    max_lateral_A: float = Field(50.0, gt=0.0, le=abtem_service.MAX_LATERAL_A)
    max_thickness_A: float = Field(80.0, gt=0.0, le=abtem_service.MAX_THICKNESS_A)
    max_angle_mrad: float = Field(60.0, ge=10.0, le=120.0)


# ===== Endpoints =====

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
    resets degradation history (fresh specimen). Optionally applies a
    simulation environment in the same step."""
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
    environment = None
    if request.environment:
        env_result = ts.twin_call(harness.set_environment, request.environment)
        environment = env_result.get("environment")
    return {
        "success": True,
        "registered": result.get("loaded"),
        "shape": result.get("shape"),
        "params": result.get("params"),
        "thickness": result.get("thickness"),
        "environment": environment,
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


@router.get("/environment")
def get_environment():
    return ts.twin_call(ts.get_harness().get_environment)


@router.post("/environment")
def set_environment(request: SetEnvironmentRequest):
    ts.require_idle()
    result = ts.twin_call(ts.get_harness().set_environment, request.name)
    return {"success": True, **result}


@router.get("/specimen")
def get_specimen():
    return ts.twin_call(ts.get_harness().get_specimen)


@router.post("/specimen")
def set_specimen(settings: SpecimenSettings):
    ts.require_idle()
    kwargs = {k: v for k, v in settings.model_dump().items() if v is not None}
    return {"success": True, **ts.twin_call(lambda: ts.get_harness().set_specimen(**kwargs))}


@router.post("/specimen/reset")
def reset_specimen():
    ts.require_idle()
    return {"success": True, **ts.twin_call(ts.get_harness().reset_specimen)}


@router.get("/diffraction/abtem/availability")
def abtem_availability():
    """Whether the optional abtem/ase dependencies are installed. The UI greys
    the Kinematical⇄abTEM toggle when unavailable."""
    return abtem_service.availability()


@router.post("/diffraction/abtem")
def compute_abtem_diffraction(request: AbtemDiffractionRequest):
    """Compute a dynamical (multislice) SAED pattern for the registered sample
    at the current stage tilt and beam voltage. Long-running (seconds to tens
    of seconds); one computation at a time (409 while busy); 501 when abtem is
    not installed. Results are cached on the full state fingerprint."""
    return abtem_service.compute_saed(
        num_frozen_phonons=request.num_frozen_phonons,
        half_width_um=request.half_width_um,
        depth_nm=request.depth_nm,
        max_lateral_A=request.max_lateral_A,
        max_thickness_A=request.max_thickness_A,
        max_angle_mrad=request.max_angle_mrad,
    )


@router.get("/drift")
def get_drift():
    return ts.twin_call(ts.get_harness().get_drift)


@router.post("/drift")
def set_drift(settings: DriftSettings):
    ts.require_idle()
    kwargs = settings.model_dump()
    return {"success": True, "drift": ts.twin_call(lambda: ts.get_harness().set_drift(**kwargs))}
