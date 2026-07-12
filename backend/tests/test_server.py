"""Unit tests for the v6 STEMServer — direct class-level tests (no sockets).

Covers the safety-critical core: stage soft limits (boundary-exact cases per
axis), the sample registration gate, the full sample registry, simulation
environments, magnification/FOV coupling, autofocus convergence reporting,
and specimen-volume release across registrations.
"""

import gc
import weakref

import numpy as np
import pytest

from app.digital_twin import samples
from app.digital_twin.server import NO_SAMPLE_MSG, STEMServer

# Small volume for speed. D=16 satisfies every sample's minimum depth
# (polycrystal_grains/dislocation_crystal stamp a 12-slice band around D/2).
D, H, W = 16, 96, 96

# atomsk_polycrystal requires an uploaded structure file; it registers in the
# registry but cannot load without one.
FILE_BACKED_SAMPLES = {"atomsk_polycrystal"}


@pytest.fixture(scope="module")
def server():
    srv = STEMServer(D=D, H=H, W=W)
    srv.finish_init()
    srv.load_sample("fcc_single_crystal", D=D, H=H, W=W)
    return srv


@pytest.fixture()
def fresh_server():
    srv = STEMServer(D=D, H=H, W=W)
    srv.finish_init()
    return srv


# ---------------------------------------------------------------------------
# Registration gate
# ---------------------------------------------------------------------------
class TestRegistrationGate:
    def test_server_ready_without_sample(self, fresh_server):
        r = fresh_server.is_ready()
        assert r["ready"] is True
        assert r["sample"] is None

    def test_acquire_without_sample_raises(self, fresh_server):
        with pytest.raises(RuntimeError, match="No sample registered"):
            fresh_server.acquire_image("haadf")

    def test_autofocus_without_sample_raises(self, fresh_server):
        with pytest.raises(RuntimeError, match="No sample registered"):
            fresh_server.autofocus("haadf")

    def test_no_sample_message_is_the_shared_constant(self, fresh_server):
        with pytest.raises(RuntimeError) as exc:
            fresh_server.acquire_image("haadf")
        assert NO_SAMPLE_MSG in str(exc.value)

    def test_stage_moves_allowed_without_sample(self, fresh_server):
        # A real instrument lets you drive the stage with no specimen inserted.
        r = fresh_server.set_stage({"x": 1e-6}, relative=False)
        assert r["new_stage"][0] == pytest.approx(1e-6)

    def test_state_reports_unregistered(self, fresh_server):
        state = fresh_server.get_microscope_state()
        assert state["sample"]["registered"] is False
        assert state["sample"]["name"] is None


# ---------------------------------------------------------------------------
# Sample registry
# ---------------------------------------------------------------------------
class TestSampleRegistry:
    def test_registry_has_at_least_13_samples(self, server):
        names = [s["name"] for s in server.list_samples()]
        assert len(names) >= 13
        assert len(names) == len(set(names)), "duplicate sample names"

    def test_registry_entries_have_metadata(self, server):
        for s in server.list_samples():
            assert s["name"]
            assert s["display_name"]
            assert s["description"]
            assert isinstance(s["default_params"], dict)

    @pytest.mark.parametrize(
        "name",
        [s["name"] for s in samples.list_samples() if s["name"] not in FILE_BACKED_SAMPLES],
    )
    def test_every_sample_loads_and_images(self, fresh_server, name):
        r = fresh_server.load_sample(name, D=D, H=H, W=W)
        assert r["loaded"] == name
        img = fresh_server.acquire_image("haadf")
        assert img["shape"] == (256, 256)
        assert img["dtype"] == "uint16"

    @pytest.mark.parametrize(
        "name",
        [s["name"] for s in samples.list_samples() if s["name"] not in FILE_BACKED_SAMPLES],
    )
    def test_every_sample_produces_diffraction(self, fresh_server, name):
        fresh_server.load_sample(name, D=D, H=H, W=W)
        fresh_server.set_mode("DIFF")
        img = fresh_server.acquire_image("haadf")
        assert img["shape"] == (256, 256)

    def test_unknown_sample_raises(self, server):
        with pytest.raises(KeyError, match="Unknown sample"):
            server.load_sample("no_such_sample", D=D, H=H, W=W)

    def test_file_backed_sample_fails_clearly_without_file(self, fresh_server):
        with pytest.raises(Exception, match="file not found"):
            fresh_server.load_sample("atomsk_polycrystal", D=D, H=H, W=W)

    def test_failed_load_keeps_previous_sample(self, server):
        server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        with pytest.raises(KeyError):
            server.load_sample("no_such_sample", D=D, H=H, W=W)
        assert server.get_current_sample()["name"] == "fcc_single_crystal"
        # still imageable
        assert server.acquire_image("haadf") is not None

    def test_get_current_sample_reports_params(self, server):
        server.load_sample("au_dispersed", D=D, H=H, W=W)
        cur = server.get_current_sample()
        assert cur["name"] == "au_dispersed"
        assert isinstance(cur["params"], dict)


