"""
samples/base.py

Sample base class. Now carries an OPTIONAL crystallographic `lattice`
descriptor so the server can compute real kinematical diffraction for
crystalline samples. Non-crystalline samples leave `lattice=None` and the
server falls back to an FFT-based diffraction proxy.
"""
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class SampleMetadata:
    name: str
    display_name: str
    description: str
    default_params: Dict[str, Any] = field(default_factory=dict)
    param_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CrystalLattice:
    """
    Minimal crystallographic description sufficient for kinematical
    diffraction-spot generation.

    - real_vectors: 3x3 array, rows are the real-space lattice vectors a1,a2,a3
      in Angstroms. The crystal is assumed aligned so a3 is roughly along the
      beam (z) at zero tilt.
    - basis: list of (fractional_xyz, atomic_number) for atoms in the unit cell.
    - name: label for display.
    """
    real_vectors: np.ndarray
    basis: List[Any]
    name: str = "crystal"

    def reciprocal_vectors(self) -> np.ndarray:
        """Return 3x3 reciprocal lattice vectors (rows b1,b2,b3), 2*pi convention."""
        a1, a2, a3 = self.real_vectors[0], self.real_vectors[1], self.real_vectors[2]
        vol = np.dot(a1, np.cross(a2, a3))
        b1 = 2 * np.pi * np.cross(a2, a3) / vol
        b2 = 2 * np.pi * np.cross(a3, a1) / vol
        b3 = 2 * np.pi * np.cross(a1, a2) / vol
        return np.array([b1, b2, b3], dtype=np.float64)

    def structure_factor(self, h, k, l) -> complex:
        """Kinematical structure factor F_hkl = sum_j Z_j exp(2pi i (h x + k y + l z))."""
        F = 0.0 + 0.0j
        for frac, Z in self.basis:
            fx, fy, fz = frac
            phase = 2 * np.pi * (h * fx + k * fy + l * fz)
            F += Z * np.exp(1j * phase)
        return F


class Sample:
    meta: SampleMetadata = None
    sample_fov_um: float = 200.0
    # Inherent length scale of the sample's finest meaningful detail, in
    # nanometres. Used by the server as a resolution limit: when the current
    # pixel size (FOV / magnification) is coarser than this, the fine detail is
    # blurred out, so the user must raise magnification to resolve it (and then
    # drift / dose become the limiting factors, as on a real instrument).
    # 0 = no inherent scale (feature always resolvable). Subclasses override.
    feature_scale_nm: float = 0.0
    tilt_strength_px_per_slice: float = 0.35
    # Optional crystallographic descriptor. If set (a CrystalLattice), the
    # server will generate real kinematical diffraction spots. If None, the
    # server uses the FFT proxy.
    lattice: Optional[CrystalLattice] = None

    def __init__(self, **params):
        defaults = self.meta.default_params if self.meta else {}
        self.params = {**defaults, **params}

    def generate_volume(self, D, H, W):
        raise NotImplementedError

    def get_lattice(self):
        """Return the crystal lattice for diffraction, or None if amorphous."""
        return self.lattice

    def get_atoms_in_region(self, cx_um, cy_um, half_width_um, depth_nm):
        """
        Default implementation for particle-based samples. If the sample has
        recorded `self._particles` (list of {'center_vox','radii_vox'}) and
        `self._vol_shape` during generate_volume, fill the in-region particles
        with atoms. Crystalline particles -> spots/rings; amorphous -> halos.
        Samples with their own lattice tiling override this.

        Returns (None, None) if the sample has no atomic structure.
        """
        if not hasattr(self, "_particles") or not hasattr(self, "_vol_shape"):
            return None, None
        D, H, W = self._vol_shape
        px_per_um = W / self.sample_fov_um
        shifted = []
        for part in self._particles:
            pz, py, px = part["center_vox"]
            shifted.append({"center_vox": (pz, py - H/2.0, px - W/2.0),
                            "radii_vox": part["radii_vox"]})
        amorphous = not getattr(self, "crystalline_particles", True)
        return atoms_in_particles(
            shifted, cx_um, cy_um, half_width_um, depth_nm, px_per_um,
            amorphous=amorphous,
            random_orientation=getattr(self, "particles_random_orientation", True))


