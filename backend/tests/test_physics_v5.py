"""Regression tests for the v5 physics, ported from the changelog's §6
verification measurements. Each test pins a number or identity that was
measured on the live code when v5 landed:

  §6.1  tilt is a rigid rotation — bar separation follows cos(beta)
  §6.2  depth of field is depth-resolved inside the projection
  §6.3  contamination accumulation is real e-/A^2 scaled by a % knob
  §6.4  roaming — periodic samples are exactly periodic, world-mode
        revisits are bit-identical, and re-tiling never grows the volume
  §6.5/6.7  drift accrual honors the settable max_dt_s idle cap
  §6.6  the PSF kernel cap is 96 (not 24), and only binds when defocused
  §6.9  the tilted focal plane produces an in-focus band
"""

import base64
import time

import numpy as np
import pytest

from app.digital_twin.server import (
    CONTAM_DOSE_SCALE,
    STEMServer,
    bilinear_sample,
    make_psf,
    project_with_dof,
)

D, H, W = 16, 96, 96


def _decode(img):
    return np.frombuffer(base64.b64decode(img["__ndarray_b64__"]),
                         dtype=img["dtype"]).reshape(img["shape"])


def _deterministic(srv):
    """Noise-free, drift-free, contamination-free acquisition conditions so a
    frame is a pure function of specimen + window."""
    srv.set_noise(use_dose_model=0, noise_sigma=0.0)
    srv.set_drift(enabled=False, reset_accum=True)
    srv.set_contamination(enabled=False)
    srv.reset_specimen()


def _grids(out_size, half_px):
    o = np.linspace(-half_px, half_px, out_size, dtype=np.float32)
    dY, dX = np.meshgrid(o, o, indexing="ij")
    return dX, dY


@pytest.fixture()
def fresh_server():
    srv = STEMServer(D=D, H=H, W=W)
    srv.finish_init()
    return srv


# ---------------------------------------------------------------------------
# §6.1 — tilt is a rigid rotation (foreshortening tracks cos(beta))
# ---------------------------------------------------------------------------
class TestRigidRotationTilt:
    @staticmethod
    def _bar_separation(beta_deg):
        vd, vh, vw = 8, 600, 600
        vol = np.zeros((vd, vh, vw), dtype=np.float32)
        vol[:, :, 250] = 1.0
        vol[:, :, 350] = 1.0
        dX, dY = _grids(600, 300.0)
        proj = project_with_dof(vol, dX, dY, 300.0, 300.0, (vd - 1) / 2.0,
                                tilt_b_deg=beta_deg, max_sigma_px=0.0)
        cols = proj.sum(axis=0)
        p1 = int(np.argmax(cols))
        cols[max(0, p1 - 5):p1 + 6] = 0.0
        p2 = int(np.argmax(cols))
        return abs(p1 - p2)

    def test_separation_follows_cos_beta(self):
        sep0 = self._bar_separation(0.0)
        assert sep0 == pytest.approx(100, abs=2)
        for beta in (10.0, 20.0, 30.0):
            sep = self._bar_separation(beta)
            expected = sep0 * np.cos(np.deg2rad(beta))
            # §6.1 measured <=1.24% error; allow 2% plus a pixel of quantisation
            assert sep == pytest.approx(expected, abs=2.0 + 0.02 * expected)

    def test_shear_model_would_not_foreshorten(self):
        # The defining failure of the old shear model: ratio 1.000 at every
        # angle. 30 degrees must compress by >10%.
        assert self._bar_separation(30.0) < 0.92 * self._bar_separation(0.0)


# ---------------------------------------------------------------------------
# §6.2 — depth of field is applied per depth slice inside the projection
# ---------------------------------------------------------------------------
class TestDepthResolvedFocus:
    @staticmethod
    def _peaks(defocus_nm):
        vd, vs = 40, 128
        vol = np.zeros((vd, vs, vs), dtype=np.float32)
        vol[5, 64, 40] = 1.0    # feature A, near the top of the slab
        vol[35, 64, 88] = 1.0   # feature B, near the bottom
        dX, dY = _grids(vs, vs / 2.0)
        proj = project_with_dof(vol, dX, dY, vs / 2.0, vs / 2.0,
                                (vd - 1) / 2.0, defocus_nm=defocus_nm,
                                nm_per_vox_z=2.5, max_sigma_px=9.0,
                                focus_gain_nm=60.0)
        return proj[:, :64].max(), proj[:, 64:].max()

    def test_focal_plane_selects_depth(self):
        # Focusing at A's depth ((5 - 19.5) * 2.5 nm) sharpens A and blurs B;
        # the opposite defocus reverses it. Post-projection blur (the v4
        # model) cannot produce this: it saw only the summed z axis.
        a_sharp, b_blur = self._peaks(+36.25)
        a_blur, b_sharp = self._peaks(-38.75)
        assert a_sharp > 3.0 * a_blur
        assert b_sharp > 3.0 * b_blur


