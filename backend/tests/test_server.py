"""Unit tests for the v6 STEMServer — direct class-level tests (no sockets).

Covers the safety-critical core: stage soft limits (boundary-exact cases per
axis), the sample registration gate, the full sample registry, acquisition
conditions (contamination / noise / drift / autofocus limits),
magnification/FOV coupling, autofocus convergence reporting, and
specimen-volume release across registrations.
"""

import gc
import time
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
        assert img["shape"] == (1024, 1024)
        assert img["dtype"] == "uint16"

    @pytest.mark.parametrize(
        "name",
        [s["name"] for s in samples.list_samples() if s["name"] not in FILE_BACKED_SAMPLES],
    )
    def test_every_sample_produces_diffraction(self, fresh_server, name):
        fresh_server.load_sample(name, D=D, H=H, W=W)
        fresh_server.set_mode("DIFF")
        img = fresh_server.acquire_image("haadf")
        assert img["shape"] == (1024, 1024)

    def test_unknown_sample_raises(self, server):
        with pytest.raises(KeyError, match="Unknown sample"):
            server.load_sample("no_such_sample", D=D, H=H, W=W)

    def test_file_backed_sample_loads_shipped_example(self, fresh_server):
        # The default file_path resolves to the example polycrystal shipped
        # under backend/sample_data/, regardless of the process cwd.
        r = fresh_server.load_sample("atomsk_polycrystal", D=D, H=H, W=W)
        assert r["loaded"] == "atomsk_polycrystal"
        # auto_fit shrinks the world to the structure (~80 A wide -> ~11 nm)
        assert fresh_server.sample_fov_um < 1.0
        # the detector FOV is clamped to the shrunken world at load
        assert (fresh_server.detectors["haadf"]["field_of_view_um"]
                <= fresh_server.sample_fov_um + 1e-9)
        # regression for the 0.38-voxel-dot bug: the structure must actually
        # light up the frame, not render as a sub-voxel point (loose floor)
        import base64 as _b64
        img = fresh_server.acquire_image("haadf")
        arr = np.frombuffer(_b64.b64decode(img["__ndarray_b64__"]),
                            dtype=img["dtype"]).reshape(img["shape"]).astype(float)
        bright = (arr > arr.mean() + arr.std()).mean()
        assert bright > 0.02

    def test_file_backed_sample_fails_clearly_without_file(self, fresh_server):
        with pytest.raises(Exception, match="file not found"):
            fresh_server.load_sample("atomsk_polycrystal", D=D, H=H, W=W,
                                     params={"file_path": "no/such/file.xyz"})

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
        server.set_drift(vx_nm_per_s=0.0, vy_nm_per_s=0.0, line_jitter_nm=0.0,
                         enabled=False, reset_accum=True)
        server.set_contamination(enabled=False)
        server.set_noise(dwell_us=20.0, dqe=0.9, readout_e=1.0)
        server.set_autofocus_limits(min_contrast=0.05)
        server.reset_specimen()
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

    def test_state_snapshot_includes_thickness_and_resolution(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W,
                                 thickness_nm=40.0)
        state = fresh_server.get_microscope_state()
        assert state["thickness"]["working_nm"] == pytest.approx(40.0)
        assert state["resolution"]["resolution_px"] in (1024, 2048, 4096)
        assert state["resolution"]["allowed"] == [1024, 2048, 4096]