def tile_lattice_in_region(lattice, half_width_A, depth_A):
    """
    Generate atom positions for a lattice tiled into a box centered at the
    origin of extent [-half_width_A, +half_width_A] in x,y and [-depth_A/2,
    +depth_A/2] in z. Returns (positions, atomic_numbers) where positions are
    in Angstroms relative to the box center.

    Vectorized: builds the integer cell index grid in numpy and filters in one
    shot rather than looping in Python.
    """
    a1, a2, a3 = lattice.real_vectors
    # Cell-index bracket that conservatively covers the box
    max_cell_xy = int(np.ceil(2.0 * half_width_A / min(np.linalg.norm(a1[:2]),
                                                       np.linalg.norm(a2[:2]),
                                                       1.0))) + 2
    max_cell_z = int(np.ceil(depth_A / max(1e-6, abs(a3[2])))) + 2

    # Build cell-index grid
    ii = np.arange(-max_cell_xy, max_cell_xy + 1)
    jj = np.arange(-max_cell_xy, max_cell_xy + 1)
    kk = np.arange(-max_cell_z, max_cell_z + 1)
    I, J, K = np.meshgrid(ii, jj, kk, indexing='ij')
    # Cell origins (N, 3)
    cell_origins = (I[..., None] * a1 + J[..., None] * a2 + K[..., None] * a3).reshape(-1, 3)

    all_pos = []; all_Z = []
    for frac, Z in lattice.basis:
        fx, fy, fz = frac
        offset = fx * a1 + fy * a2 + fz * a3
        positions = cell_origins + offset
        mask = ((np.abs(positions[:, 0]) <= half_width_A) &
                (np.abs(positions[:, 1]) <= half_width_A) &
                (np.abs(positions[:, 2]) <= depth_A / 2))
        kept = positions[mask]
        all_pos.append(kept)
        all_Z.append(np.full(len(kept), Z, dtype=np.int32))

    if not all_pos or sum(len(p) for p in all_pos) == 0:
        return np.zeros((0, 3), dtype=np.float64), np.zeros(0, dtype=np.int32)
    return np.concatenate(all_pos).astype(np.float64), np.concatenate(all_Z)


# ============================================================================
# Particle-based sample support (unified diffraction)
# ============================================================================
# Default Au FCC lattice for filling crystalline nanoparticles with atoms.
_AU_FCC = None

def _get_au_fcc():
    global _AU_FCC
    if _AU_FCC is None:
        a = 4.05
        _AU_FCC = CrystalLattice(
            real_vectors=np.array([[a,0,0],[0,a,0],[0,0,a]], dtype=np.float64),
            basis=[((0,0,0),79),((0,0.5,0.5),79),((0.5,0,0.5),79),((0.5,0.5,0),79)],
            name="Au-FCC")
    return _AU_FCC


