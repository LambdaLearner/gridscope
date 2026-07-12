"""Route tests for the microscope CONTROL surface.

A stubbed twin client pins the HTTP contracts: safety-limit rejections
surface as 400 with the twin's message verbatim, an unreachable twin is 503,
an unregistered sample is 409, and mutations during a script run are 409.
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.digital_twin.server import NO_SAMPLE_MSG
from app.services import twin_session as ts

LIMIT_MSG = ("Stage move rejected by safety limits: x=+2.000 mm exceeds "
             "+/-1.500 mm. Stage did not move.")

STATE = {
    "stage": {"x": 0.0, "y": 0.0, "z": 0.0, "a": 0.0, "b": 0.0},
    "beam": {"x": 0.0, "y": 0.0, "current_pA": 50.0, "voltage_kV": 200.0},
    "vacuum": 1e-6,
    "status": "Idle",
    "holder_type": "DoubleTilt",
    "mode": "IMG",
    "detectors": {"haadf": {"size": 256, "field_of_view_um": 20.0,
                            "magnification": 4720.0}},
    "diffraction": {"camera_length_mm": 800.0},
    "environment": "pristine",
    "sample": {"name": "fcc_single_crystal", "registered": True},
    "stage_limits": {"x": 1.5e-3, "y": 1.5e-3, "z": 1e-3, "a": 30.0, "b": 30.0},
}


class FakeControl:
    host = "127.0.0.1"
    port = 9094

    def __init__(self):
        self.stage = [0.0, 0.0, 0.0, 0.0, 0.0]

    def is_ready(self):
        return {"ready": True, "error": None, "sample": "fcc_single_crystal"}

    def get_microscope_state(self):
        return STATE

    def get_stage_limits(self):
        return STATE["stage_limits"]

    def get_stage(self):
        return list(self.stage)

    def set_stage(self, sp, relative=True):
        target_x = sp.get("x", 0.0)
        if abs(target_x) > 1.5e-3:
            # The twin raises; over RPC this arrives as a RuntimeError string.
            raise RuntimeError(f"Server error: {LIMIT_MSG}")
        for i, k in enumerate(["x", "y", "z", "a", "b"]):
            if k in sp:
                self.stage[i] = sp[k] if not relative else self.stage[i] + sp[k]
        return {"new_stage": list(self.stage), "relative": relative}

    def acquire_image(self, device, **kw):
        return np.zeros((256, 256), dtype=np.uint16)

    def autofocus(self, device="haadf", z_range_um=2.0, z_steps=9):
        return {"converged": False, "reason": "low contrast",
                "best_z_m": 0.0, "best_z_um_relative": 0.0, "scores": []}

    def get_beam(self):
        return STATE["beam"]

    def get_mode(self):
        return {"mode": "IMG"}

    def set_mode(self, mode="IMG"):
        return {"mode": mode}

    def device_settings(self, device, **kw):
        return 1

    def get_resolution(self, device="haadf"):
        return {"resolution_px": 512, "allowed": [512, 1024, 2048]}

    def set_resolution(self, resolution_px, device="haadf"):
        return {"resolution_px": resolution_px, "allowed": [512, 1024, 2048]}

    def acquire_spectrum(self, ev_min=0.0, ev_max=1000.0, n_channels=1024,
                         cx_um=None, cy_um=None):
        return {"energy_ev": [ev_min, ev_max], "intensity": [1.0, 0.5],
                "edges": [{"label": "Fe-L", "onset_ev": 708, "Z": 26}],
                "zlp_ev": 0.0, "plasmon_ev": 17.6, "thickness_nm": 100.0,
                "elements_Z": [26]}


class FakeHarness:
    def get_command_log(self, last_n=50):
        return [{"t": 0.0, "method": "acquire_image", "params": {},
                 "result_preview": "image"}]


class DownControl(FakeControl):
    """Simulates the twin being unreachable."""

    def _down(self, *a, **kw):
        raise ConnectionRefusedError("connection refused")

    is_ready = _down
    get_microscope_state = _down
    get_stage = _down
    set_stage = _down
    get_stage_limits = _down
    acquire_image = _down


class NoSampleControl(FakeControl):
    def acquire_image(self, device, **kw):
        raise RuntimeError(f"Server error: {NO_SAMPLE_MSG}")

    def autofocus(self, **kw):
        raise RuntimeError(f"Server error: {NO_SAMPLE_MSG}")

    def acquire_spectrum(self, **kw):
        raise RuntimeError(f"Server error: {NO_SAMPLE_MSG}")


@pytest.fixture()
def client(monkeypatch):
    fake_control = FakeControl()
    monkeypatch.setattr(ts, "get_control", lambda: fake_control)
    monkeypatch.setattr(ts, "get_harness", lambda: FakeHarness())
    ts.end_run()
    return TestClient(app)


@pytest.fixture()
def down_client(monkeypatch):
    monkeypatch.setattr(ts, "get_control", lambda: DownControl())
    monkeypatch.setattr(ts, "get_harness", lambda: FakeHarness())
    ts.end_run()
    return TestClient(app)


class TestStatusAndSession:
    def test_status_connected(self, client):
        r = client.get("/api/microscope/status")
        assert r.status_code == 200
        assert r.json()["connected"] is True
        assert r.json()["sample"] == "fcc_single_crystal"

    def test_status_never_raises_when_down(self, down_client):
        r = down_client.get("/api/microscope/status")
        assert r.status_code == 200
        assert r.json()["connected"] is False

    def test_session_snapshot_shape(self, client):
        r = client.get("/api/microscope/session")
        body = r.json()
        assert body["connected"] is True
        assert body["sample"]["registered"] is True
        assert body["run"]["active"] is False
        assert len(body["log"]) == 1
        assert body["state"]["stage_limits"]["x"] == 1.5e-3

    def test_session_degrades_when_down(self, down_client):
        r = down_client.get("/api/microscope/session")
        assert r.status_code == 200
        assert r.json()["connected"] is False


class TestErrorClassification:
    def test_safety_limit_rejection_is_400_with_message(self, client):
        r = client.post("/api/microscope/stage",
                        json={"position": {"x": 2e-3}, "relative": False})
        assert r.status_code == 400
        assert r.json()["detail"] == LIMIT_MSG

    def test_twin_down_is_503(self, down_client):
        r = down_client.post("/api/microscope/stage",
                             json={"position": {"x": 1e-6}, "relative": True})
        assert r.status_code == 503
        assert "unreachable" in r.json()["detail"]

    def test_no_sample_is_409(self, monkeypatch):
        monkeypatch.setattr(ts, "get_control", lambda: NoSampleControl())
        monkeypatch.setattr(ts, "get_harness", lambda: FakeHarness())
        ts.end_run()
        client = TestClient(app)
        r = client.post("/api/microscope/acquire", json={"device": "haadf"})
        assert r.status_code == 409
        assert "No sample registered" in r.json()["detail"]


class TestStageAndLimits:
    def test_limits_endpoint(self, client):
        r = client.get("/api/microscope/limits")
        assert r.status_code == 200
        assert r.json()["limits"]["z"] == 1e-3

    def test_valid_move_returns_new_position(self, client):
        r = client.post("/api/microscope/stage",
                        json={"position": {"x": 5e-6}, "relative": False})
        assert r.status_code == 200
        assert r.json()["new_position"]["x_um"] == pytest.approx(5.0)


class TestAcquireAndAutofocus:
    def test_acquire_returns_png_and_context(self, client):
        r = client.post("/api/microscope/acquire", json={"device": "haadf"})
        assert r.status_code == 200
        body = r.json()
        assert body["image"]["width"] == 256
        assert body["image"]["dtype"] == "uint16"
        assert len(body["image"]["image_base64"]) > 100
        assert body["sample"]["registered"] is True

    def test_autofocus_nonconvergence_is_a_result_not_an_error(self, client):
        r = client.post("/api/microscope/autofocus", json={})
        assert r.status_code == 200
        assert r.json()["result"]["converged"] is False


class TestResolutionAndSpectrum:
    def test_get_resolution(self, client):
        r = client.get("/api/microscope/resolution")
        assert r.status_code == 200
        assert r.json()["resolution_px"] == 512
        assert r.json()["allowed"] == [512, 1024, 2048]

    def test_set_resolution_valid(self, client):
        r = client.post("/api/microscope/resolution", json={"resolution_px": 1024})
        assert r.status_code == 200
        assert r.json()["resolution_px"] == 1024

    @pytest.mark.parametrize("bad", [256, 768, 4096, 0])
    def test_set_resolution_invalid_is_422(self, client, bad):
        r = client.post("/api/microscope/resolution", json={"resolution_px": bad})
        assert r.status_code == 422

    def test_acquire_spectrum(self, client):
        r = client.post("/api/microscope/spectrum",
                        json={"ev_min": 0.0, "ev_max": 1000.0, "n_channels": 1024})
        assert r.status_code == 200
        body = r.json()
        assert body["edges"][0]["label"] == "Fe-L"
        assert body["elements_Z"] == [26]

    @pytest.mark.parametrize("payload", [
        {"ev_min": 500.0, "ev_max": 500.0},     # empty range
        {"ev_min": 800.0, "ev_max": 100.0},     # inverted range
        {"n_channels": 8},                       # below floor
        {"n_channels": 100000},                  # above cap
        {"ev_max": 9000.0},                      # beyond detector range
    ])
    def test_spectrum_validation_is_422(self, client, payload):
        r = client.post("/api/microscope/spectrum", json=payload)
        assert r.status_code == 422

    def test_spectrum_without_sample_is_409(self, monkeypatch):
        monkeypatch.setattr(ts, "get_control", lambda: NoSampleControl())
        monkeypatch.setattr(ts, "get_harness", lambda: FakeHarness())
        ts.end_run()
        client = TestClient(app)
        r = client.post("/api/microscope/spectrum", json={})
        assert r.status_code == 409
        assert "No sample registered" in r.json()["detail"]


class TestRunLock:
    def test_mutations_rejected_while_run_active(self, client):
        assert ts.try_begin_run("test")
        try:
            for path, payload in [
                ("/api/microscope/stage", {"position": {"x": 1e-6}, "relative": True}),
                ("/api/microscope/acquire", {"device": "haadf"}),
                ("/api/microscope/mode", {"mode": "DIFF"}),
                ("/api/microscope/resolution", {"resolution_px": 1024}),
                ("/api/microscope/spectrum", {}),
            ]:
                r = client.post(path, json=payload)
                assert r.status_code == 409, path
                assert "read-only" in r.json()["detail"]
        finally:
            ts.end_run()

    def test_reads_allowed_while_run_active(self, client):
        assert ts.try_begin_run("test")
        try:
            assert client.get("/api/microscope/session").status_code == 200
            assert client.get("/api/microscope/limits").status_code == 200
        finally:
            ts.end_run()