# ---------------------------------------------------------------------------
# Stage safety limits (boundary-exact)
# ---------------------------------------------------------------------------
class TestStageLimits:
    EPS = 1e-9

    def setup_method(self):
        pass

    @pytest.fixture(autouse=True)
    def _reset_stage(self, server):
        server.set_stage({"x": 0, "y": 0, "z": 0, "a": 0, "b": 0}, relative=False)
        yield

    def test_limits_queryable(self, server):
        limits = server.get_stage_limits()
        assert limits == {"x": 1.5e-3, "y": 1.5e-3, "z": 1.0e-3, "a": 30.0, "b": 30.0}

    @pytest.mark.parametrize("axis,limit", [
        ("x", 1.5e-3), ("y", 1.5e-3), ("z", 1.0e-3), ("a", 30.0), ("b", 30.0),
    ])
    def test_move_exactly_at_limit_accepted(self, server, axis, limit):
        r = server.set_stage({axis: limit}, relative=False)
        keys = ["x", "y", "z", "a", "b"]
        assert r["new_stage"][keys.index(axis)] == pytest.approx(limit)

    @pytest.mark.parametrize("axis,limit", [
        ("x", 1.5e-3), ("y", 1.5e-3), ("z", 1.0e-3), ("a", 30.0), ("b", 30.0),
    ])
    def test_move_just_over_limit_rejected(self, server, axis, limit):
        with pytest.raises(ValueError, match="rejected by safety limits"):
            server.set_stage({axis: limit * 1.001}, relative=False)

    @pytest.mark.parametrize("axis,limit", [
        ("x", 1.5e-3), ("y", 1.5e-3), ("z", 1.0e-3), ("a", 30.0), ("b", 30.0),
    ])
    def test_negative_limit_symmetric(self, server, axis, limit):
        server.set_stage({axis: -limit}, relative=False)  # accepted
        with pytest.raises(ValueError):
            server.set_stage({axis: -limit * 1.001}, relative=False)

    def test_relative_move_checked_against_target(self, server):
        # Each relative step is fine, but the TARGET crosses the limit.
        server.set_stage({"x": 1.4e-3}, relative=False)
        with pytest.raises(ValueError, match="rejected by safety limits"):
            server.set_stage({"x": 0.2e-3}, relative=True)

    def test_rejected_move_does_not_move_any_axis(self, server):
        server.set_stage({"x": 1e-6, "y": 2e-6}, relative=False)
        before = server.get_stage()
        # y violates; x alone would be fine — whole move must be rejected.
        with pytest.raises(ValueError):
            server.set_stage({"x": 5e-6, "y": 2e-3}, relative=False)
        assert server.get_stage() == before

    def test_rejection_message_names_axis_and_limit(self, server):
        with pytest.raises(ValueError) as exc:
            server.set_stage({"z": 2e-3}, relative=False)
        msg = str(exc.value)
        assert "z=" in msg and "1.000 mm" in msg and "did not move" in msg

    def test_list_input_supported(self, server):
        r = server.set_stage([1e-6, 2e-6, 0, 0, 0], relative=False)
        assert r["new_stage"][0] == pytest.approx(1e-6)

    def test_bad_input_type_raises(self, server):
        with pytest.raises(ValueError, match="dict or list"):
            server.set_stage("nonsense")