def atoms_in_particles(particles, cx_um, cy_um, half_width_um, depth_nm,
                       px_per_um, atom_cap=100000, lattice=None,
                       amorphous=False, amorphous_number_density=0.06,
                       particle_nm_per_vox=0.5, random_orientation=True,
                       orientation_seed=12345, rng=None):
    """
    Fill the particles that fall within the requested region with atoms.

    In-plane PLACEMENT of particles uses the display voxel scale (so particles
    sit where they appear in the image). Each particle's atomic FILLING uses a
    physical scale (particle_nm_per_vox) decoupled from the often-coarse display
    scale, so particle sizes and interatomic spacings come out realistic.

    random_orientation: if True, each crystalline particle is given a random,
        but deterministic (seeded by particle index), 3D orientation. An
        ensemble of many randomly-oriented small crystallites produces
        powder-ring-like diffraction -- the physically correct result for
        dispersed nanoparticles -- rather than a single-crystal spot pattern.

    particles: list of {'center_vox': (z,y,x), 'radii_vox': (rz,ry,rx)} with the
               volume CENTER as origin (in display voxels).
    Returns (positions_A, atomic_numbers) in Angstroms relative to region center.
    """
    if rng is None:
        rng = np.random.default_rng(0)
    if lattice is None:
        lattice = _get_au_fcc()

    half_vox = half_width_um * px_per_um
    cx_vox_off = cx_um * px_per_um
    cy_vox_off = cy_um * px_per_um
    disp_A_per_vox = (1.0 / px_per_um) * 1e4
    fill_A_per_vox = particle_nm_per_vox * 10.0

    def _random_rot(seed):
        r = np.random.default_rng(seed)
        ax = r.normal(size=3); ax /= (np.linalg.norm(ax) + 1e-12)
        ang = r.uniform(0, 2*np.pi)
        K = np.array([[0,-ax[2],ax[1]],[ax[2],0,-ax[0]],[-ax[1],ax[0],0]])
        return np.eye(3) + np.sin(ang)*K + (1-np.cos(ang))*(K@K)

    all_pos = []
    all_Z = []
    total = 0
    for p_idx, part in enumerate(particles):
        cz, cy, cx = part['center_vox']
        rz, ry, rx = part['radii_vox']
        rel_x = cx - cx_vox_off
        rel_y = cy - cy_vox_off
        if (abs(rel_x) - rx > half_vox) or (abs(rel_y) - ry > half_vox):
            continue

        Rx_A = rx * fill_A_per_vox
        Ry_A = ry * fill_A_per_vox
        Rz_A = rz * fill_A_per_vox
        ox_A = rel_x * disp_A_per_vox
        oy_A = rel_y * disp_A_per_vox

        if amorphous:
            vol_A3 = (4.0/3.0) * np.pi * Rx_A * Ry_A * Rz_A
            n_at = int(min(20000, max(8, vol_A3 * amorphous_number_density)))
            u = rng.normal(size=(n_at*2, 3))
            u /= (np.linalg.norm(u, axis=1, keepdims=True) + 1e-9)
            radii_frac = rng.uniform(0, 1, size=(n_at*2,)) ** (1.0/3.0)
            pts = (u * radii_frac[:, None])[:n_at]
            pts_A = pts * np.array([Rx_A, Ry_A, Rz_A])
            pos = np.stack([pts_A[:,0] + ox_A, pts_A[:,1] + oy_A, pts_A[:,2]], axis=1)
            Z = np.full(len(pos), 79, dtype=np.int32)
        else:
            bp, bZ = tile_lattice_in_region(lattice,
                                            half_width_A=max(Rx_A, Ry_A),
                                            depth_A=2*max(Rx_A, Ry_A, Rz_A))
            if len(bp) == 0:
                continue
            # rotate the crystal lattice for this particle (random but deterministic)
            if random_orientation:
                R = _random_rot(orientation_seed + p_idx)
                bp = bp @ R.T
            ex = bp[:,0] / (Rx_A + 1e-6)
            ey = bp[:,1] / (Ry_A + 1e-6)
            ez = bp[:,2] / (Rz_A + 1e-6)
            inside = (ex*ex + ey*ey + ez*ez) <= 1.0
            bp = bp[inside]; bZ = bZ[inside]
            bp = bp + np.array([ox_A, oy_A, 0.0])
            pos = bp; Z = bZ

        all_pos.append(pos)
        all_Z.append(Z)
        total += len(pos)
        if total > atom_cap:
            break

    if not all_pos or total == 0:
        return np.zeros((0,3), dtype=np.float64), np.zeros(0, dtype=np.int32)
    pos = np.concatenate(all_pos)
    Z = np.concatenate(all_Z)
    if len(pos) > atom_cap:
        idx = rng.choice(len(pos), atom_cap, replace=False)
        pos = pos[idx]; Z = Z[idx]
    return pos.astype(np.float64), Z.astype(np.int32)
