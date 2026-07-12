"""
control_client.py — the portable instrument-control surface.

EVERY method here has a real-microscope counterpart (stage, beam, mode,
detector settings, magnification, image acquisition, autofocus). A real
deployment replaces this object with a vendor-SDK client exposing the same
operations. This file is embedded verbatim into generated automation scripts,
so it must stay self-contained (stdlib + numpy only).
"""
import socket, json, base64
import numpy as np


# ===========================================================================
# Instrument control  (portable; real instruments expose the same operations)
# ===========================================================================
class MicroscopeControlClient:
    """The instrument-control surface. Replace this object with a vendor-SDK
    client to drive a real microscope; the workflow code above it is unchanged."""

    def __init__(self, host="127.0.0.1", port=9094, timeout=30):
        self.host = host; self.port = port; self.timeout = timeout; self._next_id = 1

    # ---- transport (netstring JSON-RPC) ----
    def _to_netstring(self, obj):
        payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        return f"{len(payload)}:".encode("ascii") + payload + b","

    def _recv_exact(self, sock, n):
        chunks = []; remaining = n
        while remaining > 0:
            chunk = sock.recv(remaining)
            if not chunk: raise ConnectionError("closed while reading")
            chunks.append(chunk); remaining -= len(chunk)
        return b"".join(chunks)

    def _recv_netstring(self, sock):
        length_bytes = b""
        while True:
            c = sock.recv(1)
            if not c: raise ConnectionError("no response")
            if c == b":": break
            length_bytes += c
        length = int(length_bytes.decode("ascii"))
        payload = self._recv_exact(sock, length)
        if self._recv_exact(sock, 1) != b",":
            raise RuntimeError("malformed netstring")
        return json.loads(payload.decode("utf-8"))

    def _decode(self, obj):
        if isinstance(obj, dict) and "__ndarray_b64__" in obj:
            raw = base64.b64decode(obj["__ndarray_b64__"])
            return np.frombuffer(raw, dtype=np.dtype(obj["dtype"])).reshape(obj["shape"])
        return obj

    def _call(self, method, params=None):
        if params is None: params = {}
        msg = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        self._next_id += 1
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(self._to_netstring(msg))
            reply = self._recv_netstring(sock)
        if "error" in reply:
            raise RuntimeError(f"Server error: {reply['error']}")
        return reply.get("result", None)

    # ---- readiness (transport-level; on real hardware this is the connection check) ----
    def is_ready(self): return self._call("is_ready")
    def wait_until_ready(self, timeout=300, poll=1.0):
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = self.is_ready()
            except OSError:
                # Server not listening yet (still booting) — keep waiting.
                time.sleep(poll)
                continue
            if r.get("error"): raise RuntimeError("Server init failed:\n" + r["error"])
            if r.get("ready"): return r
            time.sleep(poll)
        raise TimeoutError(f"not ready within {timeout}s")

    # ---- detector configuration ----
    # Geometry (size, field_of_view_um, dwell_us, binning) maps to real detector
    # controls. A few keys (noise_sigma, dqe, readout_e, use_dose_model) are
    # simulation-only knobs of the twin's noise model -- documented as such.
    def get_detectors(self): return self._call("get_detectors")
    def device_settings(self, device, **kw): return self._call("device_settings", {"device": device, **kw})

    # Magnification is the same quantity as field of view (mag = MAG_K / fov_metres).
    # Setting one updates the other. These mirror a real instrument's mag control.
    def get_magnification(self, device="haadf"): return self._call("get_magnification", {"device": device})
    def set_magnification(self, magnification, device="haadf"):
        return self._call("set_magnification", {"magnification": magnification, "device": device})

    # ---- stage ----
    def get_stage(self): return self._call("get_stage")
    def set_stage(self, sp, relative=True): return self._call("set_stage", {"stage_positions": sp, "relative": relative})

    # Soft travel limits (symmetric +/- per axis; x/y/z metres, a/b degrees).
    # Real instruments expose their soft limits the same way; moves whose target
    # exceeds a limit are rejected outright and the stage does not move.
    def get_stage_limits(self): return self._call("get_stage_limits")

    # ---- beam ----
    def get_beam(self): return self._call("get_beam")
    def set_beam(self, bs, relative=False): return self._call("set_beam", {"beam_settings": bs, "relative": relative})

    # ---- optics / aberrations ----
    def get_optics(self): return self._call("get_optics")
    def set_optics(self, **kw): return self._call("set_optics", kw)

    # ---- imaging vs diffraction mode ----
    def get_mode(self): return self._call("get_mode")
    def set_mode(self, mode="IMG"): return self._call("set_mode", {"mode": mode})

    # ---- diffraction settings ----
    # camera_length_mm / beamstop_radius_px / aperture_um / depth_nm map to real
    # projection + selected-area controls. `use_local_atoms` is a simulation-only
    # toggle (how the twin COMPUTES diffraction) and has no real counterpart.
    def get_diffraction_settings(self): return self._call("get_diffraction_settings")
    def set_diffraction_settings(self, **kw): return self._call("set_diffraction_settings", kw)

    # ---- acquisition resolution windows ----
    # Real STEM scans / cameras offer a small set of fixed acquisition sizes.
    # Higher resolution resolves finer detail at the same FOV but is slower.
    def get_resolution(self, device="haadf"): return self._call("get_resolution", {"device": device})
    def set_resolution(self, resolution_px, device="haadf"):
        return self._call("set_resolution", {"resolution_px": resolution_px, "device": device})

    # ---- acquisition ----
    def acquire_image(self, device, **kw): return self._decode(self._call("acquire_image", {"device": device, **kw}))

    # ---- EELS (single-spot spectrum; probe parked at one position) ----
    # Real instruments expose the same acquisition; the twin returns a
    # physically-structured dummy spectrum (ZLP, plasmon, core-loss edges).
    def acquire_spectrum(self, ev_min=0.0, ev_max=1000.0, n_channels=1024,
                         cx_um=None, cy_um=None):
        p = {"ev_min": ev_min, "ev_max": ev_max, "n_channels": n_channels}
        if cx_um is not None: p["cx_um"] = cx_um
        if cy_um is not None: p["cy_um"] = cy_um
        return self._call("acquire_spectrum", p)

    # ---- autofocus ----
    # A real instrument-side routine; its FAILURE behavior on the twin is driven
    # by the simulation environment (configured in the twin's UI), which is
    # exactly what lets a workflow's failure-handling be tested.
    def autofocus(self, device="haadf", z_range_um=2.0, z_steps=9):
        return self._call("autofocus", {"device": device, "z_range_um": z_range_um, "z_steps": z_steps})

    # ---- full-state snapshot (real instruments expose the same introspection) ----
    def get_microscope_state(self): return self._call("get_microscope_state")

    def close(self): return self._call("close")
