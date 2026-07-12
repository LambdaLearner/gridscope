"""
Shared constants for the GridScope backend.

Single source of truth for detector names, the control-API specification
shown to the LLM, workflow templates, and the script image-marker protocol.

IMPORTANT: MICROSCOPE_API_SPEC documents ONLY MicroscopeControlClient — the
portable instrument surface. Generated scripts must run unmodified against a
real microscope, so nothing simulation-only (samples, environments, drift,
degradation) may appear here. A unit test asserts every method named in this
spec exists on MicroscopeControlClient.
"""

from pathlib import Path

# Default detector name — single source of truth
DEFAULT_DETECTOR = "haadf"

# Marker prefix generated scripts print before each base64-encoded frame.
# The script runner parses these lines and streams the frames to the UI.
IMAGE_MARKER = "##GRIDSCOPE_IMAGE##"

# Complete API reference for the portable control client.
# Imported by llm_agent.py (system prompt) and code_generator.py (LLM prompt).
MICROSCOPE_API_SPEC = """## MicroscopeControlClient API Reference (portable control surface)

Every method below has a real-microscope counterpart. Scripts written against
this API run on the digital twin today and a vendor SDK later, unchanged.

```python
mic = MicroscopeControlClient(host="127.0.0.1", port=9094, timeout=30)

# --- Readiness ---
mic.is_ready() -> Dict
    # {"ready": bool, "error": str|None, "sample": str|None}
mic.wait_until_ready(timeout=300, poll=1.0) -> Dict

# --- Detectors ---
mic.get_detectors() -> List[str]
    # Returns: ["haadf"]
mic.device_settings(device: str, **kwargs) -> int
    # Set detector settings: size, field_of_view_um, dwell_us, binning.
    # Example: mic.device_settings("haadf", field_of_view_um=15.0)

# --- Magnification / field of view (two views of one quantity) ---
mic.get_magnification(device="haadf") -> Dict
    # {"magnification": float, "field_of_view_um": float}
mic.set_magnification(magnification: float, device="haadf") -> Dict

# --- Stage (SAFETY LIMITS APPLY) ---
mic.get_stage() -> List[float]
    # [x, y, z, a, b]: x/y/z in METRES, a/b tilt in DEGREES
mic.set_stage(sp: Dict[str, float], relative: bool = True) -> Dict
    # Move stage / set tilt. x,y,z in METRES, a,b in DEGREES.
    # Example: mic.set_stage({"x": 5e-6, "y": 0}, relative=True)
    # RAISES RuntimeError if the TARGET exceeds a soft limit — the stage does
    # not move. Wrap moves in try/except and handle rejection.
mic.get_stage_limits() -> Dict[str, float]
    # Symmetric limits per axis: {"x": 1.5e-3, "y": 1.5e-3, "z": 1e-3,
    #                             "a": 30.0, "b": 30.0}  (metres / degrees)

# --- Beam ---
mic.get_beam() -> Dict
    # {"x": 0, "y": 0, "current_pA": 50.0, "voltage_kV": 200.0}
mic.set_beam(bs: Dict[str, float], relative: bool = False) -> Dict

# --- Optics / aberrations ---
mic.get_optics() -> Dict
mic.set_optics(cs_mm=..., aperture_probe_px=...) -> Dict

# --- Mode (IMG / DIFF / EELS) ---
mic.get_mode() -> Dict            # {"mode": "IMG"|"DIFF"|"EELS"}
mic.set_mode(mode: str) -> Dict   # "IMG", "DIFF", or "EELS"

# --- Acquisition resolution windows (discrete, like a real scan generator) ---
mic.get_resolution(device="haadf") -> Dict
    # {"resolution_px": 512, "allowed": [512, 1024, 2048]}
mic.set_resolution(resolution_px: int, device="haadf") -> Dict
    # resolution_px must be one of 512/1024/2048; anything else raises.
    # Higher resolution = finer detail at the same FOV but a slower frame
    # (2048 px can take ~30 s).

# --- Diffraction projection ---
mic.get_diffraction_settings() -> Dict
mic.set_diffraction_settings(camera_length_mm=..., beamstop_radius_px=...,
                             thickness_nm=..., aperture_um=...) -> Dict

# --- Image acquisition ---
mic.acquire_image(device: str) -> np.ndarray
    # uint16 frame (image in IMG mode, diffraction pattern in DIFF mode).
    # Diffraction frames may take 1-5 s to compute on the twin.

# --- EELS spectrum acquisition (single-spot; probe parked at one position) ---
mic.acquire_spectrum(ev_min=0.0, ev_max=1000.0, n_channels=1024,
                     cx_um=None, cy_um=None) -> Dict
    # {"energy_ev": [...], "intensity": [...],
    #  "edges": [{"label": "Fe-L", "onset_ev": 708, "Z": 26}, ...],
    #  "plasmon_ev": float, "thickness_nm": float, "elements_Z": [...]}
    # Core-loss edges reflect the elements actually under the probe.

# --- Autofocus (CAN FAIL) ---
mic.autofocus(device="haadf", z_range_um=2.0, z_steps=9) -> Dict
    # {"converged": bool, "reason": str, "best_z_m": float,
    #  "best_z_um_relative": float, "scores": [[z_um, score], ...]}
    # If converged is False the stage Z was NOT moved. Check it.

# --- Full state snapshot ---
mic.get_microscope_state() -> Dict

mic.close()
```

## Important Notes
- Stage x, y, z positions are in METRES (multiply µm by 1e-6).
- Tilt angles a (alpha) and b (beta) are in DEGREES.
- Stage soft limits: ±1.5 mm (x/y), ±1 mm (z), ±30° (a/b). Out-of-range moves
  raise; the stage does not move. Handle this.
- Autofocus returns converged=False on difficult specimens. Handle this.
- Always use "haadf" as the detector.
- The specimen is chosen in the GridScope UI before the script runs. Scripts
  NEVER select samples, environments, or simulation settings — those concepts
  do not exist on a real instrument.
- After each acquisition call report_image(img, ...) (helper included in the
  script template) so the frame streams back to the GridScope UI.
"""

