"""
Microscopy Code Generator

This module generates Python automation scripts for the TEM Digital Twin
based on user-defined parameters and objectives.
"""

import os
from typing import Optional
from openai import AsyncOpenAI
from ..models.schemas import ExperimentConfig, CodeGenerationRequest


# Complete TEMClient code that matches tem_client.py exactly
TEM_CLIENT_CODE = '''
import socket
import json
import base64
import numpy as np
from typing import Any, Optional, Dict, List


class TEMClient:
    """Client for communicating with the TEM Digital Twin server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9094, timeout: int = 30):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._next_id = 1

    def _to_netstring(self, obj: dict) -> bytes:
        payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        return f"{len(payload)}:".encode("ascii") + payload + b","

    def _recv_exact(self, sock: socket.socket, n: int) -> bytes:
        chunks = []
        remaining = n
        while remaining > 0:
            chunk = sock.recv(remaining)
            if not chunk:
                raise ConnectionError("Connection closed while reading response")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _recv_netstring(self, sock: socket.socket) -> dict:
        length_bytes = b""
        while True:
            c = sock.recv(1)
            if not c:
                raise ConnectionError("No response from server")
            if c == b":":
                break
            length_bytes += c
        length = int(length_bytes.decode("ascii"))
        payload = self._recv_exact(sock, length)
        trailing = self._recv_exact(sock, 1)
        if trailing != b",":
            raise RuntimeError("Malformed netstring (missing trailing comma)")
        return json.loads(payload.decode("utf-8"))

    def _call(self, method: str, params: Optional[dict] = None) -> Any:
        if params is None:
            params = {}
        msg = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params,
        }
        self._next_id += 1
        with socket.create_connection(
            (self.host, self.port), timeout=self.timeout
        ) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(self._to_netstring(msg))
            reply = self._recv_netstring(sock)
        if "error" in reply:
            raise RuntimeError(f"Server error: {reply['error']}")
        return reply.get("result", None)

    def is_connected(self) -> bool:
        """Check if we can connect to the server."""
        try:
            with socket.create_connection(
                (self.host, self.port), timeout=2
            ) as sock:
                sock.close()
                return True
        except (ConnectionRefusedError, TimeoutError, OSError):
            return False

    def get_detectors(self) -> List[str]:
        """Get list of available detectors."""
        return self._call("get_detectors")

    def get_detector_settings(self, device: str) -> Optional[Dict[str, Any]]:
        """Get current settings for a detector."""
        return self._call("get_detector_settings", {"device": device})

    def device_settings(self, device: str, **kwargs) -> int:
        """Update detector settings."""
        return self._call("device_settings", {"device": device, **kwargs})

    def get_stage(self) -> List[float]:
        """Get current stage position [x, y, z, a, b] in METERS."""
        return self._call("get_stage")

    def get_microscope_state(self) -> Dict[str, Any]:
        """Get complete microscope state for UI sync."""
        return self._call("get_microscope_state")

    def set_stage(
        self, stage_positions: Dict[str, float], relative: bool = True
    ) -> Dict[str, Any]:
        """Set stage position. Positions should be in METERS."""
        return self._call(
            "set_stage", {"stage_positions": stage_positions, "relative": relative}
        )

    def acquire_image(self, device: str, **kwargs) -> np.ndarray:
        """Acquire an image from the specified detector."""
        result = self._call("acquire_image", {"device": device, **kwargs})

        if isinstance(result, dict) and "__ndarray_b64__" in result:
            raw = base64.b64decode(result["__ndarray_b64__"])
            arr = np.frombuffer(raw, dtype=np.dtype(result["dtype"]))
            return arr.reshape(tuple(result["shape"]))

        if isinstance(result, (list, tuple)) and len(result) == 3:
            array_list, shape, dtype = result
            return np.array(array_list, dtype=dtype).reshape(shape)

        return result

    def autofocus(
        self, device: str = "flu_camera", z_range_um: float = 2.0, z_steps: int = 9
    ) -> Dict[str, Any]:
        """Run autofocus routine."""
        return self._call(
            "autofocus",
            {"device": device, "z_range_um": z_range_um, "z_steps": z_steps},
        )

    def get_command_log(self, last_n: int = 50) -> List[Dict[str, Any]]:
        """Get recent command log."""
        return self._call("get_command_log", {"last_n": last_n})

    def clear_command_log(self) -> int:
        """Clear the command log."""
        return self._call("clear_command_log")
'''


