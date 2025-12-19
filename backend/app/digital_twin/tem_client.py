"""
STEM Digital Twin Client

Python client to communicate with the STEM Digital Twin server
via netstring JSON-RPC protocol.

Features:
- Stage control (x, y, z position in meters)
- Tilt control (a, b angles in degrees) for 3D tomography simulation
- Beam control (voltage_kV, current_pA)
- Imaging mode (IMG) and Diffraction mode (DIFF)
- Sample selection (Au nanoparticles, FCC crystal)
- Image acquisition with configurable FOV
- Autofocus with sharpness maximization
"""

import socket
import json
import base64
import io
import numpy as np
from typing import Any, Optional, Dict, List
from PIL import Image


class STEMClient:
    """Client for communicating with the STEM Digital Twin server."""

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

    # --- Detector API
    def get_detectors(self) -> List[str]:
        """Get list of available detectors."""
        return self._call("get_detectors")

    def get_detector_settings(self, device: str) -> Optional[Dict[str, Any]]:
        """Get current settings for a detector."""
        return self._call("get_detector_settings", {"device": device})

    def device_settings(self, device: str, **kwargs) -> int:
        """Update detector settings."""
        return self._call("device_settings", {"device": device, **kwargs})

    # --- Stage controls
    def get_stage(self) -> List[float]:
        """Get current stage position [x, y, z, a, b]."""
        return self._call("get_stage")

    def get_microscope_state(self) -> Dict[str, Any]:
        """Get complete microscope state for UI sync."""
        return self._call("get_microscope_state")

    def set_stage(
        self, stage_positions: Dict[str, float], relative: bool = True
    ) -> Dict[str, Any]:
        """Set stage position."""
        return self._call(
            "set_stage", {"stage_positions": stage_positions, "relative": relative}
        )

    def set_tilt(self, a: float = None, b: float = None, relative: bool = False) -> Dict[str, Any]:
        """Set stage tilt angles (degrees)."""
        tilt = {}
        if a is not None:
            tilt["a"] = a
        if b is not None:
            tilt["b"] = b
        return self._call("set_stage", {"stage_positions": tilt, "relative": relative})

    def get_tilt(self) -> Dict[str, float]:
        """Get current tilt angles (a, b) in degrees."""
        stage = self._call("get_stage")
        return {"a": stage[3], "b": stage[4]}

    # --- Beam controls
    def get_beam(self) -> Dict[str, Any]:
        """Get beam settings (voltage_kV, current_pA)."""
        return self._call("get_beam")

    def set_beam(self, beam_settings: Dict[str, float], relative: bool = False) -> Dict[str, Any]:
        """Set beam settings."""
        return self._call("set_beam", {"beam_settings": beam_settings, "relative": relative})

    # --- Mode controls (IMG / DIFF)
    def get_mode(self) -> Dict[str, str]:
        """Get current imaging mode (IMG or DIFF)."""
        return self._call("get_mode")

    def set_mode(self, mode: str = "IMG") -> Dict[str, str]:
        """Set imaging mode (IMG for imaging, DIFF for diffraction)."""
        return self._call("set_mode", {"mode": mode})

    # --- Diffraction settings
    def get_diffraction_settings(self) -> Dict[str, float]:
        """Get diffraction mode settings."""
        return self._call("get_diffraction_settings")

    def set_diffraction_settings(self, **kwargs) -> Dict[str, float]:
        """Set diffraction settings (camera_length_mm, beamstop_radius_px)."""
        return self._call("set_diffraction_settings", kwargs)

    # --- Sample controls
    def get_sample_type(self) -> Dict[str, Any]:
        """Get current sample type and available samples."""
        return self._call("get_sample_type")

    def set_sample_type(self, sample_type: str) -> Dict[str, str]:
        """Switch sample (au_nanoparticles or fcc_crystal)."""
        return self._call("set_sample_type", {"sample_type": sample_type})

    # --- Image acquisition
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

    def acquire_image_base64(self, device: str, **kwargs) -> Dict[str, Any]:
        """Acquire image and return as base64 PNG (for web transport)."""
        result = self._call("acquire_image", {"device": device, **kwargs})
        
        if isinstance(result, dict) and "__ndarray_b64__" in result:
            raw = base64.b64decode(result["__ndarray_b64__"])
            arr = np.frombuffer(raw, dtype=np.dtype(result["dtype"]))
            arr = arr.reshape(tuple(result["shape"]))
            
            # Normalize to 8-bit for PNG
            arr_8bit = ((arr - arr.min()) / (arr.max() - arr.min() + 1e-6) * 255).astype(np.uint8)
            
            # Encode as PNG
            img = Image.fromarray(arr_8bit, mode='L')
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            png_base64 = base64.b64encode(buffer.getvalue()).decode('ascii')
            return {
                "image_base64": f"data:image/png;base64,{png_base64}",
                "width": arr.shape[1],
                "height": arr.shape[0],
                "dtype": str(arr.dtype),
            }
        
        return result

    # --- Autofocus
    def autofocus(
        self, device: str = "haadf", z_range_um: float = 2.0, z_steps: int = 9
    ) -> Dict[str, Any]:
        """Run autofocus routine."""
        return self._call(
            "autofocus",
            {"device": device, "z_range_um": z_range_um, "z_steps": z_steps},
        )

    # --- Command log
    def get_command_log(self, last_n: int = 50) -> List[Dict[str, Any]]:
        """Get recent command log."""
        return self._call("get_command_log", {"last_n": last_n})

    def clear_command_log(self) -> int:
        """Clear the command log."""
        return self._call("clear_command_log")


# Alias for backward compatibility
TEMClient = STEMClient