# Workflow template snippets the LLM can reference for common tasks.
WORKFLOW_TEMPLATES = {
    "tilt_series": """\
# Tilt series acquisition (respect the ±30° tilt limit)
for alpha in range(start_deg, end_deg + 1, step_deg):
    try:
        mic.set_stage({"a": alpha}, relative=False)
    except RuntimeError as e:
        print(f"Tilt {alpha} deg rejected: {e}")
        continue
    img = mic.acquire_image("haadf")
    report_image(img, label=f"alpha={alpha} deg")
""",
    "diffraction_scan": """\
# Switch to diffraction mode and acquire (may take a few seconds per frame)
mic.set_mode("DIFF")
mic.set_diffraction_settings(camera_length_mm=800, beamstop_radius_px=6)
diff_img = mic.acquire_image("haadf")
report_image(diff_img, label="diffraction")
mic.set_mode("IMG")
""",
    "grid_scan": """\
# Grid scan with autofocus-failure handling
for row in range(rows):
    for col in range(cols):
        x_m = (start_x_um + col * step_um) * 1e-6
        y_m = (start_y_um + row * step_um) * 1e-6
        try:
            mic.set_stage({"x": x_m, "y": y_m}, relative=False)
        except RuntimeError as e:
            print(f"Tile ({row},{col}) outside stage limits: {e}")
            continue
        af = mic.autofocus("haadf", z_range_um=4.0, z_steps=9)
        if not af["converged"]:
            print(f"Autofocus failed at ({row},{col}): {af['reason']}")
        img = mic.acquire_image("haadf")
        report_image(img, label=f"tile ({row},{col})")
""",
    "magnification_series": """\
# Zoom in until the sample's features are resolved
for mag in [10e3, 30e3, 57e3, 120e3]:
    mic.set_magnification(mag)
    img = mic.acquire_image("haadf")
    report_image(img, label=f"mag={mag/1e3:.0f} kx")
""",
}

# Path to the control-client source embedded verbatim in generated scripts.
CONTROL_CLIENT_SOURCE_PATH = (
    Path(__file__).parent / "digital_twin" / "control_client.py"
)
