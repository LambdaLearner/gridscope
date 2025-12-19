"""API routes for the TEM Digital Twin microscope control."""

import os
import threading
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from ..digital_twin.tem_client import TEMClient

router = APIRouter(prefix="/microscope", tags=["microscope"])

# Global client instance
_client: Optional[TEMClient] = None
_server_thread: Optional[threading.Thread] = None

# Default connection settings
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9094


def get_client() -> TEMClient:
    """Get or create the TEM client."""
    global _client
    if _client is None:
        host = os.getenv("TEM_HOST", DEFAULT_HOST)
        port = int(os.getenv("TEM_PORT", DEFAULT_PORT))
        _client = TEMClient(host=host, port=port)
    return _client


# ===== Pydantic Models =====

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
    noise_sigma: Optional[float] = None


class AcquireImageRequest(BaseModel):
    device: str = "flu_camera"


class AutofocusRequest(BaseModel):
    device: str = "flu_camera"
    z_range_um: float = 2.0
    z_steps: int = 9


class ExecuteCommandRequest(BaseModel):
    """Execute a raw command on the microscope."""
    command: str = Field(..., description="Command to execute (method name)")
    params: Dict[str, Any] = Field(default_factory=dict, description="Command parameters")


# ===== Endpoints =====

@router.get("/status")
async def get_status():
    """Check if the digital twin server is running."""
    client = get_client()
    try:
        connected = client.is_connected()
        if connected:
            state = client.get_microscope_state()
            return {
                "connected": True,
                "host": client.host,
                "port": client.port,
                "state": state,
            }
        return {"connected": False, "host": client.host, "port": client.port}
    except Exception as e:
        return {"connected": False, "error": str(e)}


@router.get("/state")
async def get_microscope_state():
    """Get the complete microscope state."""
    client = get_client()
    try:
        state = client.get_microscope_state()
        return state
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to get state: {str(e)}")


@router.get("/detectors")
async def get_detectors():
    """Get list of available detectors."""
    client = get_client()
    try:
        detectors = client.get_detectors()
        return {"detectors": detectors}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to get detectors: {str(e)}")


@router.get("/detectors/{device}")
async def get_detector_settings(device: str):
    """Get settings for a specific detector."""
    client = get_client()
    try:
        settings = client.get_detector_settings(device)
        if settings is None:
            raise HTTPException(status_code=404, detail=f"Detector {device} not found")
        return {"device": device, "settings": settings}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to get settings: {str(e)}")


@router.post("/detectors/{device}")
async def set_detector_settings(device: str, settings: DetectorSettings):
    """Update detector settings."""
    client = get_client()
    try:
        # Build kwargs from non-None settings
        kwargs = {k: v for k, v in settings.model_dump().items() if v is not None}
        result = client.device_settings(device, **kwargs)
        
        # Get updated settings
        updated = client.get_detector_settings(device)
        return {"success": result == 1, "settings": updated}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to set settings: {str(e)}")


@router.get("/stage")
async def get_stage():
    """Get current stage position."""
    client = get_client()
    try:
        pos = client.get_stage()
        return {
            "x": pos[0],
            "y": pos[1],
            "z": pos[2],
            "a": pos[3],
            "b": pos[4],
            "x_um": pos[0] * 1e6,
            "y_um": pos[1] * 1e6,
            "z_um": pos[2] * 1e6,
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to get stage: {str(e)}")


@router.post("/stage")
async def set_stage(request: SetStageRequest):
    """Set stage position."""
    client = get_client()
    try:
        pos_dict = {k: v for k, v in request.position.model_dump().items() if v is not None}
        result = client.set_stage(pos_dict, relative=request.relative)
        
        # Get updated position
        new_pos = client.get_stage()
        return {
            "success": True,
            "new_position": {
                "x": new_pos[0],
                "y": new_pos[1],
                "z": new_pos[2],
                "a": new_pos[3],
                "b": new_pos[4],
                "x_um": new_pos[0] * 1e6,
                "y_um": new_pos[1] * 1e6,
                "z_um": new_pos[2] * 1e6,
            },
            "relative": request.relative,
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to set stage: {str(e)}")


@router.post("/acquire")
async def acquire_image(request: AcquireImageRequest):
    """Acquire an image from the microscope."""
    client = get_client()
    try:
        result = client.acquire_image_base64(request.device)
        
        # Get current state for context
        stage = client.get_stage()
        detector_settings = client.get_detector_settings(request.device)
        
        return {
            "success": True,
            "device": request.device,
            "image": result,
            "stage": {
                "x_um": stage[0] * 1e6,
                "y_um": stage[1] * 1e6,
                "z_um": stage[2] * 1e6,
            },
            "settings": detector_settings,
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to acquire image: {str(e)}")


@router.post("/autofocus")
async def autofocus(request: AutofocusRequest):
    """Run autofocus routine."""
    client = get_client()
    try:
        result = client.autofocus(
            device=request.device,
            z_range_um=request.z_range_um,
            z_steps=request.z_steps,
        )
        
        # Get updated stage position
        stage = client.get_stage()
        
        return {
            "success": True,
            "result": result,
            "new_z_um": stage[2] * 1e6,
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Autofocus failed: {str(e)}")


@router.post("/execute")
async def execute_command(request: ExecuteCommandRequest):
    """Execute a raw command on the microscope.
    
    This endpoint allows executing any method on the TEM server.
    Use with caution.
    """
    client = get_client()
    
    # Map of allowed commands to their client methods
    allowed_commands = {
        "get_detectors": client.get_detectors,
        "get_stage": client.get_stage,
        "set_stage": client.set_stage,
        "device_settings": client.device_settings,
        "acquire_image": client.acquire_image_base64,
        "autofocus": client.autofocus,
        "get_microscope_state": client.get_microscope_state,
        "get_command_log": client.get_command_log,
        "clear_command_log": client.clear_command_log,
        # STEM-specific commands
        "get_mode": client.get_mode,
        "set_mode": client.set_mode,
        "get_beam": client.get_beam,
        "set_beam": client.set_beam,
        "get_sample_type": client.get_sample_type,
        "set_sample_type": client.set_sample_type,
        "get_diffraction_settings": client.get_diffraction_settings,
        "set_diffraction_settings": client.set_diffraction_settings,
    }
    
    if request.command not in allowed_commands:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown command: {request.command}. Allowed: {list(allowed_commands.keys())}"
        )
    
    try:
        method = allowed_commands[request.command]
        result = method(**request.params) if request.params else method()
        return {"success": True, "command": request.command, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Command failed: {str(e)}")


@router.get("/log")
async def get_command_log(last_n: int = 50):
    """Get recent command log from the microscope."""
    client = get_client()
    try:
        log = client.get_command_log(last_n=last_n)
        return {"log": log, "count": len(log)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to get log: {str(e)}")


@router.post("/start-server")
async def start_digital_twin_server(background_tasks: BackgroundTasks):
    """Start the digital twin server in the background.
    
    Note: This is for development/testing. In production, 
    run the server separately.
    """
    global _server_thread
    
    if _server_thread is not None and _server_thread.is_alive():
        return {"status": "already_running", "port": DEFAULT_PORT}
    
    def run_server():
        from ..digital_twin.tem_server import main
        main(host=DEFAULT_HOST, port=DEFAULT_PORT)
    
    _server_thread = threading.Thread(target=run_server, daemon=True)
    _server_thread.start()
    
    # Wait a bit for server to start
    import time
    time.sleep(2)
    
    return {"status": "started", "port": DEFAULT_PORT}