# ---------------------------------------------------------------------------
# Magnification <-> field of view
# ---------------------------------------------------------------------------
class TestMagnificationFov:
    def test_calibration_point(self, server):
        # 57 kx corresponds to a 1.6564523008 um field of view.
        r = server.set_magnification(57000.0)
        assert r["field_of_view_um"] == pytest.approx(1.6564523008, rel=1e-9)

    def test_roundtrip(self, server):
        server.set_magnification(30000.0)
        r = server.get_magnification()
        assert r["magnification"] == pytest.approx(30000.0, rel=1e-9)

    def test_setting_fov_updates_magnification(self, server):
        server.device_settings("haadf", field_of_view_um=20.0)
        r = server.get_magnification()
        expected = 0.0944177811456 / 20e-6
        assert r["magnification"] == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------
class TestEnvironments:
    ALL = ["pristine", "beam_sensitive", "contaminating", "thick_drifting", "low_dose"]

    @pytest.mark.parametrize("name", ALL)
    def test_environment_applies(self, server, name):
        r = server.set_environment(name)
        assert r["environment"] == name
        assert server.get_environment()["environment"] == name

    def test_available_list_matches(self, server):
        assert server.get_environment()["available"] == self.ALL

    def test_unknown_environment_raises(self, server):
        with pytest.raises(ValueError, match="Unknown environment"):
            server.set_environment("perfect_vacuum")

    def test_environment_resets_specimen_history(self, server):
        server.set_environment("beam_sensitive")
        for _ in range(3):
            server.acquire_image("haadf")
        assert server.get_specimen()["max_accumulated_dose"] > 0
        server.set_environment("pristine")
        assert server.get_specimen()["max_accumulated_dose"] == 0


# ---------------------------------------------------------------------------
# Mode and autofocus
# ---------------------------------------------------------------------------
class TestModeAndAutofocus:
    def test_invalid_mode_raises(self, server):
        with pytest.raises(ValueError, match="IMG"):
            server.set_mode("SPECTRUM")

    def test_mode_roundtrip(self, server):
        server.set_mode("DIFF")
        assert server.get_mode()["mode"] == "DIFF"
        server.set_mode("img")  # case-insensitive
        assert server.get_mode()["mode"] == "IMG"

    def test_autofocus_reports_convergence_fields(self, server):
        server.set_environment("pristine")
        server.set_mode("IMG")
        r = server.autofocus("haadf", z_range_um=2.0, z_steps=5)
        assert set(r) >= {"converged", "reason", "best_z_m",
                          "best_z_um_relative", "scores"}
        assert isinstance(r["converged"], bool)
        assert len(r["scores"]) == 5

    def test_autofocus_unknown_device_raises(self, server):
        with pytest.raises(ValueError, match="Unknown device"):
            server.autofocus("nonexistent")

    def test_failed_autofocus_leaves_z_unchanged(self, server, monkeypatch):
        # Force non-convergence by making the sharpness curve flat.
        import app.digital_twin.server as srv_mod
        monkeypatch.setattr(srv_mod, "sharpness_metric", lambda img: 1.0)
        z_before = server.get_stage()[2]
        r = server.autofocus("haadf", z_range_um=2.0, z_steps=5)
        assert r["converged"] is False
        assert server.get_stage()[2] == z_before


# ---------------------------------------------------------------------------
# Memory: registration swaps volumes, never accumulates
# ---------------------------------------------------------------------------
class TestVolumeRelease:
    def test_old_volume_released_after_reregistration(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        old_vol_ref = weakref.ref(fresh_server.vol)
        fresh_server.load_sample("au_dispersed", D=D, H=H, W=W)
        gc.collect()
        assert old_vol_ref() is None, (
            "previous specimen volume is still referenced after re-registration"
        )

    def test_registered_volume_has_expected_shape(self, fresh_server):
        fresh_server.load_sample("bcc_single_crystal", D=D, H=H, W=W)
        assert fresh_server.vol.shape == (D, H, W)
        assert fresh_server.vol.dtype == np.float32
