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
        assert img["shape"] == (512, 512)
        assert img["dtype"] == "uint16"

    @pytest.mark.parametrize(
        "name",
        [s["name"] for s in samples.list_samples() if s["name"] not in FILE_BACKED_SAMPLES],
    )
    def test_every_sample_produces_diffraction(self, fresh_server, name):
        fresh_server.load_sample(name, D=D, H=H, W=W)
        fresh_server.set_mode("DIFF")
        img = fresh_server.acquire_image("haadf")
        assert img["shape"] == (512, 512)

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


# ---------------------------------------------------------------------------
# Thickness workflow (v6+: working slab within the specimen's total thickness)
# ---------------------------------------------------------------------------
def _decode_u16(img_payload):
    """Decode the serialize_ndarray_b64 payload back to a numpy array."""
    import base64
    raw = base64.b64decode(img_payload["__ndarray_b64__"])
    return np.frombuffer(raw, dtype=img_payload["dtype"]).reshape(img_payload["shape"])


class TestThicknessWorkflow:
    def test_load_reports_thickness(self, fresh_server):
        r = fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W,
                                     thickness_nm=30.0, thickness_seed=7)
        th = r["thickness"]
        assert th["total_nm"] == pytest.approx(100.0)
        assert th["working_nm"] == pytest.approx(30.0)
        assert th["seed"] == 7
        assert 0.0 <= th["z_start_nm"] <= 70.0

    def test_default_load_uses_full_thickness(self, fresh_server):
        r = fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        th = r["thickness"]
        assert th["working_nm"] == pytest.approx(th["total_nm"])
        assert th["z_start_nm"] == pytest.approx(0.0)

    def test_set_thickness_without_sample_raises_no_sample(self, fresh_server):
        with pytest.raises(RuntimeError, match="No sample registered"):
            fresh_server.set_thickness(thickness_nm=30.0)

    def test_working_thickness_clamped_to_total(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        th = fresh_server.set_thickness(thickness_nm=500.0)
        assert th["working_nm"] == pytest.approx(th["total_nm"])
        th = fresh_server.set_thickness(thickness_nm=0.0)
        assert th["working_nm"] == pytest.approx(1.0)

    def test_thickness_seed_deterministic(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        a = fresh_server.set_thickness(thickness_nm=30.0, thickness_seed=11)
        b = fresh_server.set_thickness(thickness_nm=30.0, thickness_seed=11)
        assert a["z_start_nm"] == pytest.approx(b["z_start_nm"])
        c = fresh_server.set_thickness(thickness_nm=30.0, thickness_seed=12)
        assert c["z_start_nm"] != pytest.approx(a["z_start_nm"])

    def test_set_thickness_syncs_diffraction_relrod(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        fresh_server.set_thickness(thickness_nm=42.0)
        assert fresh_server.get_diffraction_settings()["thickness_nm"] == pytest.approx(42.0)

    def test_get_thickness_roundtrip(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W,
                                 thickness_nm=25.0, thickness_seed=3)
        th = fresh_server.get_thickness()
        assert th["working_nm"] == pytest.approx(25.0)
        assert th["seed"] == 3

    def test_thinner_slab_gives_less_haadf_signal(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        fresh_server.set_thickness(thickness_nm=100.0)
        thick = _decode_u16(fresh_server.acquire_image("haadf")).mean()
        fresh_server.set_thickness(thickness_nm=5.0)
        thin = _decode_u16(fresh_server.acquire_image("haadf")).mean()
        assert thin < thick


# ---------------------------------------------------------------------------
# Resolution windows (discrete 512/1024/2048)
# ---------------------------------------------------------------------------
class TestResolutionWindows:
    def test_default_resolution_is_512(self, fresh_server):
        r = fresh_server.get_resolution()
        assert r["resolution_px"] == 512
        assert r["allowed"] == [512, 1024, 2048]

    def test_set_resolution_changes_acquire_shape(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        fresh_server.set_resolution(1024)
        img = fresh_server.acquire_image("haadf")
        assert img["shape"] == (1024, 1024)
        fresh_server.set_resolution(512)
        img = fresh_server.acquire_image("haadf")
        assert img["shape"] == (512, 512)

    @pytest.mark.parametrize("bad", [256, 768, 4096, 0, -512])
    def test_invalid_resolution_rejected_with_allowed_list(self, fresh_server, bad):
        with pytest.raises(ValueError, match=r"512, 1024, 2048"):
            fresh_server.set_resolution(bad)

    def test_rejected_resolution_leaves_setting_unchanged(self, fresh_server):
        before = fresh_server.get_resolution()["resolution_px"]
        with pytest.raises(ValueError):
            fresh_server.set_resolution(999)
        assert fresh_server.get_resolution()["resolution_px"] == before


# ---------------------------------------------------------------------------
# EELS mode + single-spot spectrum
# ---------------------------------------------------------------------------
class TestEELS:
    def test_eels_mode_accepted(self, fresh_server):
        assert fresh_server.set_mode("EELS")["mode"] == "EELS"
        assert fresh_server.get_mode()["mode"] == "EELS"

    def test_acquire_spectrum_without_sample_raises_no_sample(self, fresh_server):
        with pytest.raises(RuntimeError, match="No sample registered"):
            fresh_server.acquire_spectrum()

    def test_spectrum_shape_and_range(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        r = fresh_server.acquire_spectrum(ev_min=0.0, ev_max=1000.0, n_channels=512)
        assert len(r["energy_ev"]) == 512
        assert len(r["intensity"]) == 512
        assert r["energy_ev"][0] == pytest.approx(0.0)
        assert r["energy_ev"][-1] == pytest.approx(1000.0)
        assert min(r["intensity"]) >= 0.0

    def test_fe_sample_shows_fe_edge(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        r = fresh_server.acquire_spectrum(ev_min=0.0, ev_max=1000.0)
        labels = [e["label"] for e in r["edges"]]
        assert "Fe-L" in labels
        assert 26 in r["elements_Z"]

    def test_au_sample_shows_au_edge_in_extended_range(self, fresh_server):
        fresh_server.load_sample("au_dispersed", D=D, H=H, W=W)
        r = fresh_server.acquire_spectrum(ev_min=0.0, ev_max=2500.0)
        labels = [e["label"] for e in r["edges"]]
        assert "Au-M" in labels

    def test_edges_outside_range_omitted(self, fresh_server):
        fresh_server.load_sample("au_dispersed", D=D, H=H, W=W)
        r = fresh_server.acquire_spectrum(ev_min=0.0, ev_max=500.0)
        labels = [e["label"] for e in r["edges"]]
        assert "Au-M" not in labels   # Au-M onset 2206 eV > 500 eV

    def test_plasmon_scales_with_working_thickness(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        fresh_server.set_thickness(thickness_nm=100.0)
        thick = fresh_server.acquire_spectrum(ev_min=0.0, ev_max=60.0, n_channels=600)
        fresh_server.set_thickness(thickness_nm=10.0)
        thin = fresh_server.acquire_spectrum(ev_min=0.0, ev_max=60.0, n_channels=600)
        ep = thick["plasmon_ev"]
        idx = int(round(ep / 60.0 * 599))
        assert thick["intensity"][idx] > thin["intensity"][idx]


# ---------------------------------------------------------------------------
# Environments now carry a thickness component
# ---------------------------------------------------------------------------
class TestEnvironmentThickness:
    def test_thick_drifting_sets_90nm(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        fresh_server.set_environment("thick_drifting")
        assert fresh_server.get_thickness()["working_nm"] == pytest.approx(90.0)

    def test_low_dose_sets_25nm(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        fresh_server.set_environment("low_dose")
        assert fresh_server.get_thickness()["working_nm"] == pytest.approx(25.0)

    def test_pristine_leaves_thickness_alone(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W,
                                 thickness_nm=33.0)
        fresh_server.set_environment("pristine")
        assert fresh_server.get_thickness()["working_nm"] == pytest.approx(33.0)

    def test_environment_without_sample_does_not_crash(self, fresh_server):
        r = fresh_server.set_environment("thick_drifting")
        assert r["environment"] == "thick_drifting"

    def test_state_snapshot_includes_thickness_and_resolution(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W,
                                 thickness_nm=40.0)
        state = fresh_server.get_microscope_state()
        assert state["thickness"]["working_nm"] == pytest.approx(40.0)
        assert state["resolution"]["resolution_px"] in (512, 1024, 2048)
        assert state["resolution"]["allowed"] == [512, 1024, 2048]


# ---------------------------------------------------------------------------
# Reproducibility: same seeds => bit-identical specimen
# ---------------------------------------------------------------------------
class TestSeedDeterminism:
    def test_same_structure_seed_bit_identical_volume(self, fresh_server):
        fresh_server.load_sample("polycrystal_grains", params={"seed": 42, "n_grains": 5},
                                 D=D, H=H, W=W)
        vol_a = fresh_server.vol.copy()
        fresh_server.load_sample("polycrystal_grains", params={"seed": 42, "n_grains": 5},
                                 D=D, H=H, W=W)
        assert np.array_equal(vol_a, fresh_server.vol)

    def test_different_structure_seed_differs(self, fresh_server):
        fresh_server.load_sample("polycrystal_grains", params={"seed": 42, "n_grains": 5},
                                 D=D, H=H, W=W)
        vol_a = fresh_server.vol.copy()
        fresh_server.load_sample("polycrystal_grains", params={"seed": 43, "n_grains": 5},
                                 D=D, H=H, W=W)
        assert not np.array_equal(vol_a, fresh_server.vol)

    def test_dislocation_seed_bit_identical_volume(self, fresh_server):
        fresh_server.load_sample("dislocation_crystal",
                                 params={"disl_seed": 9, "n_dislocations": 6},
                                 D=D, H=H, W=W)
        vol_a = fresh_server.vol.copy()
        fresh_server.load_sample("dislocation_crystal",
                                 params={"disl_seed": 9, "n_dislocations": 6},
                                 D=D, H=H, W=W)
        assert np.array_equal(vol_a, fresh_server.vol)


# ---------------------------------------------------------------------------
# Diffraction tilt convention (regression for the fixed-detector-frame fix)
# ---------------------------------------------------------------------------
class TestTiltConvention:
    """The v6+ fix: the specimen is rotated and read out on a FIXED lab detector
    frame, so alpha and beta act on perpendicular detector axes (like a real
    double-tilt holder). Previously a beam-derived detector basis coupled them."""

    @staticmethod
    def _cubic_atoms(n=6, a=3.571):
        """Simple-cubic block, symmetric under x<->y swap."""
        from app.digital_twin.server import diffraction_from_atoms  # noqa: F401
        coords = (np.arange(n) - (n - 1) / 2.0) * a
        X, Y, Z3 = np.meshgrid(coords, coords, coords, indexing="ij")
        pos = np.stack([X.ravel(), Y.ravel(), Z3.ravel()], axis=1)
        Zn = np.full(len(pos), 26, dtype=np.int64)
        return pos, Zn

    def test_tilt_changes_pattern(self):
        from app.digital_twin.server import diffraction_from_atoms
        pos, Zn = self._cubic_atoms()
        flat = diffraction_from_atoms(pos, Zn, 64, 0.0, 0.0)
        tilted = diffraction_from_atoms(pos, Zn, 64, 8.0, 0.0)
        assert not np.allclose(flat, tilted)

    def test_alpha_beta_act_on_perpendicular_axes(self):
        """For an x<->y symmetric specimen, an alpha tilt and a beta tilt must
        produce patterns related by the same axis swap (transpose up to sign of
        the angle) -- i.e. the two tilts are decoupled on the detector."""
        from app.digital_twin.server import diffraction_from_atoms
        pos, Zn = self._cubic_atoms()
        I_a = diffraction_from_atoms(pos, Zn, 64, 6.0, 0.0)
        candidates = [
            diffraction_from_atoms(pos, Zn, 64, 0.0, 6.0).T,
            diffraction_from_atoms(pos, Zn, 64, 0.0, -6.0).T,
        ]
        assert any(np.allclose(I_a, c, atol=200.0) for c in candidates), (
            "alpha and beta tilts are not acting on perpendicular detector axes"
        )


# ---------------------------------------------------------------------------
# Registry contract: what the schema-driven GUI depends on
# ---------------------------------------------------------------------------
class TestRegistryContract:
    """The frontend renders parameter controls purely from param_schema and
    treats seed-like params specially. These tests pin that contract."""

    EXPECTED_SAMPLES = {
        "fcc_single_crystal", "bcc_single_crystal", "hcp_single_crystal",
        "polycrystal_grains", "dislocation_crystal", "amorphous_film",
        "au_dispersed", "au_clustered", "au_bimodal", "au_on_substrate",
        "core_shell", "shape_assembly", "atomsk_polycrystal",
    }

    def _registry(self):
        return {s["name"]: s for s in samples.list_samples()}

    def test_all_13_samples_registered(self):
        assert set(self._registry()) >= self.EXPECTED_SAMPLES

    def test_param_schema_entries_are_renderable(self):
        for name, s in self._registry().items():
            for pname, schema in s["param_schema"].items():
                assert schema.get("type") in ("int", "float", "bool", "str"), (
                    f"{name}.{pname} has unrenderable type {schema.get('type')}")
                if "min" in schema and "max" in schema:
                    assert schema["min"] <= schema["max"], f"{name}.{pname}"

    def test_defaults_exist_for_every_schema_param(self):
        for name, s in self._registry().items():
            for pname in s["param_schema"]:
                assert pname in s["default_params"], (
                    f"{name}.{pname} has a schema but no default to pre-fill")

    def test_headline_knobs_present_with_spec_ranges(self):
        reg = self._registry()
        poly = reg["polycrystal_grains"]["param_schema"]
        assert poly["n_grains"]["type"] == "int"
        assert (poly["n_grains"]["min"], poly["n_grains"]["max"]) == (2, 12)
        disl = reg["dislocation_crystal"]["param_schema"]
        assert (disl["n_dislocations"]["min"], disl["n_dislocations"]["max"]) == (1, 40)
        assert "disl_seed" in disl
        assert "n_particles" in reg["au_dispersed"]["param_schema"]
        atomsk = reg["atomsk_polycrystal"]["param_schema"]
        assert atomsk["file_path"]["type"] == "str"
        assert atomsk["auto_fit"]["type"] == "bool"

    def test_new_sample_identities_match_spec(self):
        reg = self._registry()
        assert "Fe (FCC" in reg["fcc_single_crystal"]["display_name"]
        assert "Fe (BCC" in reg["bcc_single_crystal"]["display_name"]
        assert "Mg" in reg["hcp_single_crystal"]["display_name"]

    def test_stochastic_samples_expose_a_seed(self):
        reg = self._registry()
        for name in ["polycrystal_grains", "amorphous_film",
                     "au_dispersed", "au_clustered", "au_bimodal",
                     "au_on_substrate", "core_shell"]:
            schema = reg[name]["param_schema"]
            assert any(k == "seed" or k.endswith("_seed") for k in schema), (
                f"stochastic sample {name} exposes no seed in param_schema")
