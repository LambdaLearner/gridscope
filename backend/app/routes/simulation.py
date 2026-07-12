"""SIMULATION routes — twin-only configuration with no real-HW counterpart.

The Sample Settings window talks exclusively to this router: sample registry
and registration, simulation environments, specimen degradation, and drift
injection. Keeping these off the /microscope surface preserves the
"test here, deploy there" boundary: generated automation scripts never
reference anything served here.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..services import twin_session as ts

router = APIRouter(prefix="/simulation", tags=["simulation"])


# ===== Request models =====

class RegisterSampleRequest(BaseModel):
    name: str
    params: Dict[str, Any] = Field(default_factory=dict)
    environment: Optional[str] = None
    # Volume resolution; defaults match the twin's canonical sizes.
    D: Optional[int] = None
    H: Optional[int] = None
    W: Optional[int] = None


class SetEnvironmentRequest(BaseModel):
    name: str


class SpecimenSettings(BaseModel):
    beam_damage_enabled: Optional[bool] = None
    damage_dose_threshold: Optional[float] = None
    damage_rate: Optional[float] = None
    contamination_enabled: Optional[bool] = None
    contamination_rate: Optional[float] = None


class DriftSettings(BaseModel):
    vx_px_per_s: Optional[float] = None
    vy_px_per_s: Optional[float] = None
    line_jitter_px: Optional[float] = None
    enabled: Optional[bool] = None
    reset_accum: bool = False


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
        "environment": environment,
    }


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


@router.get("/drift")
def get_drift():
    return ts.twin_call(ts.get_harness().get_drift)


@router.post("/drift")
def set_drift(settings: DriftSettings):
    ts.require_idle()
    kwargs = settings.model_dump()
    return {"success": True, "drift": ts.twin_call(lambda: ts.get_harness().set_drift(**kwargs))}
