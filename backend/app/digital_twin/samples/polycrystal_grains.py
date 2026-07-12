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
    meta = SampleMetadata(
        name="polycrystal_grains",
        display_name="Polycrystal (Fe FCC, few grains)",
        description="A few contiguous, differently-oriented FCC grains (Voronoi).",
        default_params={
            "n_grains": 4,
            "seed": 7,
            "a_angstrom": 3.571,  # gamma-Fe (austenite)
            "atomic_number": 26,   # Fe
            "base_level": 90.0,
            "grain_intensity": 9000.0,
            "sigma_px": 1.1,
            "max_tilt_deg": 0.0,   # 0 = grains on-zone (clean symmetric nets);
                                   # >0 = realistic off-zone (sparse asymmetric)
        },
        param_schema={
            "n_grains":        {"type": "int",   "min": 2,    "max": 12},
            "seed":            {"type": "int",   "min": 0,    "max": 2**31-1},
            "a_angstrom":      {"type": "float", "min": 1.0,  "max": 20.0},
            "atomic_number":   {"type": "int",   "min": 1,    "max": 100},
            "base_level":      {"type": "float", "min": 0,    "max": 1000},
            "grain_intensity": {"type": "float", "min": 100,  "max": 60000},
            "sigma_px":        {"type": "float", "min": 0.5,  "max": 4.0},
            "max_tilt_deg":    {"type": "float", "min": 0.0,  "max": 30.0},
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
        Each grain gets a distinct in-plane rotation (about the beam) so adjacent
        grains look different in IMG and give distinct, cleanly-symmetric spot
        nets in DIFF. An optional out-of-plane tilt (param `max_tilt_deg`, default
        0) can be enabled for a more realistic, off-zone polycrystal."""
        rng = np.random.default_rng(int(self.params["seed"]))
        ng = int(self.params["n_grains"])
        seeds_xy = np.column_stack([rng.uniform(0.1*W, 0.9*W, ng),
                                    rng.uniform(0.1*H, 0.9*H, ng)])
        rots = []
        # spread in-plane angles roughly evenly so grains are clearly different
        base_angles = np.linspace(0, np.pi/2, ng, endpoint=False) + rng.uniform(0, 0.3, ng)
        max_tilt = np.deg2rad(float(self.params.get("max_tilt_deg", 0.0)))
        for g in range(ng):
            # In-plane rotation (about beam z). With max_tilt_deg == 0 this is the
            # ONLY rotation, so every grain stays near a zone axis and a within-
            # grain aperture gives a CLEAN, centrosymmetric single-crystal net --
            # Friedel pairs (+g / -g) both visible. That is what makes the grain
            # orientation legible in the DIFF view (Example 2, orientation mapping).
            th = base_angles[g]
            Rz = np.array([[np.cos(th), -np.sin(th), 0],
                           [np.sin(th),  np.cos(th), 0],
                           [0, 0, 1.0]])
            # Optional out-of-plane tilt for a MORE REALISTIC polycrystal. When
            # max_tilt_deg > 0, grains are thrown off-zone by up to that angle; the
            # curved Ewald sphere then intersects only a few narrow relrods, so most
            # grains show sparse, asymmetric patterns (often a single strong spot,
            # its Friedel partner heavily suppressed). Default 0 keeps nets clean.
            if max_tilt > 0.0:
                r2 = np.random.default_rng(int(self.params["seed"]) * 100 + g)
                ax = r2.normal(size=3); ax[2] = 0  # tilt axis in-plane -> tips z out
                ax /= (np.linalg.norm(ax) + 1e-12)
                phi = r2.uniform(0.0, max_tilt)
                K = np.array([[0,-ax[2],ax[1]],[ax[2],0,-ax[0]],[-ax[1],ax[0],0]])
                Rtilt = np.eye(3) + np.sin(phi)*K + (1-np.cos(phi))*(K@K)
                rots.append(Rz @ Rtilt)
            else:
                rots.append(Rz)
        return seeds_xy, rots

    def _owner_at(self, x_vox, y_vox):
        """Index of the grain owning a voxel location (nearest seed = Voronoi)."""
        d2 = (self._seeds_xy[:, 0] - x_vox)**2 + (self._seeds_xy[:, 1] - y_vox)**2
        return int(np.argmin(d2))

    def generate_volume(self, D, H, W):
        p = self.params
        self._seeds_xy, self._rots = self._grain_setup(H, W)
        self._vol_shape = (D, H, W)

        # Grains render as roughly UNIFORM Voronoi patches with a small per-grain
        # intensity offset (orientation/thickness contrast), NOT a visible atomic
        # lattice -- atomic columns are sub-nm and cannot be shown in a coarse
        # voxel volume. The crystallinity/orientation lives in the diffraction
        # (get_atoms_in_region). This gives realistic grain-contrast imaging and
        # per-grain diffraction, without an unphysical lattice visible at any FOV.
        gy, gx = np.mgrid[0:H, 0:W]
        d2 = ((gx[..., None] - self._seeds_xy[None, None, :, 0])**2 +
              (gy[..., None] - self._seeds_xy[None, None, :, 1])**2)
        owner = np.argmin(d2, axis=2)
        self._owner_map = owner.astype(np.int16)

        base = float(p["base_level"])
        slab = base + 40000.0            # bright specimen slab
        V2d = np.full((H, W), slab, dtype=np.float32)
        rng = np.random.default_rng(int(self.params["seed"]) + 99)
        for g in range(len(self._seeds_xy)):
            mask = (owner == g)
            if not mask.any():
                continue
            # small per-grain contrast (+/- ~8%) from orientation/thickness
            V2d[mask] = slab * (1.0 + 0.08 * rng.standard_normal())
        # thin dark grain-boundary lines for a realistic look
        from scipy.ndimage import sobel
        edges = np.hypot(sobel(owner.astype(float), 0), sobel(owner.astype(float), 1))
        V2d[edges > 0] *= 0.85

        V = np.tile(V2d[None, :, :], (D, 1, 1)).astype(np.float32)
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
        # lamella: x and y have different physical scales
        px_per_um_x = W / self.sample_length_um
        px_per_um_y = H / self.sample_width_um
        rc_x = W/2.0 + cx_um * px_per_um_x   # region center in voxels
        rc_y = H/2.0 + cy_um * px_per_um_y
        half_vox = half_width_um * px_per_um_x
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