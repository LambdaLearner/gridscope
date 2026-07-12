"""
Shared access to the digital twin for all HTTP routes.

One place owns:
  - the MicroscopeControlClient / SimulationHarness singletons,
  - error classification (twin errors -> HTTP status codes),
  - the single-run execution lock (one script run at a time; UI mutations
    are rejected while a run is active),
  - image encoding (uint16 ndarray -> displayable PNG base64).
"""

import base64
import io
import os
import socket
import threading
import time
from typing import Any, Callable, Dict, Optional

import numpy as np
from fastapi import HTTPException
from PIL import Image

from ..digital_twin.control_client import MicroscopeControlClient
from ..digital_twin.sim_harness import SimulationHarness
from ..digital_twin.server import NO_SAMPLE_MSG, SAFETY_LIMIT_MARKER

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9094

_control: Optional[MicroscopeControlClient] = None
_harness: Optional[SimulationHarness] = None


def get_control() -> MicroscopeControlClient:
    global _control
    if _control is None:
        host = os.getenv("TEM_HOST", DEFAULT_HOST)
        port = int(os.getenv("TEM_PORT", DEFAULT_PORT))
        _control = MicroscopeControlClient(host=host, port=port)
    return _control


def get_harness() -> SimulationHarness:
    global _harness
    if _harness is None:
        _harness = SimulationHarness(get_control())
    return _harness


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------
# Twin errors cross the JSON-RPC transport as strings, so classification is
# message-based. Each rule is pinned by a route test; if the server wording
# changes, a test fails rather than the UI silently degrading.

def classify_twin_error(exc: Exception) -> HTTPException:
    # Note: deliberately NOT OSError — FileNotFoundError (a sample asking for
    # a structure file) is an OSError but is a 400, not "twin down".
    if isinstance(exc, (ConnectionError, TimeoutError, socket.timeout)):
        return HTTPException(
            status_code=503,
            detail="Digital twin server unreachable. Start it with: python run_digital_twin.py",
        )
    msg = str(exc)
    if SAFETY_LIMIT_MARKER in msg:
        return HTTPException(status_code=400, detail=_strip_rpc_prefix(msg))
    if NO_SAMPLE_MSG in msg:
        return HTTPException(status_code=409, detail=_strip_rpc_prefix(msg))
    if "Unknown sample" in msg:
        return HTTPException(status_code=404, detail=_strip_rpc_prefix(msg))
    if "Unknown environment" in msg or "must be" in msg or "file not found" in msg.lower():
        return HTTPException(status_code=400, detail=_strip_rpc_prefix(msg))
    return HTTPException(status_code=500, detail=_strip_rpc_prefix(msg))


def _strip_rpc_prefix(msg: str) -> str:
    # Client wraps server errors as "Server error: <traceback-ish text>".
    # Surface the meaningful last line.
    msg = msg.replace("Server error: ", "").strip()
    lines = [ln for ln in msg.splitlines() if ln.strip()]
    return lines[-1] if lines else msg


def twin_call(fn: Callable, *args, **kwargs) -> Any:
    """Call into the twin, mapping failures to HTTP errors."""
    try:
        return fn(*args, **kwargs)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — classified below
        raise classify_twin_error(exc) from exc


# ---------------------------------------------------------------------------
# Single-run execution lock
# ---------------------------------------------------------------------------
_run_lock = threading.Lock()
_run_state: Dict[str, Any] = {"active": False, "started_at": None, "label": None}


def try_begin_run(label: str = "script") -> bool:
    with _run_lock:
        if _run_state["active"]:
            return False
        _run_state.update(active=True, started_at=time.time(), label=label)
        return True


def end_run() -> None:
    with _run_lock:
        _run_state.update(active=False, started_at=None, label=None)


def run_status() -> Dict[str, Any]:
    with _run_lock:
        return dict(_run_state)


def require_idle() -> None:
    """Reject mutating operations while a script run owns the instrument."""
    if run_status()["active"]:
        raise HTTPException(
            status_code=409,
            detail="A script run is in progress; microscope controls are "
                   "read-only until it finishes.",
        )


# ---------------------------------------------------------------------------
# Image encoding
# ---------------------------------------------------------------------------

def encode_image_png_b64(arr: np.ndarray) -> Dict[str, Any]:
    """uint16 frame -> 8-bit PNG base64 for the UI (contrast-stretched)."""
    a = np.asarray(arr)
    f = a.astype(np.float32)
    lo, hi = float(f.min()), float(f.max())
    if hi - lo > 1e-6:
        f = (f - lo) / (hi - lo)
    else:
        f = np.zeros_like(f)
    img8 = (f * 255.0).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img8, mode="L").save(buf, format="PNG")
    return {
        "image_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
        "width": int(a.shape[1]),
        "height": int(a.shape[0]),
        "dtype": str(a.dtype),
    }