# ---------------------------------------------------------------------------
# bilinear_sample — wrap mode and the border-rim fix (§3.2 / v5 ledger)
# ---------------------------------------------------------------------------
class TestBilinearSample:
    def test_wrap_makes_the_volume_periodic(self):
        img = np.arange(16, dtype=np.float32).reshape(4, 4)
        y, x = np.array([[0.0]]), np.array([[4.0]])  # one full width off-edge
        assert bilinear_sample(img, y, x, wrap=True)[0, 0] == img[0, 0]

    def test_border_weights_do_not_collapse(self):
        # The old clamped-index weights summed to ~0 in the last half-pixel,
        # a one-pixel dark rim on every edge the roaming window now reaches.
        img = np.full((8, 8), 100.0, dtype=np.float32)
        y, x = np.array([[7.4]]), np.array([[3.0]])
        assert bilinear_sample(img, y, x)[0, 0] == pytest.approx(100.0, rel=1e-5)


# ---------------------------------------------------------------------------
# §6.4 — roaming
# ---------------------------------------------------------------------------
class TestPeriodicRoaming:
    def test_period_is_exact_and_nothing_clamps(self, fresh_server):
        # au_dispersed: textured at every FOV. (fcc renders a uniform slab at
        # low mag — open item O20 — so its frames compare equal trivially.)
        srv = fresh_server
        srv.load_sample("au_dispersed", D=D, H=H, W=W)
        _deterministic(srv)
        period_um = srv.sample_fov_um
        srv.detectors["haadf"]["field_of_view_um"] = period_um / 4.0

        def _same(a, b):
            # exact up to the uint16 quantisation boundary: one period of
            # stage travel is exactly W volume pixels only in exact
            # arithmetic, and the float epsilon can flip a count of 1
            return int(np.abs(a.astype(np.int32) - b.astype(np.int32)).max()) <= 1

        srv.set_stage([0, 0, 0, 0, 0], relative=False)
        base = _decode(srv.acquire_image("haadf"))
        # one full period of stage travel lands on the identical frame
        srv.set_stage([period_um * 1e-6, 0, 0, 0, 0], relative=False)
        assert _same(_decode(srv.acquire_image("haadf")), base)
        # 2.5 periods == 0.5 periods (wraps, does not clamp at a margin)
        srv.set_stage([2.5 * period_um * 1e-6, 0, 0, 0, 0], relative=False)
        far = _decode(srv.acquire_image("haadf"))
        srv.set_stage([0.5 * period_um * 1e-6, 0, 0, 0, 0], relative=False)
        assert _same(far, _decode(srv.acquire_image("haadf")))
        assert not _same(far, base)


class TestWorldRoaming:
    def test_revisits_are_bit_identical_and_volume_stays_bounded(self, fresh_server):
        srv = fresh_server
        srv.load_sample("shape_assembly", D=D, H=H, W=W)
        _deterministic(srv)
        srv.detectors["haadf"]["field_of_view_um"] = srv.sample_fov_um / 4.0

        srv.set_stage([0, 0, 0, 0, 0], relative=False)
        home = _decode(srv.acquire_image("haadf"))
        srv.set_stage([800e-6, 0, 0, 0, 0], relative=False)
        away = _decode(srv.acquire_image("haadf"))
        # 800 um away is genuinely different specimen (world mode: no repeat)
        assert not np.array_equal(away, home)
        # re-tiling replaced the cached volume, it did not grow it (the
        # GB-explosion guard for unbounded roaming)
        assert srv.vol.shape == (D, H, W)
        assert srv._vol_origin_px != (0.0, 0.0)
        # driving back reveals the same specimen you left, bit-identical
        srv.set_stage([0, 0, 0, 0, 0], relative=False)
        assert np.array_equal(_decode(srv.acquire_image("haadf")), home)


# ---------------------------------------------------------------------------
# §6.5 / §6.7 — drift accrual over a long gap honors a raised max_dt_s
# ---------------------------------------------------------------------------
class TestDriftLongGap:
    def test_raised_max_dt_lets_a_long_wait_accrue(self, fresh_server):
        srv = fresh_server
        srv.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        _deterministic(srv)
        srv.set_drift(vx_nm_per_s=2.0, enabled=True, max_dt_s=120.0,
                      reset_accum=True)
        srv._last_acquire_t = time.time() - 100.0
        srv.acquire_image("haadf")
        accum = srv.get_drift()["accum_x_px"]
        expected = srv.get_drift()["vx_px_per_s"] * 100.0
        # the whole 100 s gap counts (default cap of 2 s would give 2% of it)
        assert accum == pytest.approx(expected, rel=0.05)


