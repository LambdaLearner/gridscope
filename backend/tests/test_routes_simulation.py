"""Route tests for the SIMULATION surface (sample registry / registration,
environments, specimen, drift) plus an end-to-end pass against a real
in-process STEMServer to catch stub drift."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import twin_session as ts


class FakeHarness:
    def __init__(self):
        self.loaded = None
        self.environment = "pristine"
        self.reset_called = 0

    def list_samples(self):
        return [{"name": "fcc_single_crystal", "display_name": "FCC crystal",
                 "description": "d", "default_params": {}, "param_schema": {}}]

    def get_current_sample(self):
        return {"name": self.loaded, "params": {}, "crystalline": True}

    def load_sample(self, name, params=None, D=None, H=None, W=None):
        if name == "no_such":
            raise RuntimeError(f"Server error: Unknown sample '{name}'.")
        self.loaded = name
        return {"loaded": name, "shape": [16, 96, 96], "params": params or {}}

    def reset_specimen(self):
        self.reset_called += 1
        return {"reset": True}

    def set_environment(self, name):
        if name == "no_such_env":
            raise RuntimeError(f"Server error: Unknown environment '{name}'.")
        self.environment = name
        return {"environment": name, "config": {}}

    def get_environment(self):
        return {"environment": self.environment, "available": ["pristine"]}

    def get_specimen(self):
        return {"beam_damage_enabled": 0.0}

    def set_specimen(self, **kw):
        return {"beam_damage_enabled": 1.0}

    def get_drift(self):
        return {"enabled": 0.0}

    def set_drift(self, **kw):
        return {"enabled": 1.0}


@pytest.fixture()
def harness():
    return FakeHarness()


@pytest.fixture()
def client(monkeypatch, harness):
    monkeypatch.setattr(ts, "get_harness", lambda: harness)
    ts.end_run()
    return TestClient(app)


class TestRegistry:
    def test_list_samples(self, client):
        r = client.get("/api/simulation/samples")
        assert r.status_code == 200
        assert r.json()["count"] == 1
        assert r.json()["samples"][0]["name"] == "fcc_single_crystal"

    def test_current_sample_unregistered(self, client):
        r = client.get("/api/simulation/sample")
        assert r.json()["registered"] is False


class TestRegistration:
    def test_register_loads_resets_and_sets_environment(self, client, harness):
        r = client.post("/api/simulation/sample/register",
                        json={"name": "fcc_single_crystal",
                              "environment": "pristine"})
        assert r.status_code == 200
        body = r.json()
        assert body["registered"] == "fcc_single_crystal"
        assert body["environment"] == "pristine"
        assert harness.loaded == "fcc_single_crystal"
        assert harness.reset_called == 1, "registration must reset degradation"

    def test_register_without_environment_keeps_current(self, client, harness):
        r = client.post("/api/simulation/sample/register",
                        json={"name": "fcc_single_crystal"})
        assert r.status_code == 200
        assert r.json()["environment"] is None

    def test_register_unknown_sample_is_404(self, client):
        r = client.post("/api/simulation/sample/register", json={"name": "no_such"})
        assert r.status_code == 404
        assert "Unknown sample" in r.json()["detail"]

    def test_register_rejected_during_run(self, client):
        assert ts.try_begin_run("test")
        try:
            r = client.post("/api/simulation/sample/register",
                            json={"name": "fcc_single_crystal"})
            assert r.status_code == 409
        finally:
            ts.end_run()


class TestEnvironment:
    def test_set_environment(self, client, harness):
        r = client.post("/api/simulation/environment", json={"name": "pristine"})
        assert r.status_code == 200
        assert harness.environment == "pristine"

    def test_unknown_environment_is_400(self, client):
        r = client.post("/api/simulation/environment", json={"name": "no_such_env"})
        assert r.status_code == 400
        assert "Unknown environment" in r.json()["detail"]


# ---------------------------------------------------------------------------
# End-to-end: real STEMServer behind the routes (no stub) to catch stub drift.
# The netstring transport is exercised separately in test_transport.py.
# ---------------------------------------------------------------------------
class _DirectControl:
    """Adapter: MicroscopeControlClient interface over an in-process server."""
    host, port = "inproc", 0

    def __init__(self, server):
        self._srv = server

    def __getattr__(self, name):
        return getattr(self._srv, name)

    def acquire_image(self, device, **kw):
        import base64
        import numpy as np
        obj = self._srv.acquire_image(device, **kw)
        raw = base64.b64decode(obj["__ndarray_b64__"])
        return np.frombuffer(raw, dtype=np.dtype(obj["dtype"])).reshape(obj["shape"])


class _DirectHarness:
    def __init__(self, server):
        self._srv = server

    def __getattr__(self, name):
        return getattr(self._srv, name)


@pytest.fixture(scope="module")
def e2e_client():
    from app.digital_twin.server import STEMServer
    srv = STEMServer(D=16, H=96, W=96)
    srv.finish_init()
    control, harness = _DirectControl(srv), _DirectHarness(srv)
    import unittest.mock as mock
    with mock.patch.object(ts, "get_control", lambda: control), \
         mock.patch.object(ts, "get_harness", lambda: harness):
        ts.end_run()
        yield TestClient(app)


class TestEndToEnd:
    def test_full_flow_register_then_image(self, e2e_client):
        # Unregistered: acquire is 409
        r = e2e_client.post("/api/microscope/acquire", json={"device": "haadf"})
        assert r.status_code == 409

        # Registry has all samples
        r = e2e_client.get("/api/simulation/samples")
        assert r.json()["count"] >= 13

        # Register
        r = e2e_client.post("/api/simulation/sample/register",
                            json={"name": "au_dispersed",
                                  "environment": "pristine"})
        assert r.status_code == 200

        # Acquire now works and returns a PNG payload
        r = e2e_client.post("/api/microscope/acquire", json={"device": "haadf"})
        assert r.status_code == 200
        assert r.json()["image"]["width"] == 256

    def test_real_limit_rejection_maps_to_400(self, e2e_client):
        r = e2e_client.post("/api/microscope/stage",
                            json={"position": {"y": -2e-3}, "relative": False})
        assert r.status_code == 400
        assert "safety limits" in r.json()["detail"]
        # nothing moved
        r2 = e2e_client.get("/api/microscope/stage")
        assert r2.json()["y"] == 0.0

    def test_real_unknown_sample_maps_to_404(self, e2e_client):
        r = e2e_client.post("/api/simulation/sample/register",
                            json={"name": "definitely_not_a_sample"})
        assert r.status_code == 404

    def test_file_backed_sample_maps_to_400(self, e2e_client):
        r = e2e_client.post("/api/simulation/sample/register",
                            json={"name": "atomsk_polycrystal"})
        assert r.status_code == 400
        assert "file not found" in r.json()["detail"].lower()
