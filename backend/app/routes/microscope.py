"""Microscope CONTROL routes — the portable instrument surface.

Every endpoint here corresponds to an operation a real microscope exposes
(stage with soft limits, beam, mode, magnification, detectors, acquisition,
autofocus). Twin-only configuration (samples, environments, degradation)
lives in routes/simulation.py.

Handlers are plain `def` on purpose: the twin renders frames in 1-5 s and
FastAPI runs sync handlers in its threadpool, keeping the event loop free.
"""

import threading
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from ..services import twin_session as ts

router = APIRouter(prefix="/microscope", tags=["microscope"])

_server_thread: Optional[threading.Thread] = None


# ===== Request models =====

class StagePosition(BaseModel):
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    a: Optional[float] = None
    b: Optional[float] = None


class SetStageRequest(BaseModel):
    position: StagePosition
    relative: bool = True


class DetectorSettings(BaseModel):
    size: Optional[int] = None
    exposure: Optional[float] = None
    binning: Optional[int] = None
    field_of_view_um: Optional[float] = None
    magnification: Optional[float] = None
    dwell_us: Optional[float] = None
    noise_sigma: Optional[float] = None


class BeamSettings(BaseModel):
    x: Optional[float] = None
    y: Optional[float] = None
    current_pA: Optional[float] = None
    voltage_kV: Optional[float] = None


class SetBeamRequest(BaseModel):
    settings: BeamSettings
    relative: bool = False


class SetModeRequest(BaseModel):
    mode: str


class SetMagnificationRequest(BaseModel):
    magnification: float
    device: str = "haadf"


class AcquireImageRequest(BaseModel):
    device: str = "haadf"


class AutofocusRequest(BaseModel):
    device: str = "haadf"
    z_range_um: float = 2.0
    z_steps: int = 9


class SetResolutionRequest(BaseModel):
    # The twin (like a real scan generator) offers a fixed set of windows;
    # validating here gives a 422 with the legal values before any RPC.
    resolution_px: Literal[512, 1024, 2048]
    device: str = "haadf"


class AcquireSpectrumRequest(BaseModel):
    ev_min: float = Field(0.0, ge=0.0, le=5000.0)
    ev_max: float = Field(1000.0, gt=0.0, le=5000.0)
    # n_channels capped: spectra are returned as JSON arrays and the twin
    # allocates per channel — an absurd value is a memory/payload footgun.
    n_channels: int = Field(1024, ge=16, le=8192)
    cx_um: Optional[float] = None
    cy_um: Optional[float] = None

    @model_validator(mode="after")
    def _range_ordered(self):
        if self.ev_max <= self.ev_min:
            raise ValueError("ev_max must be greater than ev_min")
        return self


# ===== Helpers =====

def _stage_dict(pos) -> Dict[str, float]:
    x, y, z, a, b = (list(pos) + [0.0] * 5)[:5]
    return {
        "x": x, "y": y, "z": z, "a": a, "b": b,
        "x_um": x * 1e6, "y_um": y * 1e6, "z_um": z * 1e6,
    }


# ===== Endpoints =====

@router.get("/status")
def get_status():
    """Connectivity check. Never raises — the UI polls this."""
    control = ts.get_control()
    try:
        ready = control.is_ready()
        return {
            "connected": True,
            "ready": bool(ready.get("ready")),
            "sample": ready.get("sample"),
            "host": control.host,
            "port": control.port,
        }
    except Exception as e:  # noqa: BLE001 — status endpoint reports, not raises
        return {"connected": False, "host": control.host, "port": control.port,
                "error": str(e)}


@router.get("/session")
def get_session(log_last_n: int = 30):
    """Single snapshot the UI polls: state + sample + run status + log."""
    control = ts.get_control()
    harness = ts.get_harness()
    try:
        state = control.get_microscope_state()
        log = harness.get_command_log(last_n=log_last_n)
        connected = True
    except Exception:  # noqa: BLE001 — poll endpoint degrades, not raises
        return {"connected": False, "run": ts.run_status()}
    return {
        "connected": connected,
        "state": state,
        "sample": state.get("sample"),
        "run": ts.run_status(),
        "log": log,
    }


@router.get("/state")
def get_microscope_state():
    return ts.twin_call(ts.get_control().get_microscope_state)


@router.get("/limits")
def get_stage_limits():
    """Stage soft limits (symmetric +/- per axis; x/y/z metres, a/b degrees)."""
    limits = ts.twin_call(ts.get_control().get_stage_limits)
    return {"limits": limits}


@router.get("/stage")
def get_stage():
    pos = ts.twin_call(ts.get_control().get_stage)
    return _stage_dict(pos)


@router.post("/stage")
def set_stage(request: SetStageRequest):
    """Move the stage. Rejected moves (safety limits) return HTTP 400 with the
    twin's violation message; the stage does not move."""
    ts.require_idle()
    pos = {k: v for k, v in request.position.model_dump().items() if v is not None}
    ts.twin_call(ts.get_control().set_stage, pos, relative=request.relative)
    new_pos = ts.twin_call(ts.get_control().get_stage)
    return {
        "success": True,
        "new_position": _stage_dict(new_pos),
        "relative": request.relative,
    }