# ---------------------------------------------------------------------------
# §6.3 — contamination: real e-/A^2, % knob, saturating exponential
# ---------------------------------------------------------------------------
class TestContaminationModel:
    @staticmethod
    def _configure(srv, rate):
        _deterministic(srv)
        srv.set_beam({"current_pA": 400.0, "voltage_kV": 200.0})
        srv.set_noise(dwell_us=60.0)
        srv.detectors["haadf"]["size"] = 128
        srv.detectors["haadf"]["field_of_view_um"] = 4.0
        srv.set_contamination(enabled=True, rate=rate)
        srv.reset_specimen()

    @staticmethod
    def _expected_inc(rate):
        e_per_px = (400.0e-12 / 1.602e-19) * 60.0e-6
        pix_A2 = ((4000.0 / 128.0) * 10.0) ** 2
        return (e_per_px / pix_A2) * (rate / 100.0)

    def test_accumulation_is_real_dose_times_percentage(self, fresh_server):
        srv = fresh_server
        srv.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        self._configure(srv, rate=100.0)
        srv.acquire_image("haadf")
        assert srv.get_specimen()["max_contamination"] == pytest.approx(
            self._expected_inc(100.0), rel=1e-3)

    def test_rate_is_a_percentage_knob(self, fresh_server):
        srv = fresh_server
        srv.load_sample("fcc_single_crystal", D=D, H=H, W=W)
        self._configure(srv, rate=200.0)
        srv.acquire_image("haadf")
        doubled = srv.get_specimen()["max_contamination"]
        self._configure(srv, rate=100.0)
        srv.acquire_image("haadf")
        nominal = srv.get_specimen()["max_contamination"]
        assert doubled == pytest.approx(2.0 * nominal, rel=1e-6)
        self._configure(srv, rate=0.0)
        srv.acquire_image("haadf")
        assert srv.get_specimen()["max_contamination"] == 0.0

    def test_dwelled_region_brightens_within_a_few_frames(self, fresh_server):
        # Demo-H4 style conditions; v5's recalibration made the footprint
        # visible (the old constants were ~1000x too slow: +50 counts of
        # 60000 after 12 frames). Use the dose model, where the brightening
        # is applied; the effect (>15%) dwarfs shot noise on a frame mean.
        # amorphous_film sits mid-range in brightness; fcc's uniform 60000
        # slab leaves no headroom below the 65535 clip for the brightening.
        srv = fresh_server
        srv.load_sample("amorphous_film", D=D, H=H, W=W)
        self._configure(srv, rate=100.0)
        srv.set_noise(use_dose_model=1)
        first = float(_decode(srv.acquire_image("haadf")).mean())
        for _ in range(5):
            srv.acquire_image("haadf")
        last = float(_decode(srv.acquire_image("haadf")).mean())
        assert last > 1.15 * first


# ---------------------------------------------------------------------------
# §6.6 — PSF kernel cap raised 24 -> 96, binding only when defocused
# ---------------------------------------------------------------------------
class TestPsfKernelCap:
    def test_cap_is_96_when_badly_defocused(self):
        psf = make_psf(defocus_nm=5.0e4, pixel_nm=2.0)
        assert psf.shape == (193, 193)  # 2 * 96 + 1: the old cap gave 49x49

    def test_cap_does_not_bind_in_focus(self):
        psf = make_psf(defocus_nm=0.0, pixel_nm=2.0)
        assert psf.shape[0] < 49  # r = ceil(3 sigma), far below either cap


# ---------------------------------------------------------------------------
# §6.9 — the tilted focal plane is an in-focus band across the field
# ---------------------------------------------------------------------------
class TestTiltFocusBand:
    @staticmethod
    def _band_contrast(srv, alpha_deg):
        srv.set_stage([0, 0, 0, alpha_deg, 0], relative=False)
        img = _decode(srv.acquire_image("haadf")).astype(np.float64)
        grad = np.abs(np.diff(img, axis=1)).mean(axis=1)
        bands = grad.reshape(8, -1).mean(axis=1)
        return float(bands.max() / max(bands.min(), 1e-9))

    def test_alpha_tilt_creates_a_sharpness_band(self, fresh_server):
        # Full-width volume: at 96 px the 5 um window upsamples ~10x and the
        # texture is too smooth for row-gradient banding to register.
        srv = fresh_server
        srv.load_sample("amorphous_film", D=D, H=768, W=768)
        _deterministic(srv)
        srv.detectors["haadf"]["size"] = 256
        srv.detectors["haadf"]["field_of_view_um"] = 5.0
        # gain 150 gave 11.4x band contrast in §6.9; the band half-width is
        # gain/(1000 sin a) = 0.3 um against a 2.5 um half-field
        srv.set_optics(dof_focus_gain_nm=150.0, dof_max_sigma_px=9.0)
        flat = self._band_contrast(srv, 0.0)
        tilted = self._band_contrast(srv, 30.0)
        assert tilted > 2.0 * flat
        assert tilted > 2.5
