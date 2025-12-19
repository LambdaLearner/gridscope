"""API routes for executing code on the TEM Digital Twin."""

import asyncio
import traceback
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json

from ..digital_twin.tem_client import TEMClient

router = APIRouter(prefix="/execute", tags=["execute"])


class ExecuteRequest(BaseModel):
    """Request to execute operations on the digital twin."""
    operations: List[Dict[str, Any]]


class SimpleExecuteRequest(BaseModel):
    """Simple execution request for common operations."""
    action: str  # "acquire", "move", "autofocus", "scan_grid"
    params: Dict[str, Any] = {}


def get_client() -> TEMClient:
    """Get TEM client."""
    return TEMClient(host="127.0.0.1", port=9094, timeout=30)


@router.post("/run")
async def execute_operations(request: ExecuteRequest):
    """Execute a sequence of operations on the digital twin.
    
    Returns results for each operation.
    """
    client = get_client()
    
    if not client.is_connected():
        raise HTTPException(
            status_code=503,
            detail="Digital Twin server not connected. Start it with: python run_digital_twin.py"
        )
    
    results = []
    
    for idx, op in enumerate(request.operations):
        try:
            operation = op.get("operation")
            params = op.get("params", {})
            
            if operation == "acquire_image":
                device = params.get("device", "flu_camera")
                result = client.acquire_image_base64(device)
                stage = client.get_stage()
                results.append({
                    "operation": operation,
                    "success": True,
                    "image": result,
                    "stage": {
                        "x_um": stage[0] * 1e6,
                        "y_um": stage[1] * 1e6,
                        "z_um": stage[2] * 1e6,
                    }
                })
                
            elif operation == "set_stage":
                position = params.get("position", {})
                relative = params.get("relative", True)
                # Convert µm to meters
                pos_m = {}
                for key in ["x", "y", "z"]:
                    if key in position:
                        pos_m[key] = position[key] * 1e-6
                client.set_stage(pos_m, relative=relative)
                new_pos = client.get_stage()
                results.append({
                    "operation": operation,
                    "success": True,
                    "stage": {
                        "x_um": new_pos[0] * 1e6,
                        "y_um": new_pos[1] * 1e6,
                        "z_um": new_pos[2] * 1e6,
                    }
                })
                
            elif operation == "autofocus":
                device = params.get("device", "flu_camera")
                z_range = params.get("z_range_um", 4.0)
                z_steps = params.get("z_steps", 9)
                result = client.autofocus(device, z_range, z_steps)
                results.append({
                    "operation": operation,
                    "success": True,
                    "result": result
                })
                
            elif operation == "device_settings":
                device = params.get("device", "flu_camera")
                settings = {k: v for k, v in params.items() if k != "device"}
                client.device_settings(device, **settings)
                updated = client.get_detector_settings(device)
                results.append({
                    "operation": operation,
                    "success": True,
                    "settings": updated
                })
                
            elif operation == "get_state":
                state = client.get_microscope_state()
                results.append({
                    "operation": operation,
                    "success": True,
                    "state": state
                })
                
            else:
                results.append({
                    "operation": operation,
                    "success": False,
                    "error": f"Unknown operation: {operation}"
                })
                
        except Exception as e:
            results.append({
                "operation": op.get("operation", "unknown"),
                "success": False,
                "error": str(e)
            })
    
    return {"results": results}


