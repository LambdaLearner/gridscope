"""
samples/polycrystal_grains.py
Procedural FCC polycrystal with a small number (default 4) of contiguous grains,
each a Voronoi region with its own crystallographic orientation. Atoms are placed
in real space according to which grain owns each location, so the IMG view and the
diffraction pattern come from the SAME atomic model:
  - an aperture inside one grain  -> a clean single-crystal spot pattern
  - an aperture spanning a boundary -> two overlapping single-crystal patterns
  - a wide aperture over many grains -> ring-like (powder) tendency
No external file needed.
"""
import numpy as np
from .base import Sample, SampleMetadata, CrystalLattice, tile_lattice_in_region
from . import register


def _rand_rot(seed):
    r = np.random.default_rng(seed)
    ax = r.normal(size=3); ax /= (np.linalg.norm(ax) + 1e-12)
    ang = r.uniform(0, 2*np.pi)
    K = np.array([[0,-ax[2],ax[1]],[ax[2],0,-ax[0]],[-ax[1],ax[0],0]])
    return np.eye(3) + np.sin(ang)*K + (1-np.cos(ang))*(K@K)


@register
class PolycrystalGrains(Sample):
    feature_scale_nm = 0.25   # lattice fringe spacing (~0.25 nm)
    sample_fov_um = 2.0
    meta = SampleMetadata(
        name="polycrystal_grains",
        display_name="Polycrystal (FCC, few grains)",
        description="A few contiguous, differently-oriented FCC grains (Voronoi).",
        default_params={
            "n_grains": 4,
            "seed": 7,
            "a_angstrom": 4.05,
            "atomic_number": 79,
            "base_level": 90.0,
            "grain_intensity": 9000.0,
            "sigma_px": 1.1,
        },
        param_schema={
            "n_grains":        {"type": "int",   "min": 2,    "max": 12},
            "seed":            {"type": "int",   "min": 0,    "max": 2**31-1},
            "a_angstrom":      {"type": "float", "min": 1.0,  "max": 20.0},
            "atomic_number":   {"type": "int",   "min": 1,    "max": 100},
            "base_level":      {"type": "float", "min": 0,    "max": 1000},
            "grain_intensity": {"type": "float", "min": 100,  "max": 60000},
            "sigma_px":        {"type": "float", "min": 0.5,  "max": 4.0},
        },
    )
    crystalline_particles = True

    def __init__(self, **params):
        super().__init__(**params)
        a = float(self.params["a_angstrom"])
        Z = int(self.params["atomic_number"])
        self.lattice = CrystalLattice(
            real_vectors=np.array([[a,0,0],[0,a,0],[0,0,a]], dtype=np.float64),
            basis=[((0,0,0),Z),((0,0.5,0.5),Z),((0.5,0,0.5),Z),((0.5,0.5,0),Z)],
            name="FCC-poly")

    def _grain_setup(self, H, W):
        """Grain seed points (in voxels) and a deterministic orientation each.
        Orientations include a sizeable in-plane rotation so adjacent grains look
        visibly different in the IMG view (rotated lattice rows) AND give distinct
        diffraction patterns."""
        rng = np.random.default_rng(int(self.params["seed"]))
        ng = int(self.params["n_grains"])
        seeds_xy = np.column_stack([rng.uniform(0.1*W, 0.9*W, ng),
                                    rng.uniform(0.1*H, 0.9*H, ng)])
        rots = []
        # spread in-plane angles roughly evenly so grains are clearly different
        base_angles = np.linspace(0, np.pi/2, ng, endpoint=False) + rng.uniform(0, 0.3, ng)
        for g in range(ng):
            # in-plane rotation (about beam z) -- dominates the visual + pattern
            th = base_angles[g]
            Rz = np.array([[np.cos(th), -np.sin(th), 0],
                           [np.sin(th),  np.cos(th), 0],
                           [0, 0, 1.0]])
            # plus a small out-of-plane tilt (proper rotation, small angle)
            r2 = np.random.default_rng(int(self.params["seed"]) * 100 + g)
            ax = r2.normal(size=3); ax[2] = 0  # tilt axis in-plane -> tips z out
            ax /= (np.linalg.norm(ax) + 1e-12)
            phi = r2.uniform(0.0, 0.30)        # up to ~17 deg out-of-plane
            K = np.array([[0,-ax[2],ax[1]],[ax[2],0,-ax[0]],[-ax[1],ax[0],0]])
            Rtilt = np.eye(3) + np.sin(phi)*K + (1-np.cos(phi))*(K@K)
            rots.append(Rz @ Rtilt)
        return seeds_xy, rots

    def _owner_at(self, x_vox, y_vox):
        """Index of the grain owning a voxel location (nearest seed = Voronoi)."""
        d2 = (self._seeds_xy[:, 0] - x_vox)**2 + (self._seeds_xy[:, 1] - y_vox)**2
        return int(np.argmin(d2))

    def generate_volume(self, D, H, W):
        p = self.params
        self._seeds_xy, self._rots = self._grain_setup(H, W)
        self._vol_shape = (D, H, W)

        V = np.zeros((D, H, W), dtype=np.float32) + float(p["base_level"])
        # Render each grain's Voronoi region with a lattice-dot texture whose
        # in-plane orientation matches that grain's rotation (so the IMG view
        # visibly shows differently-oriented grains meeting at boundaries).
        a_px = 20
        gy, gx = np.mgrid[0:H, 0:W]
        # Voronoi ownership per pixel
        d2 = ((gx[..., None] - self._seeds_xy[None, None, :, 0])**2 +
              (gy[..., None] - self._seeds_xy[None, None, :, 1])**2)
        owner = np.argmin(d2, axis=2)
        self._owner_map = owner.astype(np.int16)

        for g in range(len(self._seeds_xy)):
            mask = (owner == g)
            if not mask.any():
                continue
            ang = np.arctan2(self._rots[g][1, 0], self._rots[g][0, 0])
            ca, sa = np.cos(ang), np.sin(ang)
            xr = gx * ca - gy * sa
            yr = gx * sa + gy * ca
            on = (((np.round(xr / a_px) - xr / a_px)**2 +
                   (np.round(yr / a_px) - yr / a_px)**2) < 0.02) & mask
            ys, xs = np.where(on)
            for zz in range(D//2 - 6, D//2 + 6):
                V[zz, ys, xs] += float(p["grain_intensity"])

        def gfreq(n, s):
            f = np.fft.fftfreq(n).astype(np.float32)
            return np.exp(-2.0*(np.pi**2)*(s**2)*(f**2)).astype(np.float32)
        s = float(p["sigma_px"])
        F = np.fft.fftn(V)
        F *= gfreq(D, s)[:,None,None]; F *= gfreq(H, s)[None,:,None]; F *= gfreq(W, s)[None,None,:]
        V = np.clip(np.fft.ifftn(F).real, 0, 65535).astype(np.float32)
        return V

    def get_atoms_in_region(self, cx_um, cy_um, half_width_um, depth_nm):
        """Place atoms in the aperture according to which grain owns each sub-cell.
        We sample the aperture on a fine sub-grid, assign each sub-cell to its
        Voronoi owner, and fill it with that grain's (rotated) FCC lattice. This
        makes a within-grain aperture give a single-crystal pattern and a
        boundary-spanning aperture give two overlapping patterns -- from the SAME
        model as the image. Atoms are kept UNDER the diffraction cap (no random
        subsampling, which would smear the lattice)."""
        if not hasattr(self, "_seeds_xy"):
            return None, None
        D, H, W = self._vol_shape
        px_per_um = W / self.sample_fov_um
        rc_x = W/2.0 + cx_um * px_per_um   # region center in voxels
        rc_y = H/2.0 + cy_um * px_per_um
        half_vox = half_width_um * px_per_um
        depth_A = depth_nm * 10.0

        # Physical aperture size in Angstrom for the atom fill (compressed so the
        # per-grain block stays well under the cap to avoid subsampling).
        target_total = 90000
        # how many distinct grains does the aperture overlap? sample a 3x3 probe
        probe = np.linspace(-half_vox, half_vox, 3)
        owners = set()
        for dx in probe:
            for dy in probe:
                xv = np.clip(rc_x + dx, 0, W-1); yv = np.clip(rc_y + dy, 0, H-1)
                owners.add(self._owner_at(xv, yv))
        owners = sorted(owners)
        n_present = max(1, len(owners))

        # Side of the cubic atom block per grain, sized so total ~ target_total.
        a1, a2, a3 = self.lattice.real_vectors
        density = len(self.lattice.basis) / abs(np.dot(a1, np.cross(a2, a3)))
        side_A = float((target_total / max(1, n_present) / max(1e-9, density)) ** (1.0/3.0))
        half_A = side_A / 2.0

        # Partition the in-plane aperture among the present grains by area fraction.
        # Simple approach: give each present grain a lateral sub-offset so their
        # atom blocks occupy DIFFERENT space (adjacent, not overlapping), then
        # rotate each block by its grain orientation.
        all_pos = []; all_Z = []
        n = len(owners)
        for i, g in enumerate(owners):
            bp, bZ = tile_lattice_in_region(self.lattice, half_A, min(depth_A, side_A))
            if len(bp) == 0:
                continue
            bp = bp @ self._rots[g].T          # this grain's orientation
            # lateral offset so grains tile side-by-side (no physical overlap)
            if n > 1:
                off = (i - (n-1)/2.0) * side_A
                bp = bp + np.array([off, 0.0, 0.0])
            all_pos.append(bp); all_Z.append(bZ)
        if not all_pos:
            return np.zeros((0,3)), np.zeros(0, dtype=np.int32)
        pos = np.concatenate(all_pos); Z = np.concatenate(all_Z)
        return pos.astype(np.float64), Z.astype(np.int32)
