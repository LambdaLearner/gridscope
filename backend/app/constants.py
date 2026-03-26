"""
Shared constants for the GridScope backend.

Single source of truth for detector names, API specifications,
and workflow templates used by both llm_agent.py and code_generator.py.
"""

from pathlib import Path

# Default detector name — single source of truth
DEFAULT_DETECTOR = "haadf"

# Complete API reference for the STEMClient.
# Imported by llm_agent.py (system prompt) and code_generator.py (LLM prompt).
MICROSCOPE_API_SPEC = """## STEMClient API Reference

```python
from tem_client import STEMClient

stem = STEMClient(host="127.0.0.1", port=9094, timeout=30)

# --- Connection ---
stem.is_connected() -> bool
    # Check if the Digital Twin server is running

# --- Detectors ---
stem.get_detectors() -> List[str]
    # Returns: ["haadf"]

stem.get_detector_settings(device: str) -> Dict
    # Returns: {"size": 256, "exposure": 0.1, "binning": 1,
    #           "field_of_view_um": 20.0, "noise_sigma": 12.0}

stem.device_settings(device: str, **kwargs) -> int
    # Set detector settings.
    # Example: stem.device_settings("haadf", field_of_view_um=15.0, noise_sigma=8.0)

# --- Stage ---
stem.get_stage() -> List[float]
    # Returns [x, y, z, a, b] where x,y,z are in METERS, a,b are tilt in DEGREES

stem.set_stage(stage_positions: Dict[str, float], relative: bool = True) -> Dict
    # Move stage and/or set tilt. x,y,z in METERS, a,b in DEGREES
    # Example: stem.set_stage({"x": 5e-6, "y": 0}, relative=True)
    # Example: stem.set_stage({"a": 15, "b": -10}, relative=False)

stem.get_microscope_state() -> Dict
    # Returns full state: {"stage": {...}, "beam": {...}, "mode": "IMG",
    #                       "sample_type": "au_nanoparticles", ...}

# --- Tilt ---
stem.set_tilt(a: float = None, b: float = None, relative: bool = False) -> Dict
    # Set stage tilt angles (degrees). Convenience wrapper around set_stage.
    # Example: stem.set_tilt(a=30, b=0)

stem.get_tilt() -> Dict[str, float]
    # Returns {"a": <alpha_deg>, "b": <beta_deg>}

# --- Beam ---
stem.get_beam() -> Dict[str, Any]
    # Returns: {"x": 0, "y": 0, "current_pA": 50.0, "voltage_kV": 200.0}

stem.set_beam(beam_settings: Dict[str, float], relative: bool = False) -> Dict
    # Set beam parameters.
    # Example: stem.set_beam({"voltage_kV": 300, "current_pA": 100})

# --- Mode (IMG / DIFF) ---
stem.get_mode() -> Dict[str, str]
    # Returns: {"mode": "IMG"} or {"mode": "DIFF"}

stem.set_mode(mode: str = "IMG") -> Dict[str, str]
    # Set imaging mode. mode must be "IMG" or "DIFF".
    # Example: stem.set_mode("DIFF")

# --- Diffraction ---
stem.get_diffraction_settings() -> Dict[str, float]
    # Returns: {"camera_length_mm": 800.0, "beamstop_radius_px": 6.0}

stem.set_diffraction_settings(**kwargs) -> Dict[str, float]
    # Set diffraction parameters.
    # Example: stem.set_diffraction_settings(camera_length_mm=600, beamstop_radius_px=8)

# --- Sample ---
stem.get_sample_type() -> Dict[str, Any]
    # Returns: {"sample_type": "au_nanoparticles", "available": [...]}

stem.set_sample_type(sample_type: str) -> Dict[str, str]
    # Switch sample. Options: "au_nanoparticles", "fcc_crystal"

# --- Image acquisition ---
stem.acquire_image(device: str) -> np.ndarray
    # Acquire image. Returns 256x256 uint16 numpy array.
    # In DIFF mode, returns diffraction pattern.

# --- Autofocus ---
stem.autofocus(device: str = "haadf", z_range_um: float = 2.0, z_steps: int = 9) -> Dict
    # Run autofocus via sharpness maximization.
    # Returns: {"best_z_m": ..., "best_z_um_relative": ..., "scores": [...]}

# --- Command log ---
stem.get_command_log(last_n: int = 50) -> List[Dict]
stem.clear_command_log() -> int
```

## Important Notes
- Stage x, y, z positions are in METERS (multiply um by 1e-6)
- Tilt angles a (alpha) and b (beta) are in DEGREES, range -60 to +60
- The sample FOV is 200 um total; camera FOV range: 5-50 um
- Always use "haadf" as the detector
- 3D tilt is enabled: changing a/b angles shows different projections
- Available samples: au_nanoparticles (Au), fcc_crystal (FCC)
- Available modes: IMG (imaging), DIFF (diffraction)
"""

# Workflow template snippets the LLM can reference for common tasks.
WORKFLOW_TEMPLATES = {
    "tilt_series": """\
# Tilt series acquisition
alpha_angles = list(range(start_deg, end_deg + 1, step_deg))
for alpha in alpha_angles:
    stem.set_tilt(a=alpha)
    img = stem.acquire_image("haadf")
    print(f"Acquired at alpha={alpha} deg")
""",
    "diffraction_scan": """\
# Switch to diffraction mode and acquire
stem.set_mode("DIFF")
# Optionally adjust diffraction settings
stem.set_diffraction_settings(camera_length_mm=800, beamstop_radius_px=6)
diff_img = stem.acquire_image("haadf")
# Switch back to imaging
stem.set_mode("IMG")
""",
    "beam_sweep": """\
# Sweep beam voltage or current
for voltage in [100, 200, 300]:
    stem.set_beam({"voltage_kV": voltage})
    img = stem.acquire_image("haadf")
    print(f"Acquired at {voltage} kV")
""",
    "mode_switch": """\
# Switch between IMG and DIFF modes
stem.set_mode("DIFF")
diff_pattern = stem.acquire_image("haadf")
stem.set_mode("IMG")
real_image = stem.acquire_image("haadf")
""",
}

# Path to tem_client.py source (for auto-generation in code_generator)
TEM_CLIENT_SOURCE_PATH = Path(__file__).parent / "digital_twin" / "tem_client.py"
