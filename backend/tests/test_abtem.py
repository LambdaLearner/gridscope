"""Two-tier tests for the dynamical (abTEM) diffraction path.

Tier 1 (always runs): the service/route wiring with the engine stubbed —
availability gating (501), the single-flight lock (409), sample gating (409),
boundary validation (422), stage-tilt fingerprinting, and the LRU cache.

Tier 2 (@pytest.mark.slow, auto-skipped when abtem isn't installed): one real
multislice SAED smoke test, so abtem version churn is caught on demand.
"""

import threading

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.digital_twin import abtem_engine
from app.main import app
from app.services import abtem_service
from app.services import twin_session as ts


# ---------------------------------------------------------------------------
# Tier 1 — stubbed engine
# ---------------------------------------------------------------------------

class FakeAtoms(list):
    """len() is all the service needs from the atoms object."""


class FakeEngine:
    def __init__(self):
        self.saed_calls = 0

    def atoms_from_twin_sample(self, sample, **kw):
        return FakeAtoms(range(10))

    def saed(self, atoms, **kw):
        self.saed_calls += 1
        # A tiny pattern with a bright "direct beam" and one Bragg spot.
        p = np.zeros((32, 32), dtype=np.float32)
        p[16, 16] = 100.0
        p[16, 24] = 1.0
        return p


class FakeControl:
    def __init__(self, tilt_a=0.0, tilt_b=0.0, voltage=200.0):
        self.stage = [0.0, 0.0, 0.0, tilt_a, tilt_b]
        self.voltage = voltage

    def get_stage(self):
        return list(self.stage)

    def get_beam(self):
        return {"x": 0.0, "y": 0.0, "current_pA": 50.0,
                "voltage_kV": self.voltage}


class FakeHarness:
    def __init__(self, name="fcc_single_crystal", params=None):
        self.name = name
        self.params = params or {}

    def get_current_sample(self):
        return {"name": self.name, "params": self.params, "crystalline": True}


@pytest.fixture()
def fake_engine():
    return FakeEngine()


@pytest.fixture()
def abtem_client(monkeypatch, fake_engine):
    """Client with abtem 'available', the engine stubbed, and a fresh cache."""
    monkeypatch.setattr(abtem_engine, "abtem_available", lambda: True)
    monkeypatch.setattr(abtem_service, "_get_engine", lambda energy: fake_engine)
    # Sample reconstruction: return a lightweight object, no volume generation.
    monkeypatch.setattr(abtem_service.samples_pkg, "get_sample",
                        lambda name, **params: object())
    # Tilt application must not require ase.
    monkeypatch.setattr(abtem_engine.AbtemDiffraction, "tilted_atoms",
                        staticmethod(lambda atoms, tilt_deg_x=0.0, tilt_deg_y=0.0: atoms))
    control = FakeControl()
    harness = FakeHarness()
    monkeypatch.setattr(ts, "get_control", lambda: control)
    monkeypatch.setattr(ts, "get_harness", lambda: harness)
    abtem_service.clear_cache()
    ts.end_run()
    client = TestClient(app)
    client._control = control       # handles for tests
    client._harness = harness
    return client


class TestAvailabilityGate:
    def test_availability_endpoint_reports_missing(self, monkeypatch):
        monkeypatch.setattr(abtem_engine, "abtem_available", lambda: False)
        r = TestClient(app).get("/api/simulation/diffraction/abtem/availability")
        assert r.status_code == 200
        assert r.json()["available"] is False
        assert "abtem" in r.json()["detail"]

    def test_compute_without_abtem_is_501(self, monkeypatch):
        monkeypatch.setattr(abtem_engine, "abtem_available", lambda: False)
        monkeypatch.setattr(ts, "get_control", lambda: FakeControl())
        monkeypatch.setattr(ts, "get_harness", lambda: FakeHarness())
        r = TestClient(app).post("/api/simulation/diffraction/abtem", json={})
        assert r.status_code == 501

    def test_availability_endpoint_reports_present(self, abtem_client):
        r = abtem_client.get("/api/simulation/diffraction/abtem/availability")
        assert r.json() == {"available": True, "detail": None}


class TestComputeWiring:
    def test_compute_returns_png_and_fingerprint(self, abtem_client, fake_engine):
        r = abtem_client.post("/api/simulation/diffraction/abtem", json={})
        assert r.status_code == 200
        body = r.json()
        assert body["engine"] == "abtem"
        assert body["cached"] is False
        assert body["n_atoms"] == 10
        assert len(body["image"]["image_base64"]) > 50
        assert body["state"]["sample"] == "fcc_single_crystal"
        assert body["state"]["tilt_a_deg"] == 0.0
        assert body["fingerprint"]
        assert fake_engine.saed_calls == 1

    def test_no_sample_is_409(self, abtem_client):
        abtem_client._harness.name = None
        r = abtem_client.post("/api/simulation/diffraction/abtem", json={})
        assert r.status_code == 409
        assert "No sample registered" in r.json()["detail"]

    def test_busy_is_409(self, abtem_client):
        assert abtem_service._compute_lock.acquire(blocking=False)
        try:
            r = abtem_client.post("/api/simulation/diffraction/abtem", json={})
            assert r.status_code == 409
            assert "in progress" in r.json()["detail"]
        finally:
            abtem_service._compute_lock.release()

    @pytest.mark.parametrize("payload", [
        {"num_frozen_phonons": 17},         # above cap
        {"num_frozen_phonons": -1},
        {"max_lateral_A": 500.0},           # beyond server-side maxima
        {"max_thickness_A": 500.0},
        {"max_angle_mrad": 5.0},            # below floor
        {"depth_nm": 0.0},
    ])
    def test_boundary_validation_is_422(self, abtem_client, payload):
        r = abtem_client.post("/api/simulation/diffraction/abtem", json=payload)
        assert r.status_code == 422


