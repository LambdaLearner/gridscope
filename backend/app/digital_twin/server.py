from twisted.internet import reactor, protocol, threads
from twisted.internet.protocol import Factory
import json, time, base64, traceback
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple

from . import samples

# Distinctive error prefixes. Errors cross the JSON-RPC transport as strings,
# so the HTTP layer classifies them by matching these markers.
NO_SAMPLE_MSG = ("No sample registered. Register a sample (Sample Settings) "
                 "before driving the microscope.")
SAFETY_LIMIT_MARKER = "rejected by safety limits"

# Magnification <-> field-of-view calibration.  mag = MAG_K / fov_metres
# (equivalently fov_metres = MAG_K / mag).  MAG_K was calibrated from a real
# instrument: 57 kx corresponds to a 1.6564523008 um field of view, i.e.
# MAG_K = 57000 * 1.6564523008e-6 m = 0.0944177811456 (SI). We store MAG_K in SI
# (metres) and convert to microns at the boundary.
MAG_K = 57000.0 * 1.6564523008e-6   # = 0.0944177811456 (mag * metres)

def mag_to_fov_um(mag):
    """Magnification -> field of view in microns."""
    return (MAG_K / float(mag)) * 1e6

def fov_um_to_mag(fov_um):
    """Field of view in microns -> magnification."""
    return MAG_K / (float(fov_um) * 1e-6)


# ============================================================================
# PHYSICS (items 1-5): dose noise, PSF, drift, thickness law, kinematical diff
# ============================================================================
def make_psf(defocus_nm, cs_mm=1.0, aperture_probe_px=1.4, kv=200.0, pixel_nm=1.0,
             max_radius=24):
    sigma0 = float(aperture_probe_px)
    cs_term = 0.15 * cs_mm * (200.0 / max(50.0, kv))
    defocus_px = abs(defocus_nm) / max(1e-3, pixel_nm)
    sigma = np.sqrt(sigma0**2 + (0.18 * defocus_px)**2 + cs_term**2)
    r = int(min(max_radius, max(2, np.ceil(3 * sigma))))
    y, x = np.mgrid[-r:r+1, -r:r+1].astype(np.float32)
    rr = np.sqrt(x*x + y*y)
    psf = np.exp(-(rr*rr) / (2 * sigma * sigma)).astype(np.float32)
    if defocus_px > 6.0:
        ring_r = 0.6 * defocus_px
        ring_w = max(1.0, 0.15 * defocus_px)
        ring = np.exp(-((rr - ring_r)**2) / (2 * ring_w * ring_w)).astype(np.float32)
        psf = psf + 0.12 * ring
    s = psf.sum()
    if s > 0:
        psf /= s
    return psf


