# -*- coding: utf-8 -*-
"""
Created on Thu Dec 18 17:14:33 2025

@author: alexa
"""

import socket, json, base64
import numpy as np
from typing import Any
import time

from fastmcp import FastMCP

mcp = FastMCP("Hackathon TEM MCP")

@mcp.tool()
def get_detectors():
    ''' Returns which detectors are available '''
    return stem.get_detectors()

@mcp.tool()
def device_settings(device):
    ''' 
    Returns the device settings.
    
    Parameters
    ----------
    device : str
        Name of the device. Available options can be found using the get_detectors() function.
    '''
    return stem.device_settings()

@mcp.tool()
def get_stage():
    ''' Returns the current microscope stage position '''
    return stem.get_stage()

@mcp.tool()
def set_stage(x, y, relative=True):
    '''
    Sets the stage position.

    Parameters
    ----------
    x : float
        x movement in metres.
    y : float
        y movement in metres.
    relative:
        If relative is True, the stage moved relative to the current position.
        If relative is False, the stage is moved to the absolute position within the internal co-ordinate system of the microscope.
    '''
    return stem.set_stage({"x": x, "y": y}, relative)

@mcp.tool()
def get_beam():
    '''
    Returns the beam position.
    '''
    return stem.get_beam()

@mcp.tool()
def set_beam(x, y, relative=False):
    '''
    Sets the beam position.
    
    Parameters
    ----------
    x : float
        x movement.
    y : float
        y movement.
    relative:
        If relative is True, the beam moved relative to the current position.
        If relative is False, the beam is moved to the absolute position within the internal co-ordinate system of the microscope.
    '''
    return stem.set_beam({"x": x, "y": y}, relative)

@mcp.tool()
def get_mode():
    '''
    Returns the mode of the microscope.
    '''
    return stem.get_mode()

@mcp.tool()
def set_mode(mode="TEM"):
    '''
    Set the mode of the microscope.
    '''
    return stem.set_mode(mode)

@mcp.tool()
def get_diffraction_settings():
    '''
    Returns the diffraction settings of the microscope.
    '''
    return stem.get_diffraction_settings()
"""
@mcp.tool()
def set_diffraction_settings(**kwargs):
    '''
    Sets the diffraction settings of the microscope.
    '''
    return stem.set_diffraction_settings(**kwargs)
"""
@mcp.tool()
def acquire_image(device="haadf"):
    ''' 
    Acquire an image using the specified device.
    
    Parameters
    ----------
    device : str
        Name of the device. Available options can be found using the get_detectors() function.
    
    Returns
    ----------
    image : array
        Acquired image
    '''
    image = stem.acquire_image(device)
    np.save(f'{str(int(time.time()))}.npy', image)
    return image

@mcp.tool()
def autofocus(device="haadf", z_range_um=2.0, z_steps=9):
    '''
    Performs autofocusing by maximising sharpness metric. 
    z_range_um is the focal range to search in micrometers.
    z_steps is the number of steps in the search

    Parameters
    ----------
    z_range_um : float
        Maximum values plus and minus from the current defocus to 
        search. The default is 2.0 micrometers.
    z_steps : float
    
    '''
    return stem.autofocus(device, z_range_um, z_steps)

class STEMClient:
    def __init__(self, host="127.0.0.1", port=9094, timeout=30):
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

    def _call(self, method: str, params=None) -> Any:
        if params is None:
            params = {}
        msg = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        self._next_id += 1
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(self._to_netstring(msg))
            reply = self._recv_netstring(sock)
        if "error" in reply:
            raise RuntimeError(f"Server error: {reply['error']}")
        return reply.get("result", None)

    # --- wrappers
    def get_detectors(self):
        return self._call("get_detectors")

    def device_settings(self, device, **kwargs):
        return self._call("device_settings", {"device": device, **kwargs})

    def get_stage(self):
        return self._call("get_stage")

    def set_stage(self, stage_positions, relative=True):
        return self._call("set_stage", {"stage_positions": stage_positions, "relative": relative})

    def get_beam(self):
        return self._call("get_beam")

    def set_beam(self, beam_settings, relative=False):
        return self._call("set_beam", {"beam_settings": beam_settings, "relative": relative})

    def get_mode(self):
        return self._call("get_mode")

    def set_mode(self, mode="TEM"):
        return self._call("set_mode", {"mode": mode})

    def get_diffraction_settings(self):
        return self._call("get_diffraction_settings")

    def set_diffraction_settings(self, **kwargs):
        return self._call("set_diffraction_settings", kwargs)

    def acquire_image(self, device, **kwargs):
        result = self._call("acquire_image", {"device": device, **kwargs})

        # Base64 ndarray transport
        if isinstance(result, dict) and "__ndarray_b64__" in result:
            raw = base64.b64decode(result["__ndarray_b64__"])
            arr = np.frombuffer(raw, dtype=np.dtype(result["dtype"]))
            return arr.reshape(tuple(result["shape"]))

        # Backward compatibility
        if isinstance(result, (list, tuple)) and len(result) == 3:
            array_list, shape, dtype = result
            return np.array(array_list, dtype=dtype).reshape(shape)

        return result

    def autofocus(self, device="haadf", z_range_um=2.0, z_steps=9):
        return self._call("autofocus", {"device": device, "z_range_um": z_range_um, "z_steps": z_steps})

    def get_command_log(self, last_n=50):
        return self._call("get_command_log", {"last_n": last_n})

    def clear_command_log(self):
        return self._call("clear_command_log")

if __name__ == "__main__":
    stem = STEMClient(host="127.0.0.1", port=9094, timeout=60)
    mcp.run(transport="sse", host="127.0.0.1", port=8081)