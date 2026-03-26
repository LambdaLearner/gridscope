# -*- coding: utf-8 -*-
"""
GridScope MCP Server — exposes STEM Digital Twin functions as MCP tools.

Uses the canonical STEMClient from backend/app/digital_twin/tem_client.py
instead of maintaining a duplicate copy.
"""

import sys
import os
import time
import numpy as np

# Add backend root to path so we can import the canonical STEMClient
_backend_root = os.path.join(os.path.dirname(__file__), "..", "backend")
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from app.digital_twin.tem_client import STEMClient  # noqa: E402
from fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("Hackathon TEM MCP")


@mcp.tool()
def get_detectors():
    """Returns which detectors are available."""
    return stem.get_detectors()


@mcp.tool()
def device_settings(device: str):
    """
    Returns the device settings.

    Parameters
    ----------
    device : str
        Name of the device. Available options can be found using the get_detectors() function.
    """
    return stem.get_detector_settings(device)


@mcp.tool()
def get_stage():
    """Returns the current microscope stage position."""
    return stem.get_stage()


@mcp.tool()
def set_stage(x: float, y: float, relative: bool = True):
    """
    Sets the stage position.

    Parameters
    ----------
    x : float
        x movement in metres.
    y : float
        y movement in metres.
    relative : bool
        If True, the stage is moved relative to the current position.
        If False, the stage is moved to the absolute position.
    """
    return stem.set_stage({"x": x, "y": y}, relative)


@mcp.tool()
def get_beam():
    """Returns the beam settings (voltage_kV, current_pA)."""
    return stem.get_beam()


@mcp.tool()
def set_beam(voltage_kV: float = None, current_pA: float = None, relative: bool = False):
    """
    Sets the beam settings.

    Parameters
    ----------
    voltage_kV : float, optional
        Beam voltage in kV.
    current_pA : float, optional
        Beam current in pA.
    relative : bool
        If True, values are added to current settings.
    """
    settings = {}
    if voltage_kV is not None:
        settings["voltage_kV"] = voltage_kV
    if current_pA is not None:
        settings["current_pA"] = current_pA
    return stem.set_beam(settings, relative)


@mcp.tool()
def get_mode():
    """Returns the mode of the microscope (IMG or DIFF)."""
    return stem.get_mode()


@mcp.tool()
def set_mode(mode: str = "IMG"):
    """
    Set the mode of the microscope.

    Parameters
    ----------
    mode : str
        "IMG" for imaging mode, "DIFF" for diffraction mode.
    """
    return stem.set_mode(mode)


@mcp.tool()
def get_diffraction_settings():
    """Returns the diffraction settings of the microscope."""
    return stem.get_diffraction_settings()


@mcp.tool()
def set_diffraction_settings(camera_length_mm: float = None, beamstop_radius_px: float = None):
    """
    Sets the diffraction settings of the microscope.

    Parameters
    ----------
    camera_length_mm : float, optional
        Camera length in mm.
    beamstop_radius_px : float, optional
        Beamstop radius in pixels.
    """
    kwargs = {}
    if camera_length_mm is not None:
        kwargs["camera_length_mm"] = camera_length_mm
    if beamstop_radius_px is not None:
        kwargs["beamstop_radius_px"] = beamstop_radius_px
    return stem.set_diffraction_settings(**kwargs)


@mcp.tool()
def get_sample_type():
    """Returns the current sample type and available samples."""
    return stem.get_sample_type()


@mcp.tool()
def set_sample_type(sample_type: str):
    """
    Switch sample.

    Parameters
    ----------
    sample_type : str
        "au_nanoparticles" or "fcc_crystal".
    """
    return stem.set_sample_type(sample_type)


@mcp.tool()
def set_tilt(a: float = None, b: float = None, relative: bool = False):
    """
    Set stage tilt angles.

    Parameters
    ----------
    a : float, optional
        Alpha tilt in degrees (-60 to +60).
    b : float, optional
        Beta tilt in degrees (-60 to +60).
    relative : bool
        If True, angles are added to current tilt.
    """
    return stem.set_tilt(a=a, b=b, relative=relative)


@mcp.tool()
def get_tilt():
    """Returns the current tilt angles (a, b) in degrees."""
    return stem.get_tilt()


@mcp.tool()
def get_microscope_state():
    """Returns the complete microscope state."""
    return stem.get_microscope_state()


@mcp.tool()
def acquire_image(device: str = "haadf"):
    """
    Acquire an image using the specified device.

    Parameters
    ----------
    device : str
        Name of the device. Available options can be found using the get_detectors() function.

    Returns
    ----------
    image : array
        Acquired image (saved as .npy file).
    """
    image = stem.acquire_image(device)
    np.save(f"{str(int(time.time()))}.npy", image)
    return image


@mcp.tool()
def autofocus(device: str = "haadf", z_range_um: float = 2.0, z_steps: int = 9):
    """
    Performs autofocusing by maximising sharpness metric.

    Parameters
    ----------
    device : str
        Detector to use for autofocus.
    z_range_um : float
        Maximum values plus and minus from the current defocus to search. Default 2.0 um.
    z_steps : int
        Number of steps in the search.
    """
    return stem.autofocus(device, z_range_um, z_steps)


if __name__ == "__main__":
    stem = STEMClient(host="127.0.0.1", port=9094, timeout=60)
    mcp.run(transport="sse", host="127.0.0.1", port=8081)