@router.post("/simple")
async def simple_execute(request: SimpleExecuteRequest):
    """Execute a simple action on the digital twin."""
    client = get_client()
    
    if not client.is_connected():
        raise HTTPException(
            status_code=503,
            detail="Digital Twin not connected"
        )
    
    try:
        if request.action == "acquire":
            # Set FOV if provided
            if "fov_um" in request.params:
                client.device_settings("haadf", field_of_view_um=request.params["fov_um"])
            
            # Acquire image
            result = client.acquire_image_base64("haadf")
            stage = client.get_stage()
            
            return {
                "success": True,
                "action": "acquire",
                "image": result,
                "stage": {
                    "x_um": stage[0] * 1e6,
                    "y_um": stage[1] * 1e6,
                    "z_um": stage[2] * 1e6,
                }
            }
            
        elif request.action == "move":
            # Support both dx/dy (meters) and x_um/y_um (micrometers)
            if "dx" in request.params or "dy" in request.params:
                dx = request.params.get("dx", 0)  # in meters
                dy = request.params.get("dy", 0)  # in meters
                client.set_stage({"x": dx, "y": dy}, relative=True)
            else:
                x_um = request.params.get("x_um", 0)
                y_um = request.params.get("y_um", 0)
                relative = request.params.get("relative", True)
                client.set_stage({"x": x_um * 1e-6, "y": y_um * 1e-6}, relative=relative)
            
            new_pos = client.get_stage()
            
            return {
                "success": True,
                "action": "move",
                "new_position": {
                    "x_um": new_pos[0] * 1e6,
                    "y_um": new_pos[1] * 1e6,
                    "z_um": new_pos[2] * 1e6,
                    "a": new_pos[3] if len(new_pos) > 3 else 0,
                    "b": new_pos[4] if len(new_pos) > 4 else 0,
                }
            }
            
        elif request.action == "tilt":
            # Set tilt angles (a = alpha, b = beta) in degrees
            a = request.params.get("a", None)
            b = request.params.get("b", None)
            relative = request.params.get("relative", False)
            
            tilt_params = {}
            if a is not None:
                tilt_params["a"] = float(a)
            if b is not None:
                tilt_params["b"] = float(b)
            
            if tilt_params:
                client.set_stage(tilt_params, relative=relative)
            
            new_pos = client.get_stage()
            
            return {
                "success": True,
                "action": "tilt",
                "new_position": {
                    "x_um": new_pos[0] * 1e6,
                    "y_um": new_pos[1] * 1e6,
                    "z_um": new_pos[2] * 1e6,
                    "a": new_pos[3] if len(new_pos) > 3 else 0,
                    "b": new_pos[4] if len(new_pos) > 4 else 0,
                }
            }
            
        elif request.action == "autofocus":
            z_range = request.params.get("z_range_um", 4.0)
            z_steps = request.params.get("z_steps", 9)
            
            result = client.autofocus("haadf", z_range, z_steps)
            
            return {
                "success": True,
                "action": "autofocus",
                "result": result
            }
            
        elif request.action == "scan_grid":
            rows = request.params.get("rows", 3)
            cols = request.params.get("cols", 3)
            step_um = request.params.get("step_um", 10)
            start_x = request.params.get("start_x_um", 0)
            start_y = request.params.get("start_y_um", 0)
            autofocus = request.params.get("autofocus", True)
            fov_um = request.params.get("fov_um", 20)
            
            # Configure detector
            client.device_settings("haadf", field_of_view_um=fov_um, noise_sigma=8.0)
            
            images = []
            logs = []
            
            for row in range(rows):
                for col in range(cols):
                    tile_idx = row * cols + col
                    x_um = start_x + col * step_um
                    y_um = start_y + row * step_um
                    
                    # Move
                    client.set_stage({"x": x_um * 1e-6, "y": y_um * 1e-6}, relative=False)
                    logs.append(f"Moved to ({x_um:.1f}, {y_um:.1f}) µm")
                    
                    # Autofocus
                    if autofocus:
                        af = client.autofocus("haadf", 4.0, 9)
                        logs.append(f"Autofocus: Z adjusted by {af['best_z_um_relative']:.2f} µm")
                    
                    # Acquire
                    img = client.acquire_image_base64("haadf")
                    images.append({
                        "tile_index": tile_idx,
                        "x_um": x_um,
                        "y_um": y_um,
                        "image": img
                    })
                    logs.append(f"Acquired tile {tile_idx + 1}/{rows * cols}")
            
            return {
                "success": True,
                "action": "scan_grid",
                "images": images,
                "logs": logs,
                "total_tiles": rows * cols
            }
            
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown action: {request.action}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stream-test")
async def stream_test():
    """Test streaming endpoint."""
    async def generate():
        for i in range(5):
            data = {"step": i, "message": f"Processing step {i+1}/5"}
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(0.5)
        yield f"data: {json.dumps({'complete': True})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream"
    )