# Code template for digital twin
DIGITAL_TWIN_TEMPLATE = '''"""
TEM Digital Twin Automation Script
Generated by GridScope AI Assistant

Objective: {objective}

This script connects to the local TEM Digital Twin server on port 9094.
Make sure the digital twin server is running before executing this script.
"""

import time
from typing import List, Tuple, Dict, Any
{tem_client_code}

# ========================================
# Configuration
# ========================================
CONFIG = {{
    "host": "127.0.0.1",
    "port": 9094,
    "field_of_view_um": {fov},
    "noise_sigma": 8.0,
    "grid_rows": {grid_rows},
    "grid_cols": {grid_cols},
    "step_size_um": {step_size},
    "start_x_um": {start_x},
    "start_y_um": {start_y},
    "autofocus_enabled": {autofocus},
    "autofocus_z_range_um": 4.0,
    "autofocus_z_steps": 9,
    "dwell_time_s": {dwell_s},
}}


def calculate_tile_positions(
    start_x_um: float,
    start_y_um: float,
    step_size_um: float,
    rows: int,
    cols: int
) -> List[Tuple[int, float, float]]:
    """Calculate all tile positions in micrometers."""
    positions = []
    tile_index = 0
    for row in range(rows):
        for col in range(cols):
            x_um = start_x_um + col * step_size_um
            y_um = start_y_um + row * step_size_um
            positions.append((tile_index, x_um, y_um))
            tile_index += 1
    return positions


def run_experiment():
    """Run the automated grid imaging experiment."""
    print("=" * 60)
    print("TEM Digital Twin - Automated Grid Imaging")
    print("=" * 60)

    # Initialize TEMClient
    tem = TEMClient(host=CONFIG["host"], port=CONFIG["port"])
    
    # Check connection
    if not tem.is_connected():
        print("ERROR: Cannot connect to TEM Digital Twin server!")
        print("Make sure the server is running: python run_digital_twin.py")
        return None
    
    print(f"Connected to TEM at {{CONFIG['host']}}:{{CONFIG['port']}}")
    
    # Get current microscope state
    state = tem.get_microscope_state()
    print(f"Microscope status: {{state['status']}}")
    print(f"Available detectors: {{tem.get_detectors()}}")

    # Configure the camera
    tem.device_settings(
        "flu_camera",
        field_of_view_um=CONFIG["field_of_view_um"],
        noise_sigma=CONFIG["noise_sigma"]
    )
    print(f"Camera configured: FOV={{CONFIG['field_of_view_um']}} µm")
    
    # Get detector settings to confirm
    detector_settings = tem.get_detector_settings("flu_camera")
    print(f"Detector settings: {{detector_settings}}")

    # Calculate tile positions
    positions = calculate_tile_positions(
        CONFIG["start_x_um"],
        CONFIG["start_y_um"],
        CONFIG["step_size_um"],
        CONFIG["grid_rows"],
        CONFIG["grid_cols"]
    )
    total_tiles = len(positions)
    print(f"\\nTotal tiles to acquire: {{total_tiles}}")
    print("-" * 60)

    acquired_images = []

    for tile_index, x_um, y_um in positions:
        print(f"\\nTile {{tile_index + 1}}/{{total_tiles}}: X={{x_um:.2f}} µm, Y={{y_um:.2f}} µm")

        # Move to position (convert µm to meters)
        x_m = x_um * 1e-6
        y_m = y_um * 1e-6
        tem.set_stage({{"x": x_m, "y": y_m}}, relative=False)
        
        # Get and display current stage position
        stage_pos = tem.get_stage()
        print(f"  Stage position: X={{stage_pos[0]*1e6:.2f}} µm, Y={{stage_pos[1]*1e6:.2f}} µm")

        # Autofocus if enabled
        if CONFIG["autofocus_enabled"]:
            af_result = tem.autofocus(
                device="flu_camera", 
                z_range_um=CONFIG["autofocus_z_range_um"], 
                z_steps=CONFIG["autofocus_z_steps"]
            )
            print(f"  Autofocus: Z adjusted by {{af_result['best_z_um_relative']:.2f}} µm")

        # Acquire image
        img = tem.acquire_image("flu_camera")
        acquired_images.append({{
            "tile_index": tile_index,
            "x_um": x_um,
            "y_um": y_um,
            "image": img
        }})
        print(f"  Image acquired: {{img.shape}}, dtype={{img.dtype}}")

        # Dwell time
        if CONFIG["dwell_time_s"] > 0:
            time.sleep(CONFIG["dwell_time_s"])

    print("\\n" + "=" * 60)
    print(f"Experiment complete! Acquired {{len(acquired_images)}} images.")
    print("=" * 60)
    
    # Get command log
    log = tem.get_command_log(last_n=10)
    print(f"\\nLast {{len(log)}} commands logged")

    return acquired_images


def save_images(images: List[Dict[str, Any]], output_dir: str = "."):
    """Save acquired images to disk."""
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    for img_data in images:
        filename = os.path.join(output_dir, f"tile_{{img_data['tile_index']:04d}}.npy")
        np.save(filename, img_data["image"])
        print(f"Saved: {{filename}}")


if __name__ == "__main__":
    images = run_experiment()
    
    if images:
        # Optionally visualize with matplotlib
        try:
            import matplotlib.pyplot as plt
            
            n_display = min(4, len(images))
            fig, axes = plt.subplots(1, n_display, figsize=(4 * n_display, 4))
            if n_display == 1:
                axes = [axes]
            
            for i, img_data in enumerate(images[:n_display]):
                axes[i].imshow(img_data["image"], cmap="gray")
                axes[i].set_title(f"Tile {{img_data['tile_index']}}\\n({{img_data['x_um']:.1f}}, {{img_data['y_um']:.1f}}) µm")
                axes[i].axis("off")
            
            plt.tight_layout()
            plt.savefig("acquired_tiles.png", dpi=150)
            print("\\nSaved preview to acquired_tiles.png")
            plt.show()
        except ImportError:
            print("\\nInstall matplotlib to visualize: pip install matplotlib")
'''


