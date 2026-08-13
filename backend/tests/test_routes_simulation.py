"""Route tests for the SIMULATION surface (sample registry / registration,
environments, specimen, drift) plus an end-to-end pass against a real
in-process STEMServer to catch stub drift."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.digital_twin.server import NO_SAMPLE_MSG
from app.services import twin_session as ts


class FakeHarness:
    def __init__(self):
        self.loaded = None
        self.environment = "pristine"
        self.reset_called = 0
        self.thickness = {"total_nm": 100.0, "working_nm": 100.0,
                          "z_start_nm": 0.0, "seed": 0}

    def list_samples(self):
        return [{"name": "fcc_single_crystal", "display_name": "FCC crystal",
                 "description": "d", "default_params": {}, "param_schema": {}}]

    def get_current_sample(self):
        return {"name": self.loaded, "params": {}, "crystalline": True}

    def load_sample(self, name, params=None, D=None, H=None, W=None,
                    thickness_nm=None, thickness_seed=None):
        if name == "no_such":
            raise RuntimeError(f"Server error: Unknown sample '{name}'.")
        self.loaded = name
        if thickness_nm is not None:
            self.thickness["working_nm"] = float(thickness_nm)
        if thickness_seed is not None:
            self.thickness["seed"] = int(thickness_seed)
        return {"loaded": name, "shape": [16, 96, 96], "params": params or {},
                "thickness": dict(self.thickness)}

    def get_thickness(self):
        return dict(self.thickness)

    def set_thickness(self, thickness_nm=None, thickness_seed=None):
        if self.loaded is None:
            raise RuntimeError(f"Server error: {NO_SAMPLE_MSG}")
        if thickness_nm is not None:
            self.thickness["working_nm"] = float(thickness_nm)
        if thickness_seed is not None:
            self.thickness["seed"] = int(thickness_seed)
        return dict(self.thickness)

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


class TestThicknessRoutes:
    def test_get_thickness(self, client):
        r = client.get("/api/simulation/thickness")
        assert r.status_code == 200
        assert r.json()["total_nm"] == 100.0

    def test_set_thickness(self, client, harness):
        harness.loaded = "fcc_single_crystal"
        r = client.post("/api/simulation/thickness",
                        json={"thickness_nm": 30.0, "thickness_seed": 7})
        assert r.status_code == 200
        assert r.json()["working_nm"] == 30.0
        assert r.json()["seed"] == 7

    def test_set_thickness_without_sample_is_409(self, client):
        r = client.post("/api/simulation/thickness", json={"thickness_nm": 30.0})
        assert r.status_code == 409
        assert "No sample registered" in r.json()["detail"]

    @pytest.mark.parametrize("payload", [
        {"thickness_nm": 0.0},          # must be > 0
        {"thickness_nm": 1500.0},       # above cap
        {"thickness_seed": -1},         # negative seed
        {"thickness_seed": 2**31},      # above int32
    ])
    def test_thickness_validation_is_422(self, client, harness, payload):
        harness.loaded = "fcc_single_crystal"
        r = client.post("/api/simulation/thickness", json=payload)
        assert r.status_code == 422

    def test_register_passes_thickness_through(self, client, harness):
        r = client.post("/api/simulation/sample/register",
                        json={"name": "fcc_single_crystal",
                              "thickness_nm": 40.0, "thickness_seed": 5})
        assert r.status_code == 200
        assert r.json()["thickness"]["working_nm"] == 40.0
        assert harness.thickness["seed"] == 5


class TestVolumeCaps:
    """The caps protect against direct API calls / generated scripts, not just
    UI widget ranges — a huge volume is a twin-process OOM."""

    @pytest.mark.parametrize("payload", [
        {"name": "fcc_single_crystal", "D": 200},              # depth over cap
        {"name": "fcc_single_crystal", "H": 2048, "W": 2048},  # in-plane over cap
        {"name": "fcc_single_crystal", "H": 256, "W": 512},    # non-square
        {"name": "polycrystal_grains", "D": 8},                # needs D >= 12
        {"name": "dislocation_crystal", "D": 8},               # needs D >= 12
        {"name": "fcc_single_crystal", "thickness_nm": -5.0},
    ])
    def test_bad_register_payloads_are_422(self, client, payload):
        r = client.post("/api/simulation/sample/register", json=payload)
        assert r.status_code == 422

    def test_valid_volume_accepted(self, client):
        r = client.post("/api/simulation/sample/register",
                        json={"name": "polycrystal_grains", "D": 16,
                              "H": 96, "W": 96})
        assert r.status_code == 200


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
        assert r.json()["image"]["width"] == 1024

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
        # The DEFAULT path now resolves to the shipped example, so use an
        # explicit bogus path to exercise the clear-failure mapping.
        r = e2e_client.post("/api/simulation/sample/register",
                            json={"name": "atomsk_polycrystal",
                                  "params": {"file_path": "no/such/file.xyz"}})
        assert r.status_code == 400
        assert "file not found" in r.json()["detail"].lower()

    def test_file_backed_sample_default_registers(self, e2e_client):
        r = e2e_client.post("/api/simulation/sample/register",
                            json={"name": "atomsk_polycrystal"})
        assert r.status_code == 200

    def test_thickness_resolution_and_spectrum_flow(self, e2e_client):
        # Register with an explicit working thickness + seed
        r = e2e_client.post("/api/simulation/sample/register",
                            json={"name": "fcc_single_crystal",
                                  "thickness_nm": 30.0, "thickness_seed": 7})
        assert r.status_code == 200
        assert r.json()["thickness"]["working_nm"] == pytest.approx(30.0)

        # Re-pick thickness without reloading
        r = e2e_client.post("/api/simulation/thickness",
                            json={"thickness_nm": 60.0, "thickness_seed": 2})
        assert r.status_code == 200
        z1 = r.json()["z_start_nm"]
        # Same seed reproduces the same z-window
        r = e2e_client.post("/api/simulation/thickness",
                            json={"thickness_nm": 60.0, "thickness_seed": 2})
        assert r.json()["z_start_nm"] == pytest.approx(z1)

        # Resolution windows
        r = e2e_client.get("/api/microscope/resolution")
        assert r.json()["allowed"] == [1024, 2048, 4096]
        r = e2e_client.post("/api/microscope/resolution",
                            json={"resolution_px": 2048})
        assert r.status_code == 200
        r = e2e_client.post("/api/microscope/resolution",
                            json={"resolution_px": 768})
        assert r.status_code == 422  # not a legal window
        e2e_client.post("/api/microscope/resolution", json={"resolution_px": 1024})

        # EELS spectrum shows the Fe-L edge for the Fe crystal
        r = e2e_client.post("/api/microscope/spectrum",
                            json={"ev_min": 0.0, "ev_max": 1000.0,
                                  "n_channels": 256})
        assert r.status_code == 200
        body = r.json()
        assert len(body["energy_ev"]) == 256
        assert "Fe-L" in [e["label"] for e in body["edges"]]


class TestDriftSpecimenBounds:
    """Drift/specimen limits are enforced at the HTTP boundary (7A): scripts
    hit this surface too, so out-of-range values must 422, not render garbage.
    Bounds come from app.digital_twin.limits — one Python source of truth."""

    def test_drift_within_bounds_ok(self, client, harness):
        r = client.post("/api/simulation/drift",
                        json={"enabled": True, "vx_nm_per_s": 50.0,
                              "vy_nm_per_s": 0.0, "line_jitter_nm": 5.0})
        assert r.status_code == 200

    @pytest.mark.parametrize("payload", [
        {"vx_nm_per_s": 50.1},
        {"vy_nm_per_s": 1e6},
        {"vx_nm_per_s": -0.1},
        {"line_jitter_nm": 5.1},
        {"vx_px_per_s": 51.0},
        {"line_jitter_px": 6.0},
    ])
    def test_drift_out_of_bounds_is_422(self, client, payload):
        r = client.post("/api/simulation/drift", json=payload)
        assert r.status_code == 422

    def test_specimen_within_bounds_ok(self, client):
        r = client.post("/api/simulation/specimen",
                        json={"contamination_enabled": True,
                              "contamination_rate": 20.0,
                              "damage_rate": 10.0,
                              "damage_dose_threshold": 3e4})
        assert r.status_code == 200

    @pytest.mark.parametrize("payload", [
        {"contamination_rate": 20.1},
        {"contamination_rate": -1.0},
        {"damage_rate": 10.5},
        {"damage_dose_threshold": 0.0},
        {"damage_dose_threshold": 1e9},
    ])
    def test_specimen_out_of_bounds_is_422(self, client, payload):
        r = client.post("/api/simulation/specimen", json=payload)
        assert r.status_code == 422

    def test_bounds_match_limits_module(self):
        """The route bounds must track digital_twin.limits exactly."""
        from app.digital_twin.limits import (
            CONTAMINATION_MAX_RATE, DRIFT_MAX_NM_PER_S)
        from app.routes.simulation import DriftSettings, SpecimenSettings

        f = DriftSettings.model_fields["vx_nm_per_s"]
        assert any(getattr(m, "le", None) == DRIFT_MAX_NM_PER_S
                   for m in f.metadata)
        f = SpecimenSettings.model_fields["contamination_rate"]
        assert any(getattr(m, "le", None) == CONTAMINATION_MAX_RATE
                   for m in f.metadata)