def convolve2d_fft(img, psf):
    H, W = img.shape
    kh, kw = psf.shape
    pad = max(kh, kw)
    ap = np.pad(img, ((pad, pad), (pad, pad)), mode="edge").astype(np.float32)
    fh, fw = ap.shape
    F = np.fft.rfft2(ap)
    K = np.fft.rfft2(psf, s=(fh, fw))
    out = np.fft.irfft2(F * K, s=(fh, fw))
    out = np.roll(out, (-(kh // 2), -(kw // 2)), axis=(0, 1))
    return out[pad:pad+H, pad:pad+W].astype(np.float32)


def apply_dose_noise(signal_norm, dose_e_per_px, dqe=0.8, readout_e=1.5, rng=None):
    if rng is None:
        rng = np.random.default_rng()
    lam = np.clip(signal_norm, 0, None) * float(dose_e_per_px) * float(dqe)
    counts = rng.poisson(lam).astype(np.float32)
    if readout_e > 0:
        counts = counts + rng.normal(0.0, readout_e, counts.shape).astype(np.float32)
    return np.clip(counts, 0, None)


def apply_scan_distortion(img, drift_px_xy=(0.0, 0.0), line_jitter_px=0.0, rng=None):
    if rng is None:
        rng = np.random.default_rng()
    H, W = img.shape
    dx_total, dy_total = drift_px_xy
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    frac = (yy / max(1.0, H - 1.0))
    src_x = xx - dx_total * frac
    src_y = yy - dy_total * frac
    if line_jitter_px > 0:
        jit = rng.normal(0.0, line_jitter_px, size=H).astype(np.float32)
        src_x = src_x + jit[:, None]
    x0 = np.floor(src_x).astype(np.int32); y0 = np.floor(src_y).astype(np.int32)
    x1 = x0 + 1; y1 = y0 + 1
    x0 = np.clip(x0, 0, W-1); x1 = np.clip(x1, 0, W-1)
    y0 = np.clip(y0, 0, H-1); y1 = np.clip(y1, 0, H-1)
    Ia = img[y0, x0]; Ib = img[y1, x0]; Ic = img[y0, x1]; Id = img[y1, x1]
    wa = (x1 - src_x)*(y1 - src_y); wb = (x1 - src_x)*(src_y - y0)
    wc = (src_x - x0)*(y1 - src_y); wd = (src_x - x0)*(src_y - y0)
    return (Ia*wa + Ib*wb + Ic*wc + Id*wd).astype(np.float32)


def thickness_contrast(projected_sum, mfp_scale):
    return 1.0 - np.exp(-np.clip(projected_sum, 0, None) / max(1e-6, mfp_scale))


def _render_atomic_columns(lattice, fov_nm, out_size, tilt_a_deg, tilt_b_deg,
                           thickness_nm=4.0, probe_nm=0.05, max_atoms=250000):
    """HAADF atomic-column image by PROJECTING real atoms (true Angstrom
    positions) along the tilted beam. Physically correct columns (no aliasing),
    and specimen tilt genuinely smears/splits them. Returns a normalized 2D image
    in [0,1], or None."""
    from .samples.base import tile_lattice_in_region
    fov_A = fov_nm * 10.0
    half_A = fov_A / 2.0
    depth_A = max(4.0, thickness_nm * 10.0)
    a1 = float(np.linalg.norm(lattice.real_vectors[0]))
    c_len = abs(float(lattice.real_vectors[2][2])) or a1
    est = (fov_A / a1) ** 2 * (depth_A / c_len) * max(1, len(lattice.basis))
    if est > max_atoms:                      # thin the z-slab (columns repeat in z)
        depth_A = max(a1, depth_A * max_atoms / est)
    pos, Z = tile_lattice_in_region(lattice, half_A * 1.15, depth_A)
    if len(pos) == 0:
        return None
    a = np.deg2rad(tilt_a_deg); b = np.deg2rad(tilt_b_deg)
    Rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    Ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    pos = pos @ (Ry @ Rx).T
    px = (pos[:, 0] + half_A) / fov_A * out_size
    py = (pos[:, 1] + half_A) / fov_A * out_size
    w = (Z.astype(np.float64)) ** 1.7        # HAADF Z-contrast
    m = (px >= 0) & (px < out_size) & (py >= 0) & (py < out_size)
    ix = px[m].astype(np.intp); iy = py[m].astype(np.intp)
    # fast scatter via bincount (np.add.at is ~100x slower for large arrays)
    flat = iy * out_size + ix
    img = np.bincount(flat, weights=w[m], minlength=out_size * out_size)
    img = img.reshape(out_size, out_size)
    try:
        from scipy.ndimage import gaussian_filter
        sigma_px = max(0.6, probe_nm / (fov_nm / out_size))
        img = gaussian_filter(img, sigma=sigma_px)
    except Exception:
        pass
    mx = img.max()
    return (img / mx).astype(np.float32) if mx > 0 else None


def kinematical_diffraction(lattice, out_size, tilt_a_deg, tilt_b_deg,
                            kv=200.0, camera_length_mm=800.0,
                            beamstop_radius_px=6.0, hkl_max=5,
                            thickness_nm=20.0, sigma_override=None,
                            spot_sigma_px=2.5, rng=None):
    """
    Kinematical diffraction with a thickness-driven relrod (v6 physics).

    The reflection intensity is structure_factor^2 * form_factor(g) * relrod(s),
    where the relrod is a sinc^2 in the excitation error s whose width is set by
    sample thickness (thin foil -> long relrod -> spots survive more tilt). This
    makes zone-axis patterns sharp and correct (square for cubic [001]), keeps the
    low-order net clean via the form-factor envelope, and lets tilting actually
    move between zone axes (the in-plane reflections fade as they leave the Bragg
    condition). `sigma_override` (1/A) bypasses the thickness->width mapping.
    """
    if rng is None:
        rng = np.random.default_rng()
    V = kv * 1e3
    lam = 12.2639 / np.sqrt(V * (1.0 + 0.97845e-6 * V))   # Angstrom
    k_mag = 2 * np.pi / lam                                # 1/A (2pi convention)
    recip = lattice.reciprocal_vectors()

    a = np.deg2rad(tilt_a_deg); b = np.deg2rad(tilt_b_deg)
    Rx = np.array([[1,0,0],[0,np.cos(a),-np.sin(a)],[0,np.sin(a),np.cos(a)]])
    Ry = np.array([[np.cos(b),0,np.sin(b)],[0,1,0],[-np.sin(b),0,np.cos(b)]])
    R = Ry @ Rx
    beam = R @ np.array([0.0, 0.0, 1.0])
    k0 = k_mag * beam

    # Relrod half-width (1/A): thin foil -> long relrod -> more tolerant of tilt.
    t_A = max(10.0, thickness_nm * 10.0)
    relrod_hw = 6.0 / t_A
    if sigma_override is not None:
        relrod_hw = float(sigma_override)

    raw = []
    for h in range(-hkl_max, hkl_max + 1):
        for k in range(-hkl_max, hkl_max + 1):
            for l in range(-hkl_max, hkl_max + 1):
                if h == 0 and k == 0 and l == 0:
                    continue
                G = h * recip[0] + k * recip[1] + l * recip[2]
                Gmag = np.linalg.norm(G)
                if Gmag < 1e-6:
                    continue
                F = lattice.structure_factor(h, k, l)
                I_F = (abs(F)) ** 2
                if I_F < 1e-3:
                    continue
                # excitation error (deviation from Ewald sphere)
                s = -(2 * np.dot(k0, G) + Gmag**2) / (2 * k_mag)
                # relrod: sinc^2 with thickness-set width
                relrod = (np.sinc(s / relrod_hw)) ** 2
                if relrod < 1e-3:
                    continue
                # atomic form-factor falloff with scattering angle (suppresses
                # high orders so the clean low-order net shows)
                g = Gmag / (2 * np.pi)
                form = np.exp(-1.5 * g * g)
                G_perp = G - np.dot(G, beam) * beam
                raw.append((G_perp[0], G_perp[1], I_F * form * relrod, Gmag))

    spots = []
    if raw:
        gperp = [np.hypot(r[0], r[1]) for r in raw if np.hypot(r[0], r[1]) > 1e-6]
        gmin = min(gperp) if gperp else 1.0
        base_radius = 0.18 * out_size
        cl_zoom = camera_length_mm / 800.0
        scale = (base_radius / gmin) * cl_zoom
        for gx, gy, intensity, _ in raw:
            spots.append((gx * scale, gy * scale, intensity))

    img = np.zeros((out_size, out_size), dtype=np.float32)
    cx = cy = out_size / 2.0
    yy, xx = np.mgrid[0:out_size, 0:out_size].astype(np.float32)
    if spots:
        max_I = max(s[2] for s in spots)
        for det_x, det_y, intensity in spots:
            px = cx + det_x; py = cy + det_y
            if not (0 <= px < out_size and 0 <= py < out_size):
                continue
            d2 = (xx - px)**2 + (yy - py)**2
            img += (intensity / max_I) * np.exp(-d2 / (2 * spot_sigma_px**2))
    d2c = (xx - cx)**2 + (yy - cy)**2
    img += 1.2 * np.exp(-d2c / (2 * (spot_sigma_px*1.3)**2))
    if beamstop_radius_px and beamstop_radius_px > 0:
        img[np.sqrt(d2c) <= beamstop_radius_px] = 0.0
    img = img - img.min()
    mx = img.max()
    if mx > 1e-6:
        img = img / mx
    return np.clip(img * 65535.0, 0, 65535).astype(np.float32)


# ============================================================================
# Local-region diffraction from atomic positions (item 6)
# ============================================================================
def diffraction_from_atoms(positions_A, atomic_numbers, out_size,
                           tilt_a_deg, tilt_b_deg,
                           kv=200.0, q_max_invA=4.0,
                           thickness_nm=20.0, camera_length_mm=800.0,
                           beamstop_radius_px=6.0, atom_cap=100000, rng=None):
    """
    Diffraction pattern computed directly from atomic positions. The pattern
    is |sum_j f_j(q) exp(2pi i q.r_j)|^2 evaluated on the Ewald sphere across
    a 2D detector grid. Locality lives upstream -- the caller passes only the
    atoms in the diffracting region, so stage motion changes the pattern.
    """
    if rng is None:
        rng = np.random.default_rng()
    N = positions_A.shape[0]
    if N == 0:
        # No atoms in region: return empty pattern
        return np.zeros((out_size, out_size), dtype=np.float32)
    if N > atom_cap:
        idx = rng.choice(N, atom_cap, replace=False)
        positions_A = positions_A[idx]
        atomic_numbers = atomic_numbers[idx]
        N = atom_cap

    V_acc = kv * 1e3
    lam = 12.2639 / np.sqrt(V_acc * (1.0 + 0.97845e-6 * V_acc))
    k_mag = 2 * np.pi / lam

    a = np.deg2rad(tilt_a_deg); b = np.deg2rad(tilt_b_deg)
    Rx = np.array([[1,0,0],[0,np.cos(a),-np.sin(a)],[0,np.sin(a),np.cos(a)]])
    Ry = np.array([[np.cos(b),0,np.sin(b)],[0,1,0],[-np.sin(b),0,np.cos(b)]])
    R = Ry @ Rx
    # Tilt convention (matches a real double-tilt holder):
    #   alpha = rotation about the HORIZONTAL (x) detector axis  -> Rx
    #   beta  = rotation about the VERTICAL   (y) detector axis  -> Ry
    # We rotate the SPECIMEN's reciprocal lattice by R and read it out on a FIXED
    # detector frame (lab x,y). Using a fixed frame (rather than a beam-derived
    # basis) is what makes alpha and beta act on perpendicular detector axes, as
    # on a real instrument. The beam is along +z; the Ewald-sphere curvature uses
    # q_z from the fixed detector (qx,qy).
    beam = np.array([0.0, 0.0, 1.0])
    e_x = np.array([1.0, 0.0, 0.0])
    e_y = np.array([0.0, 1.0, 0.0])

    # Compute q-grid resolution. Note the diffracting region is kept ~cubic by
    # the sample's get_atoms_in_region (isotropic shape transform); with that,
    # 64 samples resolve the reciprocal lattice cleanly without aliasing. A
    # non-cubic (column) region was what previously produced an off-axis cloud.
    grid = min(out_size, 64)
    qs = np.linspace(-q_max_invA, q_max_invA, grid, dtype=np.float32)
    qx, qy = np.meshgrid(qs, qs, indexing='xy')
    q_perp_sq = qx**2 + qy**2
    q_z = -q_perp_sq / (2 * k_mag)
    Nq = grid * grid
    q_3d = (qx[:, :, None].astype(np.float32) * e_x[None, None, :].astype(np.float32) +
            qy[:, :, None].astype(np.float32) * e_y[None, None, :].astype(np.float32) +
            q_z[:, :, None].astype(np.float32) * beam[None, None, :].astype(np.float32)
            ).reshape(Nq, 3)
    # Rotate the specimen by R (tilt), so a fixed detector sees the tilted lattice.
    positions_A = positions_A @ R.T
    positions_f32 = positions_A.astype(np.float32)
    chunk = max(64, min(Nq, int(2.5e7 / max(1, N))))
    A = np.zeros(Nq, dtype=np.complex64)
    q_mag = np.sqrt(q_perp_sq).reshape(Nq).astype(np.float32)
    unique_Z = np.unique(atomic_numbers)
    for start in range(0, Nq, chunk):
        end = min(Nq, start + chunk)
        qch = q_3d[start:end]
        for Z in unique_Z:
            pos_Z = positions_f32[atomic_numbers == Z]
            if len(pos_Z) == 0:
                continue
            phases = (2 * np.pi) * (qch @ pos_Z.T)
            amp = (np.cos(phases).sum(axis=1).astype(np.float32) +
                   1j * np.sin(phases).sum(axis=1).astype(np.float32))
            f = (Z * np.exp(-0.5 * q_mag[start:end] ** 2)).astype(np.float32)
            A[start:end] += f * amp.astype(np.complex64)

    I = (A.real**2 + A.imag**2).reshape(grid, grid)
    # Coherence damping from thickness (gentle high-q falloff)
    coh = np.exp(-q_perp_sq * (thickness_nm / 200.0))
    I = I * coh

    # Camera-length zoom: crop a centered region then upsample
    cl_zoom = camera_length_mm / 800.0
    if cl_zoom != 1.0:
        crop = max(8, int(grid / cl_zoom))
        if crop < grid:
            s0 = (grid - crop) // 2
            I = I[s0:s0+crop, s0:s0+crop]
            grid_eff = crop
        else:
            grid_eff = grid
    else:
        grid_eff = grid

    # Upsample to out_size
    if grid_eff != out_size:
        try:
            from scipy.ndimage import zoom
            I = zoom(I, out_size / grid_eff, order=1)
        except ImportError:
            rep = out_size / grid_eff
            yi = (np.arange(out_size) / rep).astype(int).clip(0, grid_eff - 1)
            xi = (np.arange(out_size) / rep).astype(int).clip(0, grid_eff - 1)
            I = I[yi][:, xi]
    # Direct (000) beam handling. The undiffracted beam is ~100x brighter than
    # the Bragg spots and would saturate the display, hiding the spots. We
    # normalize the pattern on the BRAGG spots (excluding the centre) and then
    # REMOVE the direct beam entirely (set the central disk to zero) -- like a
    # physical beam stop that blocks the undiffracted beam so only the diffracted
    # spots remain. The removed radius is beamstop_radius_px.
    yy, xx = np.mgrid[0:out_size, 0:out_size].astype(np.float32)
    cx = cy = out_size / 2.0
    rr = np.sqrt((yy-cy)**2 + (xx-cx)**2)
    center_mask = rr <= max(1.0, beamstop_radius_px)

    outside = ~center_mask
    I = I - (I[outside].min() if outside.any() else I.min())
    I = np.clip(I, 0, None)
    mx = float(I[outside].max()) if outside.any() else float(I.max())
    if mx > 1e-6:
        I = I / mx
    I = np.clip(I, 0, 1.0)
    # remove the direct beam (beam stop)
    I[center_mask] = 0.0
    return np.clip(I * 65535.0, 0, 65535).astype(np.float32)



# ============================================================================
# Simulated microscope state
# ============================================================================
@dataclass
class SimMicroscope:
    stage: Dict[str, float] = field(default_factory=lambda: {"x":0.0,"y":0.0,"z":0.0,"a":0.0,"b":0.0})
    beam: Dict[str, float]  = field(default_factory=lambda: {"x":0.0,"y":0.0,"current_pA":50.0,"voltage_kV":200.0})
    vacuum: float = 1e-6
    status: str = "Idle"
    holder_type: str = "DoubleTilt"
    mode: str = "IMG"
    diff: Dict[str, float] = field(default_factory=lambda: {
        "camera_length_mm": 800.0, "beamstop_radius_px": 6.0, "thickness_nm": 20.0,
        "aperture_um": 0.0, "depth_nm": 0.0,  # 0 = auto (use FOV / sample depth)
        "use_local_atoms": 1.0,  # 1=local-region from-atoms, 0=analytical kinematical
    })
    # NEW: specimen thickness selection (real-TEM thickness workflow). total = the
    # specimen's full physical thickness; working = the slab imaged through; z_start
    # = where that slab begins within the total (chosen by a seed at load time).
    thickness: Dict[str, float] = field(default_factory=lambda: {
        "total_nm": 100.0, "working_nm": 100.0, "z_start_nm": 0.0, "seed": 0,
    })
    # NEW: aberrations & optics
    optics: Dict[str, float] = field(default_factory=lambda: {"cs_mm": 1.0, "aperture_probe_px": 1.4})
    # NEW: drift state (accumulates over time)
    drift: Dict[str, float] = field(default_factory=lambda: {
        "vx_px_per_s": 0.0, "vy_px_per_s": 0.0,   # constant drift velocity
        "accum_x_px": 0.0, "accum_y_px": 0.0,      # accumulated offset
        "line_jitter_px": 0.0,
        "enabled": 0.0,
        "max_dt_s": 2.0,   # cap on per-frame elapsed time (idle-jump guard)
    })
    # NEW: beam damage + contamination (specimen-degradation effects)
    specimen: Dict[str, float] = field(default_factory=lambda: {
        # beam damage: cumulative dose above 'damage_dose_threshold' (e-/A^2)
        # progressively removes signal in the exposed region.
        "beam_damage_enabled": 0.0,
        "damage_dose_threshold": 3.0e4,    # e-/A^2 critical dose (moderately robust)
        "damage_rate": 1.0,                # contrast-loss speed for dose past threshold
        # contamination: carbon builds up where the beam dwells, darkening the
        # image and adding diffuse background to diffraction over time.
        "contamination_enabled": 0.0,
        "contamination_rate": 1.0,         # carbon build-up rate (0-5 typical)
    })


def default_haadf(detector_dict):
    detector_dict["haadf"] = {
        "size": 512, "exposure": 0.1, "binning": 1,
        "field_of_view_um": 20.0, "noise_sigma": 12.0,
        # magnification is kept in sync with field_of_view_um (mag = MAG_K/fov_m)
        "magnification": MAG_K / (20.0 * 1e-6),
        # NEW: dose model parameters
        "dwell_us": 10.0,        # per-pixel dwell time (microseconds)
        "dqe": 0.8,
        "readout_e": 1.5,
        "use_dose_model": 1.0,   # 1 = Poisson-dose, 0 = legacy gaussian
    }


def serialize_ndarray_b64(arr):
    raw = arr.tobytes(order="C")
    b64 = base64.b64encode(raw).decode("ascii")
    return {"__ndarray_b64__": b64, "shape": arr.shape, "dtype": str(arr.dtype)}


def sharpness_metric(img_u16):
    img = img_u16.astype(np.float32)
    gx = np.abs(img[:, 1:] - img[:, :-1]).mean()
    gy = np.abs(img[1:, :] - img[:-1, :]).mean()
    return float(gx + gy)


def bilinear_sample(img, y, x):
    H, W = img.shape
    x0 = np.floor(x).astype(np.int32); y0 = np.floor(y).astype(np.int32)
    x1 = x0 + 1; y1 = y0 + 1
    x0 = np.clip(x0, 0, W - 1); x1 = np.clip(x1, 0, W - 1)
    y0 = np.clip(y0, 0, H - 1); y1 = np.clip(y1, 0, H - 1)
    Ia = img[y0, x0].astype(np.float32); Ib = img[y1, x0].astype(np.float32)
    Ic = img[y0, x1].astype(np.float32); Id = img[y1, x1].astype(np.float32)
    wa = (x1 - x) * (y1 - y); wb = (x1 - x) * (y - y0)
    wc = (x - x0) * (y1 - y); wd = (x - x0) * (y - y0)
    return Ia*wa + Ib*wb + Ic*wc + Id*wd


# ============================================================================
# STEMServer
# ============================================================================
class STEMServer(object):
    def __init__(self, default_sample=None, D=64, H=768, W=768):
        # default_sample=None starts the server with NO specimen loaded: the
        # user must register a sample before imaging (mirrors inserting a
        # holder into a real instrument). Pass a name to preload one (tests,
        # notebook-style usage).
        print("STEMServer (DT v6) init")
        self.detectors = {}
        default_haadf(self.detectors)
        self.sim = SimMicroscope()
        self.command_log = []
        self.focus_plane_z_m = 0.0
        self._default_DHW = (D, H, W)
        self._default_sample = default_sample
        self._ready = False
        self._init_error = None
        self.vol = None
        self.vol_D = None
        self.current_sample_name = None
        self.current_sample = None
        self.sample_fov_um = 200.0
        self.sample_px_per_um = 1.0
        self.tilt_strength_px_per_slice = 0.35
        # thickness law scale (raw projected-sum units that give ~63% signal)
        self.mfp_scale = 2000.0
        self._last_acquire_t = time.time()
        # Specimen-degradation maps (sample-frame, low-res grids that accumulate
        # exposure). Allocated lazily per-sample in _ensure_specimen_maps().
        self._dose_map = None          # cumulative dose proxy (e-/A^2-ish)
        self._contam_map = None        # cumulative contamination thickness proxy
        self._specimen_grid = 128      # resolution of the maps

    def _ensure_specimen_maps(self):
        g = self._specimen_grid
        if self._dose_map is None or self._dose_map.shape != (g, g):
            self._dose_map = np.zeros((g, g), dtype=np.float32)
            self._contam_map = np.zeros((g, g), dtype=np.float32)

    def reset_specimen(self):
        """Clear accumulated beam damage and contamination (fresh specimen)."""
        self._dose_map = None
        self._contam_map = None
        self._ensure_specimen_maps()
        self._log("reset_specimen", {}, "cleared")
        return {"reset": True}

    def finish_init(self):
        try:
            samples.discover()
            avail = [s["name"] for s in samples.list_samples()]
            print(f"[DT] Registered samples: {avail}")
            if self._default_sample is not None:
                D, H, W = self._default_DHW
                self.load_sample(self._default_sample, D=D, H=H, W=W)
            self._ready = True
            print("[DT] Server ready"
                  + (f" (sample '{self.current_sample_name}' loaded)."
                     if self.current_sample_name else " (no sample registered)."))
        except Exception:
            self._init_error = traceback.format_exc()
            print("[DT] INIT FAILED:\n" + self._init_error)

    def is_ready(self):
        return {"ready": bool(self._ready),
                "error": (self._init_error if not self._ready else None),
                "sample": self.current_sample_name}

    def _calibrate_contrast(self):
        """
        Set mfp_scale so a typical projected column gives a mid-range signal,
        keeping the thickness-saturation curve in its responsive region rather
        than saturating everything to ~1.
        """
        # sample the projected sum on a coarse grid for speed
        sub = self.vol[:, ::8, ::8].sum(axis=0)
        med = float(np.median(sub))
        # choose scale so the median maps to ~0.4 signal: 1-exp(-med/scale)=0.4
        # => scale = med / -ln(0.6) = med / 0.5108
        self.mfp_scale = max(1.0, med / 0.5108)

    def _require_ready(self):
        if not self._ready:
            if self._init_error:
                raise RuntimeError(f"Sample init failed:\n{self._init_error}")
            raise RuntimeError("Sample is still loading. Call is_ready() to check.")
        if self.vol is None:
            raise RuntimeError(NO_SAMPLE_MSG)

    def _log(self, method, params, result=None):
        self.command_log.append({"t": time.time(), "method": method,
                                 "params": params, "result_preview": str(result)[:200]})

    def get_command_log(self, last_n=50):
        return self.command_log[-int(last_n):]

    def clear_command_log(self):
        self.command_log = []
        return 1

    # ---- sample registry ----
    def list_samples(self):
        r = samples.list_samples()
        self._log("list_samples", {}, f"{len(r)} samples")
        return r

    def get_current_sample(self):
        r = {"name": self.current_sample_name,
             "params": (self.current_sample.params if self.current_sample else None),
             "crystalline": bool(self.current_sample and self.current_sample.get_lattice() is not None)}
        self._log("get_current_sample", {}, r)
        return r

    def load_sample(self, name, params=None, D=None, H=None, W=None,
                    thickness_nm=None, thickness_seed=None):
        params = params or {}
        D0, H0, W0 = self._default_DHW
        D = int(D) if D is not None else D0
        H = int(H) if H is not None else H0
        W = int(W) if W is not None else W0
        sample = samples.get_sample(name, **params)
        print(f"[DT] Loading sample '{name}' ({D}x{H}x{W}) ...")
        prev_ready = self._ready
        self._ready = False
        try:
            self.vol = sample.generate_volume(D, H, W)
            self.vol_D = D
            self.current_sample_name = name
            self.current_sample = sample
            self.sample_fov_um = sample.sample_fov_um
            self.sample_px_per_um = W / self.sample_fov_um
            self.tilt_strength_px_per_slice = sample.tilt_strength_px_per_slice
            # ---- thickness selection (replicates real-TEM thickness workflow) ----
            # The specimen has a total physical thickness (sample.thickness_nm, e.g.
            # 100 nm). At load time you choose a WORKING thickness to image through,
            # and a SEED decides WHERE within the full thickness that slab sits --
            # mimicking how local specimen thickness varies and where you land on
            # the specimen is somewhat arbitrary. Environments may also set these.
            total_t = float(getattr(sample, "thickness_nm", 100.0))
            work_t = float(thickness_nm) if thickness_nm is not None else total_t
            work_t = max(1.0, min(work_t, total_t))
            seed = int(thickness_seed) if thickness_seed is not None else 0
            # deterministic z-start offset within [0, total - work]
            span = max(0.0, total_t - work_t)
            frac = (np.random.default_rng(seed).random() if span > 0 else 0.0)
            z_start = frac * span
            self.sim.thickness = {
                "total_nm": total_t,
                "working_nm": work_t,
                "z_start_nm": z_start,
                "seed": seed,
            }
            # tie the diffraction thickness (relrod model) to the working thickness
            self.sim.diff["thickness_nm"] = work_t
            self._calibrate_contrast()
            self._ready = True
            self._init_error = None
        except Exception:
            self._init_error = traceback.format_exc()
            self._ready = prev_ready
            raise
        r = {"loaded": name, "shape": [D, H, W], "params": sample.params,
             "thickness": dict(self.sim.thickness)}
        self._log("load_sample", {"name": name, "params": params,
                                  "thickness_nm": thickness_nm,
                                  "thickness_seed": thickness_seed}, r)
        print(f"[DT] Sample '{name}' loaded. thickness={self.sim.thickness}")
        return r

    def get_thickness(self):
        """Return the current specimen thickness selection (total / working /
        z-window start / seed), all in nm."""
        r = dict(getattr(self.sim, "thickness",
                         {"total_nm": 100.0, "working_nm": 100.0,
                          "z_start_nm": 0.0, "seed": 0}))
        self._log("get_thickness", {}, r)
        return r

    def set_thickness(self, thickness_nm=None, thickness_seed=None):
        """Re-choose the working thickness and/or the seed WITHOUT reloading the
        sample (e.g. to simulate navigating to a differently-thick region)."""
        th = getattr(self.sim, "thickness", None)
        if th is None or self.current_sample is None:
            raise RuntimeError(NO_SAMPLE_MSG)
        total_t = float(th["total_nm"])
        work_t = float(thickness_nm) if thickness_nm is not None else float(th["working_nm"])
        work_t = max(1.0, min(work_t, total_t))
        seed = int(thickness_seed) if thickness_seed is not None else int(th["seed"])
        span = max(0.0, total_t - work_t)
        frac = (np.random.default_rng(seed).random() if span > 0 else 0.0)
        self.sim.thickness = {"total_nm": total_t, "working_nm": work_t,
                              "z_start_nm": frac * span, "seed": seed}
        self.sim.diff["thickness_nm"] = work_t
        self._log("set_thickness", {"thickness_nm": thickness_nm,
                                    "thickness_seed": thickness_seed},
                  dict(self.sim.thickness))
        return dict(self.sim.thickness)

    # ---- beam ----
    def get_beam(self):
        b = self.sim.beam
        r = {k: float(b.get(k, 0.0)) for k in ["x","y","current_pA","voltage_kV"]}
        self._log("get_beam", {}, r)
        return r

    def set_beam(self, beam_settings, relative=False):
        keys = ["x","y","current_pA","voltage_kV"]
        if not isinstance(beam_settings, dict):
            raise ValueError("beam_settings must be a dict")
        for k in keys:
            if k in beam_settings and beam_settings[k] is not None:
                if relative:
                    self.sim.beam[k] = float(self.sim.beam.get(k, 0.0)) + float(beam_settings[k])
                else:
                    self.sim.beam[k] = float(beam_settings[k])
        r = {"new_beam": {k: float(self.sim.beam.get(k, 0.0)) for k in keys}, "relative": bool(relative)}
        self._log("set_beam", {"beam_settings": beam_settings, "relative": relative}, r)
        return r

    # ---- optics (NEW: aberrations) ----
    def get_optics(self):
        o = self.sim.optics
        r = {"cs_mm": float(o["cs_mm"]), "aperture_probe_px": float(o["aperture_probe_px"])}
        self._log("get_optics", {}, r)
        return r

    def set_optics(self, **kwargs):
        if "cs_mm" in kwargs and kwargs["cs_mm"] is not None:
            self.sim.optics["cs_mm"] = float(kwargs["cs_mm"])
        if "aperture_probe_px" in kwargs and kwargs["aperture_probe_px"] is not None:
            self.sim.optics["aperture_probe_px"] = float(kwargs["aperture_probe_px"])
        r = self.get_optics()
        self._log("set_optics", kwargs, r)
        return r

    # ---- drift (NEW) ----
    def get_drift(self):
        d = self.sim.drift
        r = {k: float(d[k]) for k in d}
        self._log("get_drift", {}, r)
        return r

    def set_drift(self, vx_px_per_s=None, vy_px_per_s=None, line_jitter_px=None,
                  enabled=None, reset_accum=False,
                  vx_nm_per_s=None, vy_nm_per_s=None, line_jitter_nm=None):
        """Set stage drift. PREFER the physical nm/s interface (vx_nm_per_s,
        vy_nm_per_s) and line_jitter_nm -- these are TEM-realistic units and are
        converted to the internal volume-pixel rates using the current volume
        scale. Realistic magnitudes: excellent < 0.2 nm/s, good ~0.5, moderate ~2,
        poor/just-inserted ~5, and ~10 nm/s is about the worst a usable session
        shows. The px/s arguments remain for backward compatibility."""
        d = self.sim.drift
        # volume pixels per nm (accum/velocities live in volume-pixel space)
        px_per_nm = float(getattr(self, "sample_px_per_um", 38.4)) / 1000.0
        if vx_nm_per_s is not None: d["vx_px_per_s"] = float(vx_nm_per_s) * px_per_nm
        if vy_nm_per_s is not None: d["vy_px_per_s"] = float(vy_nm_per_s) * px_per_nm
        if line_jitter_nm is not None: d["line_jitter_px"] = float(line_jitter_nm) * px_per_nm
        if vx_px_per_s is not None: d["vx_px_per_s"] = float(vx_px_per_s)
        if vy_px_per_s is not None: d["vy_px_per_s"] = float(vy_px_per_s)
        if line_jitter_px is not None: d["line_jitter_px"] = float(line_jitter_px)
        if enabled is not None: d["enabled"] = 1.0 if enabled else 0.0
        if reset_accum:
            d["accum_x_px"] = 0.0; d["accum_y_px"] = 0.0
            self._last_acquire_t = time.time()
        r = {k: float(d[k]) for k in d}
        # report physical rates too, for the GUI
        nm_per_px = (1.0 / px_per_nm) if px_per_nm > 0 else 26.04
        r["vx_nm_per_s"] = d["vx_px_per_s"] * nm_per_px
        r["vy_nm_per_s"] = d["vy_px_per_s"] * nm_per_px
        self._log("set_drift", {"vx_nm_per_s": vx_nm_per_s, "vy_nm_per_s": vy_nm_per_s,
                                "vx_px_per_s": vx_px_per_s, "vy_px_per_s": vy_px_per_s}, r)
        return r

    # ---- specimen degradation (NEW: beam damage + contamination) ----
    def get_specimen(self):
        s = self.sim.specimen
        r = {k: float(s[k]) for k in s}
        # report a summary of accumulated maps
        if self._dose_map is not None:
            r["max_accumulated_dose"] = float(self._dose_map.max())
            r["max_contamination"] = float(self._contam_map.max())
        self._log("get_specimen", {}, r)
        return r

    def set_specimen(self, **kwargs):
        s = self.sim.specimen
        for key in ["damage_dose_threshold", "damage_rate", "contamination_rate"]:
            if kwargs.get(key) is not None:
                s[key] = float(kwargs[key])
        if kwargs.get("beam_damage_enabled") is not None:
            s["beam_damage_enabled"] = 1.0 if kwargs["beam_damage_enabled"] else 0.0
        if kwargs.get("contamination_enabled") is not None:
            s["contamination_enabled"] = 1.0 if kwargs["contamination_enabled"] else 0.0
        r = self.get_specimen()
        self._log("set_specimen", kwargs, r)
        return r

    # ---- mode / diffraction ----
    def get_mode(self):
        r = {"mode": str(self.sim.mode)}
        self._log("get_mode", {}, r)
        return r

    def set_mode(self, mode="IMG"):
        m = str(mode).upper().strip()
        if m not in ("IMG", "DIFF", "EELS"):
            raise ValueError("mode must be 'IMG', 'DIFF', or 'EELS'")
        self.sim.mode = m
        r = {"mode": m}
        self._log("set_mode", {"mode": mode}, r)
        return r

    def acquire_spectrum(self, ev_min=0.0, ev_max=1000.0, n_channels=1024,
                         cx_um=None, cy_um=None):
        """Acquire a single-spot EELS spectrum (probe parked at one position).

        This mirrors the 4D-STEM/EELS acquisition geometry: the focused probe sits
        at ONE point and a 1-D spectrum is recorded. The spectrum here is a
        physically-structured DUMMY (not quantitatively accurate): a zero-loss peak
        at 0 eV, a plasmon peak in the low-loss region, and composition-aware
        core-loss edges placed at approximate ionization energies of the elements
        actually under the probe (from the sample's atoms). Intensities scale with
        the working specimen thickness. The value is the WORKFLOW and the API
        surface -- swap in a real EELS backend on a microscope later.

        Returns {"energy_ev": [...], "intensity": [...], "edges": [{...}], ...}.
        """
        self._require_ready()
        E = np.linspace(float(ev_min), float(ev_max), int(n_channels)).astype(np.float64)
        spec = np.zeros_like(E)

        # thickness scaling (thicker -> stronger plasmon relative to zero-loss)
        th = getattr(self.sim, "thickness", {"working_nm": 100.0, "total_nm": 100.0})
        t_nm = float(th.get("working_nm", 100.0))
        t_over_lambda = t_nm / 100.0   # ~ t/inelastic-mean-free-path (order 1)

        # (1) zero-loss peak (Gaussian at 0 eV)
        zlp_w = 0.8
        spec += np.exp(-0.5 * (E / zlp_w) ** 2)

        # (2) plasmon peak(s): position depends loosely on material; single plasmon
        #     around ~15-25 eV, amplitude grows with thickness (multiple scattering)
        Zset = self._atoms_under_probe_Z(cx_um, cy_um)
        Ep = 15.0 + 0.10 * (float(np.mean(Zset)) if len(Zset) else 15.0)  # crude
        plasmon_amp = 0.35 * t_over_lambda
        spec += plasmon_amp * np.exp(-0.5 * ((E - Ep) / 3.0) ** 2)
        # double plasmon at 2*Ep for thicker specimens
        spec += 0.4 * plasmon_amp**2 * np.exp(-0.5 * ((E - 2 * Ep) / 4.0) ** 2)

        # (3) core-loss edges for the elements under the probe. Approximate edge
        #     onset energies (eV) for a few common elements/edges.
        EDGES = {
            6:  [("C-K", 284)], 8: [("O-K", 532)], 12: [("Mg-K", 1305)],
            13: [("Al-K", 1560)], 14: [("Si-K", 1839)], 22: [("Ti-L", 456)],
            26: [("Fe-L", 708)], 29: [("Cu-L", 931)], 79: [("Au-M", 2206)],
        }
        edges_out = []
        for Z in Zset:
            for (name, e0) in EDGES.get(int(Z), []):
                if E[0] <= e0 <= E[-1]:
                    # saw-tooth edge: sharp onset then ~E^-r decay
                    amp = 0.08 * t_over_lambda
                    tail = np.where(E >= e0, amp * ((e0 / np.clip(E, e0, None)) ** 3), 0.0)
                    spec += tail
                    edges_out.append({"label": name, "onset_ev": e0, "Z": int(Z)})

        # gentle decreasing background (power law) + Poisson-like noise
        bg = 0.02 * np.clip((E + 5.0), 1, None) ** (-0.3)
        spec = spec + bg
        rng = np.random.default_rng(0)
        spec = spec * (1.0 + 0.02 * rng.standard_normal(spec.shape))
        spec = np.clip(spec, 0, None)

        r = {"energy_ev": E.tolist(), "intensity": spec.tolist(),
             "edges": edges_out, "zlp_ev": 0.0, "plasmon_ev": float(Ep),
             "thickness_nm": t_nm, "elements_Z": sorted(int(z) for z in Zset)}
        self._log("acquire_spectrum",
                  {"ev_min": ev_min, "ev_max": ev_max, "n_channels": n_channels},
                  f"EELS spectrum ({len(E)} ch, edges={[e['label'] for e in edges_out]})")
        return r

    def _atoms_under_probe_Z(self, cx_um=None, cy_um=None):
        """Set of atomic numbers present in a small region under the probe, from
        the current sample. Falls back to a light element if none available."""
        s = getattr(self, "current_sample", None)
        if s is None or not hasattr(s, "get_atoms_in_region"):
            return np.array([6])   # carbon fallback
        try:
            cx = 0.0 if cx_um is None else float(cx_um)
            cy = 0.0 if cy_um is None else float(cy_um)
            _, Z = s.get_atoms_in_region(cx, cy, 0.01, 10.0)
            Z = np.asarray(Z)
            return np.unique(Z) if Z.size else np.array([6])
        except Exception:
            return np.array([6])

    def get_diffraction_settings(self):
        d = self.sim.diff
        r = {"camera_length_mm": float(d["camera_length_mm"]),
             "beamstop_radius_px": float(d["beamstop_radius_px"]),
             "thickness_nm": float(d.get("thickness_nm", 20.0)),
             "aperture_um": float(d.get("aperture_um", 0.0)),
             "depth_nm": float(d.get("depth_nm", 0.0)),
             "use_local_atoms": float(d.get("use_local_atoms", 1.0))}
        self._log("get_diffraction_settings", {}, r)
        return r

    def set_diffraction_settings(self, **kwargs):
        if kwargs.get("camera_length_mm") is not None:
            self.sim.diff["camera_length_mm"] = float(kwargs["camera_length_mm"])
        if kwargs.get("beamstop_radius_px") is not None:
            self.sim.diff["beamstop_radius_px"] = float(kwargs["beamstop_radius_px"])
        if kwargs.get("thickness_nm") is not None:
            self.sim.diff["thickness_nm"] = float(kwargs["thickness_nm"])
        if kwargs.get("aperture_um") is not None:
            self.sim.diff["aperture_um"] = float(kwargs["aperture_um"])
        if kwargs.get("depth_nm") is not None:
            self.sim.diff["depth_nm"] = float(kwargs["depth_nm"])
        if kwargs.get("use_local_atoms") is not None:
            self.sim.diff["use_local_atoms"] = 1.0 if kwargs["use_local_atoms"] else 0.0
        r = self.get_diffraction_settings()
        self._log("set_diffraction_settings", kwargs, r)
        return r

    # ---- detectors / stage ----
    def get_detectors(self):
        r = list(self.detectors.keys())
        self._log("get_detectors", {}, r)
        return r

    def device_settings(self, device, **args):
        if device not in self.detectors:
            return 0
        # Magnification and field-of-view are two views of the same quantity
        # (mag = MAG_K / fov_metres). Accept either; keep both consistent.
        if "magnification" in args and args["magnification"] is not None:
            fov_um = mag_to_fov_um(float(args["magnification"]))
            args["field_of_view_um"] = fov_um
            self.detectors[device]["magnification"] = float(args["magnification"])
        for k, v in args.items():
            if k in self.detectors[device]:
                self.detectors[device][k] = v
        # If FOV was set directly, refresh the derived magnification too.
        if "field_of_view_um" in args and args["field_of_view_um"] is not None:
            self.detectors[device]["magnification"] = fov_um_to_mag(
                float(args["field_of_view_um"]))
        self._log("device_settings", {"device": device, **args}, 1)
        return 1

    def get_magnification(self, device="haadf"):
        if device not in self.detectors:
            return 0
        fov_um = float(self.detectors[device].get("field_of_view_um", 20.0))
        mag = fov_um_to_mag(fov_um)
        r = {"magnification": mag, "field_of_view_um": fov_um}
        self._log("get_magnification", {"device": device}, r)
        return r

    def set_magnification(self, magnification, device="haadf"):
        if device not in self.detectors:
            return 0
        fov_um = mag_to_fov_um(float(magnification))
        self.detectors[device]["field_of_view_um"] = fov_um
        self.detectors[device]["magnification"] = float(magnification)
        r = {"magnification": float(magnification), "field_of_view_um": fov_um}
        self._log("set_magnification", {"magnification": magnification, "device": device}, r)
        return r

    # Discrete acquisition resolutions (pixels per side), like a real STEM scan /
    # camera: a small set of fixed windows. Higher resolution -> smaller pixel for
    # the same field of view -> finer detail (e.g. atomic columns) resolves at a
    # LOWER magnification, at the cost of longer acquisition (more scan points).
    ALLOWED_RESOLUTIONS = (512, 1024, 2048)

    def get_resolution(self, device="haadf"):
        r = {"resolution_px": int(self.detectors[device]["size"]),
             "allowed": list(self.ALLOWED_RESOLUTIONS)}
        self._log("get_resolution", {"device": device}, r)
        return r

    def set_resolution(self, resolution_px, device="haadf"):
        """Select one of the fixed acquisition resolution windows (pixels/side)."""
        px = int(resolution_px)
        if px not in self.ALLOWED_RESOLUTIONS:
            raise ValueError(
                f"resolution_px must be one of {list(self.ALLOWED_RESOLUTIONS)} "
                f"(got {px}). Higher = finer detail resolvable at lower mag, but slower.")
        self.detectors[device]["size"] = px
        r = {"resolution_px": px, "allowed": list(self.ALLOWED_RESOLUTIONS)}
        self._log("set_resolution", {"resolution_px": resolution_px, "device": device}, r)
        return r

    def get_stage(self):
        st = self.sim.stage
        r = [st["x"], st["y"], st["z"], st["a"], st["b"]]
        self._log("get_stage", {}, r)
        return r

    # Stage travel limits (safety interlock). x/y/z in METRES, a/b in DEGREES.
    # A move whose TARGET exceeds any limit is rejected outright (nothing moves),
    # mimicking a hardware soft-limit that protects the stage/specimen/pole-piece.
    STAGE_LIMITS = {
        "x": 1.5e-3,   # +/- 1.5 mm
        "y": 1.5e-3,   # +/- 1.5 mm
        "z": 1.0e-3,   # +/- 1.0 mm
        "a": 30.0,     # +/- 30 degrees
        "b": 30.0,     # +/- 30 degrees
    }

    def get_stage_limits(self):
        """Soft-limit travel ranges (symmetric, so the value is +/- per axis)."""
        r = {k: float(v) for k, v in self.STAGE_LIMITS.items()}
        self._log("get_stage_limits", {}, r)
        return r

    def set_stage(self, stage_positions, relative=True):
        keys = ["x","y","z","a","b"]
        move = {k: 0.0 for k in keys}
        if isinstance(stage_positions, dict):
            for k in keys:
                if k in stage_positions and stage_positions[k] is not None:
                    move[k] = float(stage_positions[k])
        elif isinstance(stage_positions, (list, tuple)):
            for i, k in enumerate(keys):
                if i < len(stage_positions) and stage_positions[i] is not None:
                    move[k] = float(stage_positions[i])
        else:
            raise ValueError("stage_positions must be dict or list/tuple")

        # Compute the intended target and check it against the soft limits BEFORE
        # applying anything. Reject the whole move if any axis is out of range.
        target = {}
        for k in keys:
            target[k] = (self.sim.stage[k] + move[k]) if relative else move[k]
        violations = []
        for k in keys:
            lim = self.STAGE_LIMITS[k]
            if abs(target[k]) > lim + 1e-12:
                if k in ("x", "y", "z"):
                    violations.append(
                        f"{k}={target[k]*1e3:+.3f} mm exceeds +/-{lim*1e3:.3f} mm")
                else:
                    violations.append(
                        f"{k}={target[k]:+.2f} deg exceeds +/-{lim:.1f} deg")
        if violations:
            msg = ("Stage move rejected by safety limits: " + "; ".join(violations)
                   + ". Stage did not move.")
            self._log("set_stage", {"stage_positions": stage_positions,
                                     "relative": relative}, {"rejected": msg})
            raise ValueError(msg)

        for k in keys:
            self.sim.stage[k] = target[k]
        r = {"new_stage": [self.sim.stage[k] for k in keys], "relative": bool(relative)}
        self._log("set_stage", {"stage_positions": stage_positions, "relative": relative}, r)
        return r

    # ---- imaging (items 1-4) ----
    def _render_camera_image_u16(self, device, for_autofocus=False):
        self._require_ready()
        det = self.detectors[device]
        out_size = int(det["size"])
        fov_um = float(det["field_of_view_um"])

        b = self.sim.beam
        current_pA = float(b.get("current_pA", 50.0))
        voltage_kV = float(b.get("voltage_kV", 200.0))

        sx_um = self.sim.stage["x"] * 1e6
        sy_um = self.sim.stage["y"] * 1e6
        W = self.vol.shape[2]; H = self.vol.shape[1]
        cx = (0.5 * W + (sx_um * self.sample_px_per_um)) % W
        cy = (0.5 * H + (sy_um * self.sample_px_per_um)) % H

        # Item 3: update accumulated drift BEFORE choosing the sampling center, so
        # successive frames are translated relative to one another. (Skip during
        # autofocus so scoring is stable.)
        intra_dx = intra_dy = 0.0
        if not for_autofocus and self.sim.drift.get("enabled", 0.0) >= 0.5:
            now = time.time()
            # cap dt so that a long idle gap (e.g. the sample sits loaded while the
            # user reads the panel, then acquires) does not teleport the field in a
            # single huge jump -- on a real scope you'd re-center before starting.
            # Live/continuous acquisition sees smooth, physically-correct drift.
            dt = max(0.0, now - self._last_acquire_t)
            dt = min(dt, float(self.sim.drift.get("max_dt_s", 2.0)))
            self._last_acquire_t = now
            self.sim.drift["accum_x_px"] += self.sim.drift["vx_px_per_s"] * dt
            self.sim.drift["accum_y_px"] += self.sim.drift["vy_px_per_s"] * dt
            # accumulated offset shifts the whole frame (between-frame drift).
            # The sample is GENERATED over a large range (generation_range_um), so
            # shifting the sampling window reveals adjacent, still-generated
            # specimen -- as on a real instrument where drift moves you to a nearby
            # region, not into blackness. We do NOT wrap modulo the volume (which
            # would jump to the far edge / vacuum); we clamp so the window stays
            # over generated specimen.
            cx = float(cx + self.sim.drift["accum_x_px"])
            cy = float(cy + self.sim.drift["accum_y_px"])
            margin = 0.5 * fov_um * self.sample_px_per_um + 2
            cx = min(max(cx, margin), W - margin)
            cy = min(max(cy, margin), H - margin)
            # intra-frame drift (shear within one frame) computed from frame time
            frame_t = float(det["dwell_us"]) * 1e-6 * out_size * out_size
            intra_dx = self.sim.drift["vx_px_per_s"] * frame_t
            intra_dy = self.sim.drift["vy_px_per_s"] * frame_t

        half = 0.5 * fov_um * self.sample_px_per_um
        xs = np.linspace(cx - half, cx + half, out_size, dtype=np.float32)
        ys = np.linspace(cy - half, cy + half, out_size, dtype=np.float32)
        Y0, X0 = np.meshgrid(ys, xs, indexing="ij")

        a_deg = float(self.sim.stage.get("a", 0.0))
        b_deg = float(self.sim.stage.get("b", 0.0))
        sa = np.tan(np.deg2rad(a_deg)) * self.tilt_strength_px_per_slice
        sb = np.tan(np.deg2rad(b_deg)) * self.tilt_strength_px_per_slice

        D = self.vol_D
        z0 = (D - 1) * 0.5
        proj = np.zeros((out_size, out_size), dtype=np.float32)
        for z in range(D):
            dz = (z - z0)
            Xq = X0 - sb * dz
            Yq = Y0 - sa * dz
            proj += bilinear_sample(self.vol[z], Yq, Xq)

        # Item 4: thickness saturation + Z-contrast-ish nonlinearity already
        # baked into per-sample intensities. Convert raw sum -> scattering frac.
        # Scale the projected mass-thickness by the WORKING thickness fraction:
        # a thinner imaged slab passes fewer scatterers, so (in HAADF) less signal.
        th = getattr(self.sim, "thickness", None)
        if th is not None and float(th.get("total_nm", 0)) > 0:
            proj = proj * (float(th["working_nm"]) / float(th["total_nm"]))
        signal = thickness_contrast(proj, self.mfp_scale)  # in [0,1)

        # Item 2: PSF convolution (defocus + aberrations)
        dz_um = (self.sim.stage["z"] - self.focus_plane_z_m) * 1e6
        defocus_nm = dz_um * 1000.0
        # Physical pixel size so defocus blur scales correctly with FOV. A wide
        # FOV means each pixel covers more sample, so a given defocus blurs fewer
        # pixels; a narrow FOV resolves the blur. Without this the defocus_px term
        # saturated instantly and the autofocus curve was flat.
        nm_per_px = (fov_um * 1000.0) / max(1, out_size)
        psf = make_psf(defocus_nm,
                       cs_mm=float(self.sim.optics["cs_mm"]),
                       aperture_probe_px=float(self.sim.optics["aperture_probe_px"]),
                       kv=voltage_kV, pixel_nm=nm_per_px)
        signal = convolve2d_fft(signal, psf)
        signal = np.clip(signal, 0, None)

        # Resolution limit tied to the sample's INHERENT length scale. Each sample
        # declares `feature_scale_nm` (the size of its finest meaningful detail:
        # atomic-column spacing for crystals, particle size for nanoparticles). If
        # the current pixel size (set by FOV / magnification) is coarser than that
        # scale, the fine detail cannot be resolved -- so we blur it away in
        # proportion to how far under-resolved it is. Consequence: you must raise
        # magnification (shrink the FOV) to see the structure, exactly as on a real
        # instrument, and at high mag drift/dose then dominate.
        feat_nm = float(getattr(self.current_sample, "feature_scale_nm", 0.0) or 0.0)
        if feat_nm > 0.0:
            # need ~2 px across a feature to resolve it (Nyquist-ish)
            needed_nm_per_px = feat_nm / 2.0
            under = nm_per_px / max(1e-9, needed_nm_per_px)
            if under > 1.0:
                # blur sigma (in px) grows as we go further below the resolution
                # needed for this sample's features; capped so it stays finite.
                sigma_px = min(6.0, 0.5 * (under - 1.0))
                if sigma_px > 0.15:
                    from scipy.ndimage import gaussian_filter
                    signal = gaussian_filter(signal, sigma=sigma_px).astype(np.float32)

        # High-resolution atomic columns for crystalline samples. A single crystal
        # is a featureless slab at low/moderate magnification; only when the FOV is
        # small enough to resolve the atomic-column spacing do columns appear -- as
        # on a real HAADF instrument. We render the columns by PROJECTING the real
        # atoms (true Angstrom positions from the lattice) along the TILTED beam,
        # rather than synthesizing sinusoidal fringes. This (a) avoids the moire /
        # aliasing that a pixel-space fringe pattern produces near Nyquist, (b) puts
        # the columns at the correct spacing, and (c) makes specimen tilt (alpha/beta)
        # genuinely smear/split the columns, as it does physically. Columns are only
        # drawn when they are actually resolvable (spacing >= ~3.5 px); below that we
        # keep the clean uniform slab (no aliased grid).
        lat = getattr(self.current_sample, "lattice", None)
        if lat is not None and nm_per_px > 0:
            try:
                a1_A = float(np.linalg.norm(lat.real_vectors[0]))   # Angstrom
                d_nm = a1_A / 10.0
                period_px = d_nm / nm_per_px
                if period_px >= 3.5:   # only when cleanly resolvable (no aliasing)
                    a_deg2 = float(self.sim.stage.get("a", 0.0))
                    b_deg2 = float(self.sim.stage.get("b", 0.0))
                    cols = _render_atomic_columns(
                        lat, fov_um * 1000.0, out_size, a_deg2, b_deg2)
                    if cols is not None:
                        # blend columns into the slab signal where the sample exists
                        local = np.clip(signal / (signal.max() + 1e-6), 0, 1)
                        # ramp contrast in as columns become well-resolved
                        w = float(np.clip((period_px - 3.5) / 4.0, 0.0, 1.0))
                        cols = cols / (cols.max() + 1e-6)
                        signal = signal * (1.0 - 0.6 * w * local) + \
                                 signal.max() * 0.6 * w * cols * local
                        signal = np.clip(signal, 0, None)
            except Exception:
                pass

        # voltage affects contrast slightly
        voltage_scale = max(0.1, min(3.0, voltage_kV / 200.0))
        signal = signal * (1.0 / (0.85 + 0.15 * voltage_scale))

        # --- Specimen degradation: beam damage + contamination (review 2) ---
        # Accumulate exposure in the region currently under the beam, then apply
        # the cumulative effect. Skipped during autofocus so it doesn't corrupt
        # focus scoring (though damage during AF is modeled separately by passing
        # for_autofocus and still reading the current maps).
        sp = self.sim.specimen
        damage_on = float(sp.get("beam_damage_enabled", 0.0)) >= 0.5
        contam_on = float(sp.get("contamination_enabled", 0.0)) >= 0.5
        if damage_on or contam_on:
            self._ensure_specimen_maps()
            g = self._specimen_grid
            # Map the current FOV window to a sub-rectangle of the specimen grid.
            # Stage position determines the window center in normalized [0,1].
            fov_frac = min(1.0, fov_um / max(1e-6, self.sample_fov_um))
            cxn = 0.5 + (sx_um / max(1e-6, self.sample_fov_um))
            cyn = 0.5 + (sy_um / max(1e-6, self.sample_fov_um))
            half_f = 0.5 * fov_frac
            gx0 = int(np.clip((cxn - half_f) * g, 0, g-1))
            gx1 = int(np.clip((cxn + half_f) * g, 0, g-1)) + 1
            gy0 = int(np.clip((cyn - half_f) * g, 0, g-1))
            gy1 = int(np.clip((cyn + half_f) * g, 0, g-1)) + 1
            # Exposure increment per acquisition, in REAL electrons/A^2 (the unit
            # damage_dose_threshold is expressed in). This correctly depends on
            # probe current, dwell time, AND the pixel size on the specimen, which
            # is set by FOV and RESOLUTION: dose = electrons_per_pixel / pixel_area,
            # pixel_area = (FOV/resolution)^2. So a smaller FOV or a higher
            # resolution concentrates dose and damages faster -- as on a real
            # instrument. (Earlier builds used an arbitrary unit that ignored this.)
            _dwell_s = float(det.get("dwell_us", 20.0)) * 1e-6
            _e_per_px = (current_pA * 1e-12 / 1.602e-19) * _dwell_s
            _pix_nm = (fov_um * 1000.0) / max(1, out_size)      # nm per acquisition pixel
            _pix_A2 = max(1e-6, (_pix_nm * 10.0) ** 2)          # A^2 per pixel
            inc = _e_per_px / _pix_A2                            # e-/A^2 added this frame
            if not for_autofocus and (gx1 > gx0) and (gy1 > gy0):
                if damage_on:
                    self._dose_map[gy0:gy1, gx0:gx1] += inc
                if contam_on:
                    # contamination grows with exposure (per-frame dwell-dose), scaled
                    # by the contamination_rate; independent of the damage threshold.
                    self._contam_map[gy0:gy1, gx0:gx1] += (inc / 3.0e3) * float(sp.get("contamination_rate", 1.0))
            from scipy.ndimage import zoom as _zoom
            def _patch_to_out(maparr):
                patch = maparr[gy0:gy1, gx0:gx1]
                if patch.size == 0:
                    return np.zeros((out_size, out_size), dtype=np.float32)
                zy = out_size / patch.shape[0]; zx = out_size / patch.shape[1]
                return _zoom(patch, (zy, zx), order=1)[:out_size, :out_size]
            # Two DISTINCT effects, applied after dose-model renormalization
            # (per-frame max-normalization would otherwise cancel a uniform change):
            #   - Beam DAMAGE: mass loss / sputtering removes scatterers, so the
            #     HAADF signal DROPS -> multiplicative attenuation (->0), darker.
            #   - CONTAMINATION: carbon builds up where the beam dwells, ADDING
            #     projected mass-thickness. HAADF signal scales with mass-thickness,
            #     so contaminated regions get BRIGHTER -> additive brightening.
            # 1.0 = pristine for the damage factor; 0.0 = none for contam brighten.
            self._degradation_factor = np.ones((out_size, out_size), dtype=np.float32)
            self._contam_brighten = None
            if damage_on:
                dose_patch = _patch_to_out(self._dose_map)
                thr = float(sp.get("damage_dose_threshold", 3e4))
                rate = float(sp.get("damage_rate", 1.0))
                # Gradual contrast loss once cumulative dose exceeds the critical
                # dose. Use the LOG of the dose ratio so damage progresses smoothly
                # over many frames (a few % to tens of % per frame) rather than
                # collapsing the instant the threshold is passed. Real dose can be
                # >> threshold at small FOV/high dose, so a linear ratio would
                # saturate immediately; log keeps it controllable and realistic.
                ratio = np.clip(dose_patch / max(1.0, thr), 1.0, None)
                excess = np.log10(ratio)                       # 0 at threshold, 1 at 10x
                self._degradation_factor *= np.exp(-rate * excess).astype(np.float32)
            if contam_on:
                contam_patch = _patch_to_out(self._contam_map)
                # fraction of "full" contamination in [0,1); brightening grows with
                # accumulated carbon. Applied as an additive HAADF signal increase.
                contam_frac = 1.0 - np.exp(-0.004 * contam_patch)
                self._contam_brighten = (contam_frac * 22000.0).astype(np.float32)
            # Damage reduces electrons pre-noise (correct noise statistics); the
            # contamination brightening is applied post-normalization below.
            signal = signal * self._degradation_factor
        else:
            self._degradation_factor = None
            self._contam_brighten = None

        rng = np.random.default_rng(int(time.time() * 1e6) % (2**32))

        # Item 3: intra-frame drift shear + line jitter (offset already applied
        # to the sampling center above).
        if not for_autofocus and self.sim.drift.get("enabled", 0.0) >= 0.5:
            if abs(intra_dx) > 1e-6 or abs(intra_dy) > 1e-6 or self.sim.drift["line_jitter_px"] > 0:
                signal = apply_scan_distortion(
                    signal,
                    drift_px_xy=(intra_dx, intra_dy),
                    line_jitter_px=float(self.sim.drift["line_jitter_px"]),
                    rng=rng,
                )

        # Item 1: Poisson-dose noise
        if not for_autofocus and float(det.get("use_dose_model", 1.0)) >= 0.5:
            dwell_s = float(det["dwell_us"]) * 1e-6
            # electrons per pixel = current(A)/e * dwell ; current_pA in pA
            dose_e = (current_pA * 1e-12 / 1.602e-19) * dwell_s
            counts = apply_dose_noise(signal, dose_e,
                                      dqe=float(det["dqe"]),
                                      readout_e=float(det["readout_e"]),
                                      rng=rng)
            # Damage/contamination would be cancelled by naive normalization (a
            # uniform attenuation rescales away), so we re-apply the degradation
            # factor AFTER normalization: a degraded region/frame ends up genuinely
            # darker than a pristine one.
            # Convert dose counts back to a displayable image. IMPORTANT: use a
            # FIXED reference tied to the dose, not the per-frame max. Per-frame
            # max-normalization stretches a low-contrast (uniform-slab) region's
            # tiny shot noise across the full range, making a genuinely uniform
            # crystal look like pure noise. Normalizing by the expected full-signal
            # dose keeps a uniform bright region rendering as uniform bright gray,
            # while real contrast (edges, particles, fringes) still spans the range.
            ref = max(1e-6, dose_e * float(det["dqe"]))   # counts for signal==1.0
            out = np.clip(counts / ref, 0.0, 1.2) * 60000.0
            if getattr(self, "_degradation_factor", None) is not None:
                out = out * self._degradation_factor            # damage: darker
            if getattr(self, "_contam_brighten", None) is not None:
                out = out + self._contam_brighten                # contamination: brighter
            return np.clip(out, 0, 65535).astype(np.uint16)
        else:
            # legacy / autofocus path: scale signal, light gaussian noise
            current_scale = max(0.05, current_pA / 50.0)
            img_f = signal * 60000.0 * current_scale
            if not for_autofocus:
                noise_sigma = float(det.get("noise_sigma", 12.0))
                img_f = img_f + rng.normal(0.0, noise_sigma, img_f.shape).astype(np.float32)
            return np.clip(img_f, 0, 65535).astype(np.uint16)

    # ---- diffraction (item 5) ----
    def _normalize_to_u16(self, img_f):
        x = img_f.astype(np.float32); x -= x.min()
        mx = float(x.max())
        if mx > 1e-6: x = x / mx
        return np.clip(x * 65535.0, 0, 65535).astype(np.uint16)

    def _render_diffraction_fft_proxy(self, img_u16, beamstop_radius_px=0):
        x = img_u16.astype(np.float32); x = x - float(x.mean())
        F = np.fft.fftshift(np.fft.fft2(x))
        P = np.log1p(np.abs(F)).astype(np.float32)
        if beamstop_radius_px and beamstop_radius_px > 0:
            H, W = P.shape
            yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
            cy, cx = (H - 1) * 0.5, (W - 1) * 0.5
            r = np.sqrt((yy - cy)**2 + (xx - cx)**2)
            P[r <= float(beamstop_radius_px)] = 0.0
        return self._normalize_to_u16(P)

    def acquire_image(self, device, **args):
        self._require_ready()
        if device not in self.detectors:
            return None
        det = self.detectors[device]
        out_size = int(det["size"])

        if str(self.sim.mode).upper() == "DIFF":
            beamstop = float(self.sim.diff.get("beamstop_radius_px", 6.0))
            rng = np.random.default_rng(int(time.time()*1e6) % (2**32))
            method = None
            img_f = None

            # Try the local-region atom path first (item 6: stage-aware diffraction).
            # Falls back automatically if the sample doesn't expose atoms.
            use_local = float(self.sim.diff.get("use_local_atoms", 1.0)) >= 0.5
            if use_local and self.current_sample is not None:
                # Determine diffracting region:
                #   aperture_um: 0 (auto) -> current detector FOV
                #   depth_nm:    0 (auto) -> full sample depth
                ap_um = float(self.sim.diff.get("aperture_um", 0.0))
                if ap_um <= 0:
                    ap_um = float(det.get("field_of_view_um", 20.0))
                # The illuminated region cannot exceed the generated specimen.
                # Without this clamp, a wide detector FOV on a small-extent
                # sample makes the atom tiling grid explode to tens of GB
                # before the 100k cap runs. Anchor to the sample's generation
                # range (sample_fov_um is its legacy alias).
                gen_um = float(getattr(self.current_sample, "generation_range_um",
                                       self.sample_fov_um))
                ap_um = min(ap_um, gen_um)
                depth_nm = float(self.sim.diff.get("depth_nm", 0.0))
                if depth_nm <= 0:
                    # full sample depth = D voxels * (sample_fov_um / W voxels) approximated
                    # Use volume depth in microns -> nm
                    depth_um = self.vol_D * (self.sample_fov_um / max(1, self.vol.shape[2]))
                    depth_nm = max(1.0, depth_um * 1000.0)
                # Stage position in microns (for locality on non-uniform samples)
                cx_um = float(self.sim.stage.get("x", 0.0)) * 1e6
                cy_um = float(self.sim.stage.get("y", 0.0)) * 1e6
                try:
                    atoms_pos, atoms_Z = self.current_sample.get_atoms_in_region(
                        cx_um, cy_um, ap_um / 2.0, depth_nm)
                except Exception:
                    atoms_pos, atoms_Z = None, None
                if atoms_pos is not None and len(atoms_pos) > 0:
                    img_f = diffraction_from_atoms(
                        atoms_pos, atoms_Z, out_size,
                        tilt_a_deg=float(self.sim.stage.get("a", 0.0)),
                        tilt_b_deg=float(self.sim.stage.get("b", 0.0)),
                        kv=float(self.sim.beam.get("voltage_kV", 200.0)),
                        camera_length_mm=float(self.sim.diff["camera_length_mm"]),
                        beamstop_radius_px=beamstop,
                        thickness_nm=float(self.sim.diff.get("thickness_nm", 20.0)),
                        rng=rng)
                    method = f"from_atoms (N={len(atoms_pos)})"

            # Fallback: analytical kinematical from a declared lattice. This is
            # only reached if a sample exposes a lattice but no atoms -- with the
            # unified atom path, all crystalline/particle samples expose atoms, so
            # this is a rarely-used compatibility branch.
            if img_f is None:
                lat = self.current_sample.get_lattice() if self.current_sample else None
                if lat is not None:
                    img_f = kinematical_diffraction(
                        lat, out_size,
                        tilt_a_deg=float(self.sim.stage.get("a", 0.0)),
                        tilt_b_deg=float(self.sim.stage.get("b", 0.0)),
                        kv=float(self.sim.beam.get("voltage_kV", 200.0)),
                        camera_length_mm=float(self.sim.diff["camera_length_mm"]),
                        beamstop_radius_px=beamstop,
                        thickness_nm=float(self.sim.diff.get("thickness_nm", 20.0)),
                        rng=rng)
                    method = "kinematical_lattice"

            # Single diffraction channel: no FFT proxy. If a sample exposes
            # neither atoms nor a lattice, return an empty detector (just the
            # central beam + noise) rather than a physically meaningless FFT.
            if img_f is None:
                img_f = np.zeros((out_size, out_size), dtype=np.float32)
                cyx = out_size / 2.0
                yy, xx = np.mgrid[0:out_size, 0:out_size].astype(np.float32)
                d2c = (xx - cyx)**2 + (yy - cyx)**2
                img_f += 65535.0 * 1.0 * np.exp(-d2c / (2 * (3.0)**2))
                if beamstop and beamstop > 0:
                    img_f[np.sqrt(d2c) <= beamstop] = 0.0
                method = "empty (no atomic structure)"
            noise = rng.normal(0.0, 250.0, img_f.shape).astype(np.float32)
            img = np.clip(img_f + noise, 0, 65535).astype(np.uint16)

            r = serialize_ndarray_b64(img)
            self._log("acquire_image", {"device": device, "mode": "DIFF", "diff_method": method},
                      f"image {img.shape}")
            return r
        else:
            img = self._render_camera_image_u16(device)
            r = serialize_ndarray_b64(img)
            self._log("acquire_image", {"device": device, "mode": "IMG"}, f"image {img.shape}")
            return r

    def autofocus(self, device="haadf", z_range_um=2.0, z_steps=9):
        self._require_ready()
        if device not in self.detectors:
            raise ValueError(f"Unknown device {device}")
        z0 = self.sim.stage["z"]
        zs_um = np.linspace(-z_range_um, z_range_um, int(z_steps))
        zs_m = z0 + (zs_um * 1e-6)
        scores = []
        best_score = -1e18; best_z = z0
        for z_m, z_um in zip(zs_m, zs_um):
            self.sim.stage["z"] = float(z_m)
            # On beam-sensitive specimens, let damage accumulate DURING the sweep
            # so later Z-steps see a degraded specimen -> the sharpness curve is
            # corrupted and AF can legitimately diverge (review 3). On robust
            # specimens (damage disabled) the sweep is non-destructive.
            damaging = float(self.sim.specimen.get("beam_damage_enabled", 0.0)) >= 0.5
            img = self._render_camera_image_u16(device, for_autofocus=not damaging)
            sc = sharpness_metric(img)
            scores.append((float(z_um), float(sc)))
            if sc > best_score:
                best_score = sc; best_z = float(z_m)

        # --- Convergence assessment (review 3) ---
        # Autofocus should NOT always succeed. Judge the sharpness curve:
        #  - weak peak prominence above the baseline -> low-contrast/flat, AF unreliable
        #  - multiple comparable maxima              -> multimodal, ambiguous
        sc_arr = np.array([s for _, s in scores], dtype=np.float64)
        floor = float(sc_arr.min())
        peak = float(sc_arr.max())
        # prominence: how far the peak rises above the baseline, relative to baseline
        contrast = (peak - floor) / (abs(floor) + 1e-9)
        # count local maxima within 90% of the (prominence-scaled) peak
        thresh_level = floor + 0.9 * (peak - floor)
        near_peak = 0
        for i in range(1, len(sc_arr)-1):
            if sc_arr[i] >= sc_arr[i-1] and sc_arr[i] >= sc_arr[i+1] and sc_arr[i] >= thresh_level:
                near_peak += 1
        if len(sc_arr) >= 2 and sc_arr[0] >= thresh_level and sc_arr[0] > sc_arr[1]: near_peak += 1
        if len(sc_arr) >= 2 and sc_arr[-1] >= thresh_level and sc_arr[-1] > sc_arr[-2]: near_peak += 1

        converged = True
        reason = "ok"
        # thresholds (could be environment-tuned)
        min_contrast = float(self.sim.specimen.get("af_min_contrast", 0.08))
        if contrast < min_contrast:
            converged = False
            reason = f"low contrast (peak/floor ratio {contrast:.3f} < {min_contrast:.3f}); specimen may be low-contrast or beam-damaged"
        elif near_peak >= 3:
            converged = False
            reason = f"multimodal sharpness curve ({near_peak} comparable maxima); focus ambiguous"

        # If not converged, do NOT commit to best_z (leave stage where it was) to
        # mimic a real AF routine refusing/failing rather than guessing.
        if converged:
            self.sim.stage["z"] = best_z
        else:
            self.sim.stage["z"] = z0

        result = {"converged": bool(converged),
                  "reason": reason,
                  "best_z_m": float(best_z),
                  "best_z_um_relative": float((best_z - z0) * 1e6),
                  "curve_contrast": float(contrast),
                  "n_candidate_peaks": int(near_peak),
                  "scores": scores}
        self._log("autofocus", {"device": device, "z_range_um": z_range_um,
                                "z_steps": z_steps, "converged": converged}, result)
        return result

    # ---- simulation environment (review 3): named realism scenarios ----
    def set_environment(self, name="pristine"):
        """Configure a bundle of realism settings for a named test scenario.
        This is the 'simulation environment' a user selects to stress-test their
        code under specific conditions without changing the specimen itself."""
        name = str(name).lower().strip()
        # Drift is specified through the PHYSICAL nm/s interface so presets stay
        # correct for any sample's volume scale (the notebook hard-coded px/s
        # values pre-computed for the default scale; nm/s is the same intent,
        # scale-independent). Realistic anchors: excellent <0.2 · good ~0.5 ·
        # moderate ~2 · poor ~5 nm/s.
        presets = {
            "pristine": {  # ideal conditions: no drift, no damage, high dose
                "drift": dict(vx_nm_per_s=0.0, vy_nm_per_s=0.0, line_jitter_nm=0.0,
                              enabled=False),  # ~0 nm/s (excellent)
                "specimen": dict(beam_damage_enabled=False, contamination_enabled=False),
                "detector": dict(dwell_us=20.0, dqe=0.9, readout_e=1.0),
                "af_min_contrast": 0.05,
            },
            "beam_sensitive": {  # damage accumulates quickly; AF can diverge
                "drift": dict(vx_nm_per_s=0.4, vy_nm_per_s=0.25, line_jitter_nm=0.05,
                              enabled=True),  # ~0.5 nm/s (good)
                "specimen": dict(beam_damage_enabled=True, contamination_enabled=False,
                                 damage_dose_threshold=1.0e4, damage_rate=0.8),
                "detector": dict(dwell_us=10.0, dqe=0.8, readout_e=1.5),
                "af_min_contrast": 0.12,
            },
            "contaminating": {  # carbon builds up where the beam dwells
                "drift": dict(vx_nm_per_s=1.0, vy_nm_per_s=0.6, line_jitter_nm=0.1,
                              enabled=True),  # ~1.2 nm/s (moderate)
                "specimen": dict(beam_damage_enabled=False, contamination_enabled=True,
                                 contamination_rate=3.0),
                "detector": dict(dwell_us=15.0, dqe=0.8, readout_e=1.5),
                "af_min_contrast": 0.10,
            },
            "thick_drifting": {  # thick noisy sample with strong drift
                "drift": dict(vx_nm_per_s=5.0, vy_nm_per_s=3.0, line_jitter_nm=0.3,
                              enabled=True),  # ~5.8 nm/s (poor/fresh insert)
                "specimen": dict(beam_damage_enabled=False, contamination_enabled=False),
                "detector": dict(dwell_us=6.0, dqe=0.7, readout_e=2.5),
                "af_min_contrast": 0.10,
            },
            "low_dose": {  # dose-limited: very noisy, AF struggles
                "drift": dict(vx_nm_per_s=1.5, vy_nm_per_s=0.9, line_jitter_nm=0.15,
                              enabled=True),  # ~1.7 nm/s (moderate, dose-limited)
                "specimen": dict(beam_damage_enabled=True, contamination_enabled=False,
                                 damage_dose_threshold=5.0e3, damage_rate=1.0),
                "detector": dict(dwell_us=2.0, dqe=0.75, readout_e=2.0),
                "af_min_contrast": 0.15,
            },
        }
        if name not in presets:
            raise ValueError(f"Unknown environment '{name}'. Options: {list(presets.keys())}")
        cfg = presets[name]
        self.set_drift(**cfg["drift"], reset_accum=True)
        self.set_specimen(**cfg["specimen"])
        for k, v in cfg["detector"].items():
            self.detectors["haadf"][k] = v
        self.sim.specimen["af_min_contrast"] = cfg["af_min_contrast"]
        # Thickness is part of the environment too: some scenarios put you on a
        # thick region, some on a thin one. Only applied if a sample is loaded.
        env_thickness = {
            "thick_drifting": dict(thickness_nm=90.0, thickness_seed=3),
            "low_dose":       dict(thickness_nm=25.0, thickness_seed=5),
        }
        if name in env_thickness and getattr(self, "current_sample", None) is not None:
            try:
                self.set_thickness(**env_thickness[name])
            except Exception:
                pass
        self.reset_specimen()
        self._current_environment = name
        r = {"environment": name, "config": cfg}
        self._log("set_environment", {"name": name}, r)
        return r

    def get_environment(self):
        return {"environment": getattr(self, "_current_environment", "pristine"),
                "available": ["pristine","beam_sensitive","contaminating","thick_drifting","low_dose"]}

    def get_microscope_state(self):
        """Composite snapshot used by the HTTP session endpoint (one RPC)."""
        st = self.sim.stage
        r = {
            "stage": {k: float(st[k]) for k in ["x", "y", "z", "a", "b"]},
            "beam": {k: float(self.sim.beam.get(k, 0.0))
                     for k in ["x", "y", "current_pA", "voltage_kV"]},
            "vacuum": float(self.sim.vacuum),
            "status": str(self.sim.status),
            "holder_type": str(self.sim.holder_type),
            "mode": str(self.sim.mode),
            "detectors": {k: dict(v) for k, v in self.detectors.items()},
            # inline (not via get_diffraction_settings) so 2 s polling does not
            # flood the command log
            "diffraction": {k: float(v) for k, v in self.sim.diff.items()},
            "environment": getattr(self, "_current_environment", "pristine"),
            "sample": {
                "name": self.current_sample_name,
                "registered": self.vol is not None,
            },
            "stage_limits": {k: float(v) for k, v in self.STAGE_LIMITS.items()},
            # inline (not via get_thickness/get_resolution) for the same
            # command-log reason as diffraction above
            "thickness": dict(self.sim.thickness),
            "resolution": {
                "resolution_px": int(self.detectors["haadf"]["size"]),
                "allowed": list(self.ALLOWED_RESOLUTIONS),
            },
            # drift with physical nm/s echo + dose meter fields, so the 2 s poll
            # carries everything the GUI displays without extra RPC loops
            "drift": self._drift_state_with_nm(),
            "specimen": {
                "beam_damage_enabled": float(self.sim.specimen.get("beam_damage_enabled", 0.0)),
                "contamination_enabled": float(self.sim.specimen.get("contamination_enabled", 0.0)),
                "damage_dose_threshold": float(self.sim.specimen.get("damage_dose_threshold", 3e4)),
                "max_accumulated_dose": (float(self._dose_map.max())
                                         if self._dose_map is not None else 0.0),
                "max_contamination": (float(self._contam_map.max())
                                      if self._contam_map is not None else 0.0),
            },
        }
        return r

    def _drift_state_with_nm(self):
        d = {k: float(v) for k, v in self.sim.drift.items()}
        px_per_nm = float(getattr(self, "sample_px_per_um", 38.4)) / 1000.0
        nm_per_px = (1.0 / px_per_nm) if px_per_nm > 0 else 26.04
        d["vx_nm_per_s"] = d["vx_px_per_s"] * nm_per_px
        d["vy_nm_per_s"] = d["vy_px_per_s"] * nm_per_px
        return d

    def close(self):
        self._log("close", {}, 1)
        return 1


# ============================================================================
# Netstring JSON-RPC protocol
# ============================================================================
class NetstringJSONProtocol(protocol.Protocol):
    def __init__(self, server_instance):
        self.buffer = b""
        self.server_instance = server_instance

    def dataReceived(self, data):
        self.buffer += data
        while True:
            colon = self.buffer.find(b":")
            if colon < 0: return
            length_str = self.buffer[:colon]
            if not length_str: return
            try:
                length = int(length_str)
            except ValueError:
                comma = self.buffer.find(b",")
                self.buffer = self.buffer[comma+1:] if comma >= 0 else b""
                continue
            if len(self.buffer) < colon + 1 + length + 1: return
            payload = self.buffer[colon+1:colon+1+length]
            trailing = self.buffer[colon+1+length:colon+1+length+1]
            if trailing != b",":
                comma = self.buffer.find(b",")
                self.buffer = self.buffer[comma+1:] if comma >= 0 else b""
                continue
            self.buffer = self.buffer[colon+1+length+1:]
            self._handle_payload(payload)

    def _handle_payload(self, payload_bytes):
        try:
            request = json.loads(payload_bytes.decode("utf-8"))
            method = request.get("method"); params = request.get("params", {})
            req_id = request.get("id", None)
            d = threads.deferToThread(self._dispatch_method, method, params)
            d.addCallback(lambda result: self._send_success(req_id, result))
            d.addErrback(lambda f: self._send_error(req_id, str(f)))
        except Exception as e:
            self._send_error(None, f"Invalid JSON payload: {e}")

    def _dispatch_method(self, method, params):
        if not hasattr(self.server_instance, method):
            raise AttributeError(f"Method {method} not implemented.")
        func = getattr(self.server_instance, method)
        return func(**params) if isinstance(params, dict) else func(params)

    def _send_success(self, req_id, result):
        self._write_netstring({"jsonrpc": "2.0", "id": req_id, "result": result})

    def _send_error(self, req_id, message):
        self._write_netstring({"jsonrpc": "2.0", "id": req_id, "error": str(message)})

    def _write_netstring(self, obj):
        payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        self.transport.write(f"{len(payload)}:".encode("ascii") + payload + b",")


class NetstringFactory(Factory):
    def __init__(self, server_instance):
        self.server_instance = server_instance
    def buildProtocol(self, addr):
        return NetstringJSONProtocol(self.server_instance)


_SERVER_INSTANCE = None


def main(host="127.0.0.1", port=9094):
    global _SERVER_INSTANCE
    if _SERVER_INSTANCE is not None:
        print("Server already initialized. Restart runtime for a fresh server.")
        return _SERVER_INSTANCE
    server_inst = STEMServer()
    _SERVER_INSTANCE = server_inst
    factory = NetstringFactory(server_inst)
    reactor.listenTCP(port, factory, interface=host)
    print(f"STEM Twisted DT server listening on {host}:{port} (initializing sample...)")
    reactor.callWhenRunning(lambda: threads.deferToThread(server_inst.finish_init))
    if reactor.running:
        print("Reactor already running; listener installed.")
        return server_inst
    reactor.run(installSignalHandlers=False)
    return server_inst


if __name__ == "__main__":
    main()