# ---------------------------------------------------------------------------
# Resolution windows (discrete 1024/2048/4096)
# ---------------------------------------------------------------------------
class TestResolutionWindows:
    def test_default_resolution_is_1024(self, fresh_server):
        r = fresh_server.get_resolution()
        assert r["resolution_px"] == 1024
        assert r["allowed"] == [1024, 2048, 4096]

    def test_set_resolution_changes_acquire_shape(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        fresh_server.set_resolution(2048)
        img = fresh_server.acquire_image("haadf")
        assert img["shape"] == (2048, 2048)
        fresh_server.set_resolution(1024)
        img = fresh_server.acquire_image("haadf")
        assert img["shape"] == (1024, 1024)

    @pytest.mark.parametrize("bad", [256, 512, 768, 0, -1024])
    def test_invalid_resolution_rejected_with_allowed_list(self, fresh_server, bad):
        with pytest.raises(ValueError, match=r"1024, 2048, 4096"):
            fresh_server.set_resolution(bad)

    def test_rejected_resolution_leaves_setting_unchanged(self, fresh_server):
        before = fresh_server.get_resolution()["resolution_px"]
        with pytest.raises(ValueError):
            fresh_server.set_resolution(999)
        assert fresh_server.get_resolution()["resolution_px"] == before


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


# ---------------------------------------------------------------------------
# v2 realism package: physical drift units, idle-jump guard, real-dose exposure
# ---------------------------------------------------------------------------
class TestPhysicalDrift:
    def test_nm_per_s_converts_via_volume_scale(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        r = fresh_server.set_drift(vx_nm_per_s=2.0, vy_nm_per_s=1.0, enabled=True)
        px_per_nm = fresh_server.sample_px_per_um / 1000.0
        assert r["vx_px_per_s"] == pytest.approx(2.0 * px_per_nm)
        assert r["vy_px_per_s"] == pytest.approx(1.0 * px_per_nm)

    def test_result_echoes_physical_rates(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        r = fresh_server.set_drift(vx_nm_per_s=3.5, vy_nm_per_s=0.5)
        assert r["vx_nm_per_s"] == pytest.approx(3.5)
        assert r["vy_nm_per_s"] == pytest.approx(0.5)

    def test_px_interface_still_works(self, fresh_server):
        r = fresh_server.set_drift(vx_px_per_s=0.5, vy_px_per_s=0.25)
        assert r["vx_px_per_s"] == pytest.approx(0.5)
        assert r["vy_px_per_s"] == pytest.approx(0.25)

    def test_idle_gap_is_capped_by_max_dt(self, fresh_server, monkeypatch):
        """A long pause between acquires must not teleport the field: drift
        advances by at most max_dt_s of wall-clock per frame."""
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        fresh_server.set_drift(vx_px_per_s=1.0, vy_px_per_s=0.0, enabled=True,
                               reset_accum=True)
        # Simulate a 60 s idle gap before the next acquire.
        fresh_server._last_acquire_t = time.time() - 60.0
        fresh_server.acquire_image("haadf")
        accum = fresh_server.get_drift()["accum_x_px"]
        max_dt = fresh_server.sim.drift["max_dt_s"]
        assert accum <= 1.0 * max_dt + 1e-6, (
            f"idle gap applied {accum:.2f} px of drift; cap is {max_dt}s * 1px/s")
        assert accum > 0.0

    def test_state_snapshot_reports_drift_and_dose(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        fresh_server.set_drift(vx_nm_per_s=1.0, enabled=True)
        state = fresh_server.get_microscope_state()
        assert state["drift"]["vx_nm_per_s"] == pytest.approx(1.0)
        assert "max_contamination" in state["specimen"]
        assert "max_accumulated_dose" not in state["specimen"]
        assert "min_contrast" in state["autofocus"]
        assert "environment" not in state


class TestRealDose:
    def _contamination_after_one_frame(self, srv, fov_um, resolution_px):
        srv.set_contamination(enabled=True, rate=100.0)
        srv.reset_specimen()
        srv.device_settings("haadf", field_of_view_um=fov_um, size=resolution_px)
        srv.acquire_image("haadf")
        return float(srv.get_specimen()["max_contamination"])

    def test_dose_is_real_electrons_per_A2(self, fresh_server):
        """accumulation = dose * rate/100, dose = (I*t/e)/pixel_area with
        pixel_area=(FOV/res)^2; at rate=100 the map holds the dose itself."""
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        fresh_server.set_beam({"current_pA": 80.0}, relative=False)
        fresh_server.device_settings("haadf", dwell_us=20.0)
        dose = self._contamination_after_one_frame(fresh_server, fov_um=1.0,
                                                   resolution_px=1024)
        e_per_px = (80.0e-12 / 1.602e-19) * 20e-6
        pix_A2 = ((1.0 * 1000.0 / 1024) * 10.0) ** 2
        assert dose == pytest.approx(e_per_px / pix_A2, rel=1e-3)

    def test_higher_resolution_concentrates_dose(self, fresh_server):
        """Same FOV, 1024 -> 2048 px: 4x smaller pixel area, 4x the dose."""
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        d1024 = self._contamination_after_one_frame(fresh_server, fov_um=2.0,
                                                    resolution_px=1024)
        d2048 = self._contamination_after_one_frame(fresh_server, fov_um=2.0,
                                                    resolution_px=2048)
        assert d2048 == pytest.approx(4.0 * d1024, rel=1e-3)

    def test_smaller_fov_concentrates_dose(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        d_wide = self._contamination_after_one_frame(fresh_server, fov_um=4.0,
                                                     resolution_px=1024)
        d_narrow = self._contamination_after_one_frame(fresh_server, fov_um=1.0,
                                                       resolution_px=1024)
        assert d_narrow == pytest.approx(16.0 * d_wide, rel=1e-3)


# ---------------------------------------------------------------------------
# v5 acquisition-condition setters (contamination / noise / autofocus / drift)
# ---------------------------------------------------------------------------
class TestConditionSetters:
    def test_set_contamination_roundtrip(self, fresh_server):
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        r = fresh_server.set_contamination(enabled=True, rate=250.0)
        assert r["contamination_rate"] == pytest.approx(250.0)
        assert r["contamination_enabled"] == 1.0
        r = fresh_server.set_contamination(enabled=False)
        assert r["contamination_enabled"] == 0.0
        # rate=0 is "off" even while enabled: nothing accumulates
        fresh_server.set_contamination(enabled=True, rate=0.0)
        fresh_server.reset_specimen()
        fresh_server.acquire_image("haadf")
        assert fresh_server.get_specimen()["max_contamination"] == 0.0

    def test_contamination_rate_is_a_percentage_of_nominal(self, fresh_server):
        # Accumulation is deterministic (the image noise is not), so a single
        # frame at rate=200 must land at exactly 2x the rate=100 map max.
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        fresh_server.set_contamination(enabled=True, rate=100.0)
        fresh_server.reset_specimen()
        fresh_server.acquire_image("haadf")
        at_100 = fresh_server.get_specimen()["max_contamination"]
        fresh_server.set_contamination(rate=200.0)
        fresh_server.reset_specimen()
        fresh_server.acquire_image("haadf")
        at_200 = fresh_server.get_specimen()["max_contamination"]
        assert at_100 > 0.0
        assert at_200 == pytest.approx(2.0 * at_100, rel=1e-6)

    def test_set_noise_writes_only_the_keys_passed(self, fresh_server):
        # Partial-update trap: a later call touching another key must NOT
        # reset earlier settings to defaults (the project's worst historical
        # defect was exactly this leak).
        fresh_server.set_noise(dwell_us=5.0)
        fresh_server.set_noise(dqe=0.5)
        det = fresh_server.detectors["haadf"]
        assert det["dwell_us"] == pytest.approx(5.0)
        assert det["dqe"] == pytest.approx(0.5)

    def test_set_autofocus_limits_roundtrip_and_enforcement(self, fresh_server):
        r = fresh_server.set_autofocus_limits(min_contrast=0.2)
        assert r["af_min_contrast"] == pytest.approx(0.2)
        # An absurdly strict threshold must make autofocus refuse to converge.
        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        fresh_server.set_autofocus_limits(min_contrast=0.999)
        af = fresh_server.autofocus("haadf", z_range_um=2.0, z_steps=5)
        assert af["converged"] is False
        assert "low contrast" in af["reason"]

    def test_set_drift_max_dt_roundtrip(self, fresh_server):
        fresh_server.set_drift(max_dt_s=120.0)
        assert fresh_server.get_drift()["max_dt_s"] == pytest.approx(120.0)


# ---------------------------------------------------------------------------
# v5 removed surface: environments / specimen presets / EELS are gone
# ---------------------------------------------------------------------------
class TestRemovedSurface:
    @pytest.mark.parametrize("name", ["set_environment", "get_environment",
                                      "set_specimen", "acquire_spectrum"])
    def test_removed_rpcs_are_gone(self, fresh_server, name):
        assert not hasattr(fresh_server, name)

    def test_eels_mode_rejected(self, fresh_server):
        with pytest.raises(ValueError, match="IMG"):
            fresh_server.set_mode("EELS")

    def test_harness_surface_is_current(self):
        from app.digital_twin.sim_harness import SimulationHarness
        assert not hasattr(SimulationHarness, "set_environment")
        assert not hasattr(SimulationHarness, "set_specimen")
        assert hasattr(SimulationHarness, "set_contamination")
        assert hasattr(SimulationHarness, "set_noise")

    def test_control_client_surface_is_current(self):
        from app.digital_twin.control_client import MicroscopeControlClient
        assert not hasattr(MicroscopeControlClient, "acquire_spectrum")
        assert hasattr(MicroscopeControlClient, "set_autofocus_limits")


# ---------------------------------------------------------------------------
# v3 performance rewrites: exactness of PERF A / PERF B and spot scaling
# ---------------------------------------------------------------------------
class TestPerfRewritesExact:
    def test_perf_a_projection_collapse_is_exact(self, fresh_server):
        """PERF A relies on: sum_z bilinear(vol[z]) == bilinear(sum_z vol[z]).
        Verify the identity on the real bilinear_sample and a real loaded
        volume, at the same float32 precision the render path uses."""
        from app.digital_twin.server import bilinear_sample

        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        vol = np.asarray(fresh_server.vol)
        rng = np.random.default_rng(0)
        ys = rng.uniform(1, vol.shape[1] - 2, size=(64, 64)).astype(np.float32)
        xs = rng.uniform(1, vol.shape[2] - 2, size=(64, 64)).astype(np.float32)
        slow = np.zeros((64, 64), dtype=np.float32)
        for z in range(vol.shape[0]):
            slow += bilinear_sample(vol[z], ys, xs)
        fast = bilinear_sample(vol.sum(axis=0, dtype=np.float32), ys, xs)
        assert np.allclose(fast, slow, rtol=1e-4, atol=1e-2)

    def test_perf_b_patch_local_matches_full_grid(self):
        """Patch-local spot rendering must match the pre-change full-grid
        evaluation to within 16-bit output quantisation (changelog §8.2)."""
        from app.digital_twin.samples.fcc_single_crystal import FCCSingleCrystal
        from app.digital_twin.server import kinematical_diffraction

        lat = FCCSingleCrystal().lattice
        kw = dict(out_size=512, tilt_a_deg=0.0, tilt_b_deg=0.0,
                  spot_sigma_px=2.5)
        patch = kinematical_diffraction(lat, **kw)
        full = kinematical_diffraction(lat, spot_render_radius_sigma=1e9, **kw)
        assert np.abs(patch - full).max() <= 1.0  # under one 16-bit step

    def test_spot_sigma_default_scales_with_resolution(self):
        """User decision (§8.4 applied): the default spot width scales with
        the window so patterns look proportionally identical. Passing the
        scaled sigma explicitly must reproduce the default exactly."""
        from app.digital_twin.samples.fcc_single_crystal import FCCSingleCrystal
        from app.digital_twin.server import kinematical_diffraction

        lat = FCCSingleCrystal().lattice
        for out_size in (256, 512):
            auto = kinematical_diffraction(lat, out_size, 0.0, 0.0)
            explicit = kinematical_diffraction(
                lat, out_size, 0.0, 0.0,
                spot_sigma_px=2.5 * (out_size / 1024.0))
            assert np.array_equal(auto, explicit)

    def test_beamstop_scales_with_resolution(self, fresh_server, monkeypatch):
        """User decision (§8.4 applied): the stored beamstop radius is
        calibrated at the 1024 window and scaled by out_size/1024 at render
        time, so it covers the same FRACTION of the pattern at every
        resolution. Spy on the render call to see the value actually used."""
        import app.digital_twin.server as server_mod

        fresh_server.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        fresh_server.set_mode("DIFF")

        captured = []
        orig = server_mod.diffraction_from_atoms

        def spy(*args, **kwargs):
            captured.append(float(kwargs["beamstop_radius_px"]))
            return orig(*args, **kwargs)

        monkeypatch.setattr(server_mod, "diffraction_from_atoms", spy)
        fresh_server.set_resolution(1024)
        fresh_server.acquire_image("haadf")
        fresh_server.set_resolution(2048)
        fresh_server.acquire_image("haadf")
        assert captured[0] == pytest.approx(6.0)    # stored 6.0 at reference
        assert captured[1] == pytest.approx(12.0)   # 2x window -> 2x pixels
