"""Orchestration for the dynamical (abTEM) diffraction path.

The abTEM path is DECOUPLED from the twin server (spec §2.7): the pattern is
computed here in the FastAPI process on a reconstruction of the currently
registered sample, not by an RPC. Reconstruction is exact because samples are
seed-deterministic: same name + params => bit-identical structure. Stage tilt
does NOT apply automatically on this path — we read α/β from the twin and
rotate the atoms ourselves.

Concurrency: one compute at a time (single-flight lock -> 409), separate from
the script-runner lock because this path never mutates twin state. Results are
LRU-cached on a fingerprint of everything that affects the pattern, so
toggling kinematical⇄abTEM on an unchanged state is instant.
"""

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

from fastapi import HTTPException

from ..digital_twin import abtem_engine
from ..digital_twin import samples as samples_pkg
from . import twin_session as ts
from .capture import store as capture_store

# Server-side hard maxima on the extraction box: multislice cost grows with
# atom count, and there is no safe way to kill a CPU-bound compute thread —
# so the runtime bound IS the box bound. Requests may shrink these, not grow.
MAX_LATERAL_A = 100.0
MAX_THICKNESS_A = 160.0
MAX_FROZEN_PHONONS = 16

_CACHE_MAX = 8
_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_cache_lock = threading.Lock()

_compute_lock = threading.Lock()

# One engine per beam energy (spec: reuse the engine, don't rebuild per frame).
_engines: Dict[float, Any] = {}


def availability() -> Dict[str, Any]:
    return {"available": abtem_engine.abtem_available(),
            "detail": None if abtem_engine.abtem_available()
            else abtem_engine.ABTEM_MISSING_MSG}


def _require_available() -> None:
    if not abtem_engine.abtem_available():
        raise HTTPException(status_code=501, detail=abtem_engine.ABTEM_MISSING_MSG)


def _get_engine(energy_kev: float):
    key = round(float(energy_kev), 3)
    if key not in _engines:
        _engines[key] = abtem_engine.AbtemDiffraction(energy_kev=key)
    return _engines[key]


def _fingerprint(payload: Dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    return None


def _cache_put(key: str, value: Dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)


def clear_cache() -> None:
    """Test/maintenance hook."""
    with _cache_lock:
        _cache.clear()


def compute_saed(num_frozen_phonons: int = 0,
                 half_width_um: float = 0.02,
                 depth_nm: float = 10.0,
                 max_lateral_A: float = 50.0,
                 max_thickness_A: float = 80.0,
                 max_angle_mrad: float = 60.0) -> Dict[str, Any]:
    """Compute a dynamical SAED pattern for the currently registered sample at
    the current stage tilt and beam voltage. Returns a PNG payload plus the
    state fingerprint actually used (so a client can detect staleness)."""
    _require_available()

    if not (0 <= int(num_frozen_phonons) <= MAX_FROZEN_PHONONS):
        raise HTTPException(status_code=400,
                            detail=f"num_frozen_phonons must be 0..{MAX_FROZEN_PHONONS}")
    max_lateral_A = min(float(max_lateral_A), MAX_LATERAL_A)
    max_thickness_A = min(float(max_thickness_A), MAX_THICKNESS_A)

    # Current twin state: the sample identity + params (for reconstruction),
    # the stage tilt (applied to the atoms), and the beam energy.
    harness = ts.get_harness()
    control = ts.get_control()
    current = ts.twin_call(harness.get_current_sample)
    if not current.get("name"):
        raise HTTPException(
            status_code=409,
            detail="No sample registered. Register a sample before computing "
                   "a dynamical pattern.")
    stage = ts.twin_call(control.get_stage)
    beam = ts.twin_call(control.get_beam)
    a_deg, b_deg = float(stage[3]), float(stage[4])
    energy_kev = float(beam.get("voltage_kV", 200.0))

    state = {
        "sample": current["name"],
        "params": current.get("params") or {},
        "tilt_a_deg": a_deg,
        "tilt_b_deg": b_deg,
        "energy_kev": energy_kev,
        "num_frozen_phonons": int(num_frozen_phonons),
        "half_width_um": float(half_width_um),
        "depth_nm": float(depth_nm),
        "max_lateral_A": max_lateral_A,
        "max_thickness_A": max_thickness_A,
        "max_angle_mrad": float(max_angle_mrad),
    }
    key = _fingerprint(state)
    cached = _cache_get(key)
    if cached is not None:
        return {**cached, "cached": True}

    if not _compute_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="A dynamical (abTEM) computation is already in progress.")
    try:
        # Re-check the cache under the lock (a concurrent request may have
        # just computed the same state while we waited to observe it).
        cached = _cache_get(key)
        if cached is not None:
            return {**cached, "cached": True}

        t0 = time.monotonic()
        engine = _get_engine(energy_kev)
        # Reconstruct the sample locally — bit-identical thanks to seeds.
        sample = samples_pkg.get_sample(current["name"], **state["params"])
        atoms = engine.atoms_from_twin_sample(
            sample,
            half_width_um=state["half_width_um"],
            depth_nm=state["depth_nm"],
            max_lateral_A=max_lateral_A,
            max_thickness_A=max_thickness_A,
        )
        # The abTEM path is decoupled from the server: apply the stage tilt
        # to the atoms ourselves (the kinematical path does this server-side).
        if abs(a_deg) > 1e-9 or abs(b_deg) > 1e-9:
            atoms = abtem_engine.AbtemDiffraction.tilted_atoms(
                atoms, tilt_deg_x=a_deg, tilt_deg_y=b_deg)

        pattern = engine.saed(
            atoms,
            num_frozen_phonons=int(num_frozen_phonons),
            max_angle_mrad=float(max_angle_mrad),
        )
        # Stash the RAW dynamical pattern for "Save 32-bit TIFF" (A4): the
        # quantitative float intensities, tagged so the filename/metadata
        # distinguish it from kinematical frames.
        capture_store.stash(pattern, meta={
            "mode": "DIFF",
            "engine": "abTEM",
            "sample": current["name"],
            "params": state["params"],
            "tilt_a_deg": a_deg,
            "tilt_b_deg": b_deg,
            "voltage_kV": energy_kev,
            "num_frozen_phonons": int(num_frozen_phonons),
        })
        u16 = abtem_engine.AbtemDiffraction.display_u16(pattern)
        result = {
            "success": True,
            "engine": "abtem",
            "image": ts.encode_image_png_b64(u16),
            "state": state,
            "fingerprint": key,
            "n_atoms": int(len(atoms)),
            "compute_seconds": round(time.monotonic() - t0, 2),
        }
        _cache_put(key, result)
        return {**result, "cached": False}
    except HTTPException:
        raise
    except ValueError as exc:  # e.g. no atoms in region / over-cropped box
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — classified like other twin errors
        raise ts.classify_twin_error(exc) from exc
    finally:
        _compute_lock.release()