@router.get("/beam")
def get_beam():
    return ts.twin_call(ts.get_control().get_beam)


@router.post("/beam")
def set_beam(request: SetBeamRequest):
    ts.require_idle()
    settings = {k: v for k, v in request.settings.model_dump().items() if v is not None}
    result = ts.twin_call(ts.get_control().set_beam, settings, relative=request.relative)
    return {"success": True, **result}


@router.get("/mode")
def get_mode():
    return ts.twin_call(ts.get_control().get_mode)


@router.post("/mode")
def set_mode(request: SetModeRequest):
    ts.require_idle()
    result = ts.twin_call(ts.get_control().set_mode, request.mode)
    return {"success": True, **result}


@router.get("/magnification")
def get_magnification(device: str = "haadf"):
    return ts.twin_call(ts.get_control().get_magnification, device)


@router.post("/magnification")
def set_magnification(request: SetMagnificationRequest):
    ts.require_idle()
    result = ts.twin_call(
        ts.get_control().set_magnification, request.magnification, request.device
    )
    return {"success": True, **result}


@router.get("/detectors")
def get_detectors():
    return {"detectors": ts.twin_call(ts.get_control().get_detectors)}


@router.get("/detectors/{device}")
def get_detector_settings(device: str):
    state = ts.twin_call(ts.get_control().get_microscope_state)
    settings = state.get("detectors", {}).get(device)
    if settings is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Detector {device} not found")
    return {"device": device, "settings": settings}


@router.post("/detectors/{device}")
def set_detector_settings(device: str, settings: DetectorSettings):
    ts.require_idle()
    kwargs = {k: v for k, v in settings.model_dump().items() if v is not None}
    ts.twin_call(ts.get_control().device_settings, device, **kwargs)
    state = ts.twin_call(ts.get_control().get_microscope_state)
    return {"success": True, "settings": state.get("detectors", {}).get(device)}


@router.get("/resolution")
def get_resolution(device: str = "haadf"):
    return ts.twin_call(ts.get_control().get_resolution, device)


@router.post("/resolution")
def set_resolution(request: SetResolutionRequest):
    ts.require_idle()
    result = ts.twin_call(
        ts.get_control().set_resolution, request.resolution_px, request.device
    )
    return {"success": True, **result}


@router.post("/spectrum")
def acquire_spectrum(request: AcquireSpectrumRequest):
    """Acquire a single-spot EELS spectrum (probe parked at one position).
    The twin's spectrum is a physically-structured dummy — the workflow and
    API surface are what a real EELS backend would replace."""
    ts.require_idle()
    result = ts.twin_call(
        ts.get_control().acquire_spectrum,
        ev_min=request.ev_min,
        ev_max=request.ev_max,
        n_channels=request.n_channels,
        cx_um=request.cx_um,
        cy_um=request.cy_um,
    )
    return {"success": True, **result}


@router.post("/acquire")
def acquire_image(request: AcquireImageRequest):
    """Acquire a frame (IMG or DIFF depending on mode). Diffraction frames can
    take several seconds; the handler runs in the threadpool."""
    ts.require_idle()
    control = ts.get_control()
    arr = ts.twin_call(control.acquire_image, request.device)
    state = ts.twin_call(control.get_microscope_state)
    return {
        "success": True,
        "device": request.device,
        "image": ts.encode_image_png_b64(arr),
        "stage": {
            "x_um": state["stage"]["x"] * 1e6,
            "y_um": state["stage"]["y"] * 1e6,
            "z_um": state["stage"]["z"] * 1e6,
            "a": state["stage"]["a"],
            "b": state["stage"]["b"],
        },
        "mode": state["mode"],
        "sample": state["sample"],
        "settings": state.get("detectors", {}).get(request.device),
    }


@router.post("/autofocus")
def autofocus(request: AutofocusRequest):
    """Run autofocus. May legitimately fail to converge (converged=false) —
    that is a result, not an HTTP error."""
    ts.require_idle()
    result = ts.twin_call(
        ts.get_control().autofocus,
        device=request.device,
        z_range_um=request.z_range_um,
        z_steps=request.z_steps,
    )
    new_pos = ts.twin_call(ts.get_control().get_stage)
    return {"success": True, "result": result, "new_z_um": new_pos[2] * 1e6}


@router.get("/log")
def get_command_log(last_n: int = 50):
    log = ts.twin_call(ts.get_harness().get_command_log, last_n=last_n)
    return {"log": log, "count": len(log)}


@router.post("/start-server")
def start_digital_twin_server():
    """Start the digital twin in-process (development convenience)."""
    global _server_thread
    if _server_thread is not None and _server_thread.is_alive():
        return {"status": "already_running", "port": ts.DEFAULT_PORT}

    def run_server():
        from ..digital_twin.server import main
        main(host=ts.DEFAULT_HOST, port=ts.DEFAULT_PORT)

    _server_thread = threading.Thread(target=run_server, daemon=True)
    _server_thread.start()
    import time
    time.sleep(2)
    return {"status": "started", "port": ts.DEFAULT_PORT}