class TestCache:
    def test_identical_state_is_cached(self, abtem_client, fake_engine):
        r1 = abtem_client.post("/api/simulation/diffraction/abtem", json={})
        r2 = abtem_client.post("/api/simulation/diffraction/abtem", json={})
        assert r1.json()["cached"] is False
        assert r2.json()["cached"] is True
        assert r2.json()["fingerprint"] == r1.json()["fingerprint"]
        assert fake_engine.saed_calls == 1

    def test_tilt_change_invalidates(self, abtem_client, fake_engine):
        r1 = abtem_client.post("/api/simulation/diffraction/abtem", json={})
        abtem_client._control.stage[3] = 5.0   # tilt alpha
        r2 = abtem_client.post("/api/simulation/diffraction/abtem", json={})
        assert r2.json()["cached"] is False
        assert r2.json()["fingerprint"] != r1.json()["fingerprint"]
        assert r2.json()["state"]["tilt_a_deg"] == 5.0
        assert fake_engine.saed_calls == 2

    def test_phonon_change_invalidates(self, abtem_client, fake_engine):
        abtem_client.post("/api/simulation/diffraction/abtem", json={})
        r = abtem_client.post("/api/simulation/diffraction/abtem",
                              json={"num_frozen_phonons": 4})
        assert r.json()["cached"] is False
        assert fake_engine.saed_calls == 2

    def test_sample_params_change_invalidates(self, abtem_client, fake_engine):
        abtem_client.post("/api/simulation/diffraction/abtem", json={})
        abtem_client._harness.params = {"seed": 99}
        r = abtem_client.post("/api/simulation/diffraction/abtem", json={})
        assert r.json()["cached"] is False
        assert fake_engine.saed_calls == 2

    def test_cache_evicts_beyond_capacity(self, abtem_client, fake_engine):
        for i in range(abtem_service._CACHE_MAX + 2):
            abtem_client._control.stage[3] = float(i)
            abtem_client.post("/api/simulation/diffraction/abtem", json={})
        assert len(abtem_service._cache) == abtem_service._CACHE_MAX


class TestDisplayTransform:
    def test_display_u16_suppresses_direct_beam(self):
        p = np.zeros((32, 32), dtype=np.float32)
        p[16, 16] = 100.0     # direct beam, 100x brighter
        p[16, 24] = 1.0       # Bragg spot
        out = abtem_engine.AbtemDiffraction.display_u16(p, beamstop_radius=3)
        assert out.dtype == np.uint16
        # The Bragg spot must render at (or near) full scale, not 1% of it.
        assert out[16, 24] == 65535


# ---------------------------------------------------------------------------
# Tier 2 — real abTEM (skipped unless installed; run with -m slow)
# ---------------------------------------------------------------------------

requires_abtem = pytest.mark.skipif(
    not abtem_engine.abtem_available(), reason="abtem/ase not installed")


@pytest.mark.slow
@requires_abtem
class TestRealAbtem:
    def test_saed_on_tiny_crystal_produces_bragg_spots(self):
        eng = abtem_engine.AbtemDiffraction(energy_kev=200.0,
                                            potential_sampling=0.15)
        atoms = eng.build_crystal("Au", "fcc", 4.05, size=(4, 4, 6))
        dp = eng.saed(atoms, max_angle_mrad=40.0)
        assert dp.ndim == 2
        assert np.isfinite(dp).all()
        assert dp.max() > 0
        # Beyond the direct beam there must be real diffracted intensity.
        disp = abtem_engine.AbtemDiffraction.display_u16(dp, beamstop_radius=4)
        cy, cx = np.unravel_index(np.argmax(dp), dp.shape)
        Y, X = np.mgrid[0:dp.shape[0], 0:dp.shape[1]]
        outside = np.hypot(Y - cy, X - cx) > 6
        assert disp[outside].max() > 30000, "no visible Bragg spots"

    def test_twin_sample_reconstruction_roundtrip(self):
        from app.digital_twin import samples
        samples.discover()
        eng = abtem_engine.AbtemDiffraction(energy_kev=200.0,
                                            potential_sampling=0.15)
        sample = samples.get_sample("fcc_single_crystal")
        atoms = eng.atoms_from_twin_sample(sample, max_lateral_A=30.0,
                                           max_thickness_A=40.0,
                                           generate_volume=False)
        assert len(atoms) > 10
        dp = eng.saed(atoms, max_angle_mrad=40.0)
        assert dp.max() > 0