class MicroscopyCodeGenerator:
    """Generates Python code for microscopy automation using TEMClient."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the code generator."""
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if self.api_key:
            self.client = AsyncOpenAI(api_key=self.api_key)
        else:
            self.client = None
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o")

    def _get_config_values(self, config: Optional[ExperimentConfig]) -> dict:
        """Extract configuration values with defaults."""
        if config:
            return {
                "fov": config.fov,
                "grid_rows": config.grid.rows,
                "grid_cols": config.grid.cols,
                "step_size": config.grid.step_size,
                "start_x": config.start_pos.x,
                "start_y": config.start_pos.y,
                "autofocus": str(config.autofocus_each_tile),
                "dwell_s": config.dwell_s,
            }
        else:
            return {
                "fov": 20,
                "grid_rows": 5,
                "grid_cols": 5,
                "step_size": 16.0,
                "start_x": 0,
                "start_y": 0,
                "autofocus": "True",
                "dwell_s": 0.5,
            }

    def generate_from_template(self, request: CodeGenerationRequest) -> str:
        """Generate code using the digital twin template."""
        values = self._get_config_values(request.experiment_config)
        values["objective"] = request.objective
        values["tem_client_code"] = TEM_CLIENT_CODE
        
        return DIGITAL_TWIN_TEMPLATE.format(**values)

    async def generate_with_llm(self, request: CodeGenerationRequest) -> dict:
        """Generate code using LLM for custom requirements."""
        if not self.client:
            code = self.generate_from_template(request)
            return {
                "code": code,
                "explanation": "Generated using template (no API key configured)",
                "warnings": ["LLM enhancement unavailable"],
                "suggested_modifications": [],
            }

        config_context = ""
        if request.experiment_config:
            config = request.experiment_config
            config_context = f"""
Current Experiment Configuration:
- FOV: {config.fov} µm
- Grid: {config.grid.rows}x{config.grid.cols} tiles
- Step Size: {config.grid.step_size} µm
- Start Position: ({config.start_pos.x}, {config.start_pos.y}) µm
- Autofocus: {config.autofocus_each_tile}
- Dwell Time: {config.dwell_s}s
"""

        prompt = f"""Generate a Python script for the TEM Digital Twin based on this request:

Objective: {request.objective}
{config_context}

Additional Requirements: {request.additional_requirements or 'None'}

IMPORTANT: You MUST use ONLY these TEMClient methods:
- tem.is_connected() -> bool
- tem.get_detectors() -> List[str]  
- tem.get_detector_settings(device: str) -> Dict
- tem.device_settings(device: str, **kwargs) -> int
- tem.get_stage() -> List[float]  # Returns [x,y,z,a,b] in METERS
- tem.get_microscope_state() -> Dict
- tem.set_stage(stage_positions: Dict, relative: bool) -> Dict  # Positions in METERS
- tem.acquire_image(device: str) -> np.ndarray
- tem.autofocus(device, z_range_um, z_steps) -> Dict
- tem.get_command_log(last_n) -> List
- tem.clear_command_log() -> int

Include the full TEMClient class in your code.
Stage positions must be in METERS (multiply µm by 1e-6).

Respond with JSON:
{{
    "code": "complete python code with TEMClient class included",
    "explanation": "what the code does",
    "warnings": ["safety notes"],
    "suggested_modifications": ["customization ideas"]
}}"""

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert microscopy automation programmer for the TEM Digital Twin. Generate clean Python code using ONLY the TEMClient API. Always include the full TEMClient class. Respond with valid JSON."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=4000,
        )

        import json
        try:
            result = json.loads(response.choices[0].message.content or "{}")
            return result
        except json.JSONDecodeError:
            content = response.choices[0].message.content or ""
            return {
                "code": content,
                "explanation": "Generated code",
                "warnings": [],
                "suggested_modifications": [],
            }

    async def generate(self, request: CodeGenerationRequest) -> dict:
        """Generate microscopy automation code."""
        # Always use LLM if available and there are custom requirements
        if self.client and request.additional_requirements:
            return await self.generate_with_llm(request)
        
        # Use template for standard requests
        code = self.generate_from_template(request)
        
        return {
            "code": code,
            "explanation": f"Generated TEM Digital Twin script for: {request.objective}",
            "warnings": [
                "Make sure the Digital Twin server is running on port 9094",
                "Stage positions are in micrometers in config but converted to meters for API calls",
            ],
            "suggested_modifications": [
                "Adjust field_of_view_um for different magnifications (5-50 µm)",
                "Modify autofocus parameters for faster/slower focus search",
                "Add image saving with save_images() function",
            ],
        }
