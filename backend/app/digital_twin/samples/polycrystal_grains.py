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


# Low-index zone axes a grain can be put on (used by orientation_mode="random_zone_axes").
# Each gives a DIFFERENT, resolvable projected column pattern and spot net:
#   [001] square, [011] rectangular, [111] hexagonal, [112]/[013] lower symmetry.
GRAIN_ZONE_AXES = [(0, 0, 1), (0, 1, 1), (1, 1, 1), (1, 1, 2), (0, 1, 3), (1, 2, 3)]

# R3: these two helpers now live in samples/base.py (they were duplicated
# verbatim here and in dislocation_crystal.py). Imported into this namespace,
# and `_rot_axis_to_beam` kept as an alias, so existing callers still work.
from .base import rotation_taking_to_beam, projected_column_spacing_A  # noqa: E402,F401
_rot_axis_to_beam = rotation_taking_to_beam


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
            # "random_zone_axes" = DEFAULT. Each grain is placed on a DIFFERENT
            #   low-index zone axis (plus a random spin about the beam), so grains
            #   genuinely differ AND stay resolvable.
            # "random_3d" = each grain gets a uniformly random 3-D orientation.
            #   More honest for an untextured polycrystal, but a random orientation
            #   is almost never near a zone axis, so most grains show no resolvable
            #   columns.
            # "in_plane"  = legacy: every grain keeps [001] along the beam and is
            #   only spun about it (all grains give the same square net, rotated).
            "orientation_mode": "random_zone_axes",
            "max_tilt_deg": 0.0,   # only used by the legacy "in_plane" mode
        },
        param_schema={
            "n_grains":        {"type": "int",   "min": 2,    "max": 12},
            "seed":            {"type": "int",   "min": 0,    "max": 2**31-1},
            "a_angstrom":      {"type": "float", "min": 1.0,  "max": 20.0},
            "atomic_number":   {"type": "int",   "min": 1,    "max": 100},
            "base_level":      {"type": "float", "min": 0,    "max": 1000},
            "grain_intensity": {"type": "float", "min": 100,  "max": 60000},
            "sigma_px":        {"type": "float", "min": 0.5,  "max": 4.0},
            "orientation_mode": {"type": "str", "choices": ["random_zone_axes", "random_3d", "in_plane"]},
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

    @staticmethod
    def _uniform_random_rotation(rng):
        """A rotation drawn UNIFORMLY from SO(3) (Shoemake's quaternion method).

        This is what gives a grain a genuinely random crystallographic
        orientation -- i.e. a random zone axis along the beam -- rather than the
        same zone axis merely spun about the beam.
        """
        u1, u2, u3 = rng.random(3)
        q1 = np.sqrt(1.0 - u1) * np.sin(2 * np.pi * u2)
        q2 = np.sqrt(1.0 - u1) * np.cos(2 * np.pi * u2)
        q3 = np.sqrt(u1) * np.sin(2 * np.pi * u3)
        q4 = np.sqrt(u1) * np.cos(2 * np.pi * u3)
        x, y, z, w = q1, q2, q3, q4
        return np.array([
            [1 - 2*(y*y + z*z), 2*(x*y - z*w),     2*(x*z + y*w)],
            [2*(x*y + z*w),     1 - 2*(x*x + z*z), 2*(y*z - x*w)],
            [2*(x*z - y*w),     2*(y*z + x*w),     1 - 2*(x*x + y*y)],
        ], dtype=np.float64)

    def _grain_setup(self, H, W):
        """Grain seed points (in voxels) and a deterministic orientation each.

        `orientation_mode` controls what "orientation" means:

        * "random_zone_axes" (DEFAULT): each grain is placed on a DIFFERENT
          low-index zone axis from GRAIN_ZONE_AXES, plus a random spin about the
          beam. Grains therefore differ in symmetry and spot spacing (not merely
          in rotation) while every grain stays ON a zone axis, so its projected
          columns remain resolvable. This is the mode to use when you want to SEE
          the orientation change as you pan across a boundary.

        * "random_3d" (physically realistic): each grain gets a UNIFORMLY RANDOM
          3-D orientation, so different grains present DIFFERENT ZONE AXES to the
          beam -- which is what a real randomly-textured polycrystal does. Note
          the trade-off: a random orientation is almost never near a zone axis, so
          most grains show NO resolvable atomic columns and only sparse,
          asymmetric spots. Realistic, but less legible than random_zone_axes.

        * "in_plane" (legacy): every grain keeps [001] along the beam and is only
          spun about the beam by a distinct angle, optionally tipped off-zone by
          up to `max_tilt_deg`. Every grain then gives the SAME square [001] net,
          just rotated. Kept only for the clean, didactic orientation-mapping
          demo; it is NOT what a real polycrystal does.
        """
        rng = np.random.default_rng(int(self.params["seed"]))
        ng = int(self.params["n_grains"])
        seeds_xy = np.column_stack([rng.uniform(0.1*W, 0.9*W, ng),
                                    rng.uniform(0.1*H, 0.9*H, ng)])
        mode = str(self.params.get("orientation_mode", "random_zone_axes")).lower()
        rots = []

        if mode == "random_zone_axes":
            # Each grain is put on a DIFFERENT low-index zone axis (plus a random
            # in-plane spin). Because every grain is still ON a zone axis, each one
            # shows a genuinely different but RESOLVABLE column pattern -- square
            # for [001], hexagonal for [111], rectangular for [011] -- and a
            # different spot net in DIFF. This is the mode to use when you want to
            # SEE the orientation change as you pan across a boundary.
            for g in range(ng):
                rg = np.random.default_rng(int(self.params["seed"]) * 1000 + g)
                zone = GRAIN_ZONE_AXES[rg.integers(0, len(GRAIN_ZONE_AXES))]
                R = _rot_axis_to_beam(zone)
                th = rg.uniform(0, 2 * np.pi)          # random spin about the beam
                Rz = np.array([[np.cos(th), -np.sin(th), 0],
                               [np.sin(th),  np.cos(th), 0],
                               [0, 0, 1.0]])
                rots.append(Rz @ R)
            return seeds_xy, rots

        if mode == "random_3d":
            # Uniformly random orientation per grain -- the physically honest model
            # of an untextured polycrystal. NOTE: a random orientation is almost
            # never near a zone axis, so most grains show NO resolvable atomic
            # columns (their projected atoms blur together) and only sparse,
            # asymmetric spots. Realistic, but less legible than random_zone_axes.
            for g in range(ng):
                rg = np.random.default_rng(int(self.params["seed"]) * 1000 + g)
                rots.append(self._uniform_random_rotation(rg))
            return seeds_xy, rots

        # ---- legacy "in_plane" mode ----
        base_angles = np.linspace(0, np.pi/2, ng, endpoint=False) + rng.uniform(0, 0.3, ng)
        max_tilt = np.deg2rad(float(self.params.get("max_tilt_deg", 0.0)))
        for g in range(ng):
            th = base_angles[g]
            Rz = np.array([[np.cos(th), -np.sin(th), 0],
                           [np.sin(th),  np.cos(th), 0],
                           [0, 0, 1.0]])
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

    def lattice_at(self, cx_um, cy_um):
        """The ORIENTED lattice of the grain under a given specimen position.

        The server's high-magnification atomic-column renderer asks the sample for
        a single `lattice`; for a polycrystal that would draw the same columns
        everywhere. If the server calls `lattice_at(cx_um, cy_um)` (see the small
        hook in the notes accompanying this file), each grain shows the columns of
        ITS OWN orientation, so panning across a boundary visibly changes the
        atomic pattern. Returns None if the volume has not been generated yet.
        """
        if not hasattr(self, "_seeds_xy") or not hasattr(self, "_vol_shape"):
            return None
        D, H, W = self._vol_shape
        px_per_um_x = W / self.sample_length_um
        px_per_um_y = H / self.sample_width_um
        xv = float(np.clip(W / 2.0 + cx_um * px_per_um_x, 0, W - 1))
        yv = float(np.clip(H / 2.0 + cy_um * px_per_um_y, 0, H - 1))
        g = self._owner_at(xv, yv)
        R = self._rots[g]
        return CrystalLattice(
            real_vectors=self.lattice.real_vectors @ R.T,
            basis=self.lattice.basis,
            name=f"{self.lattice.name}-grain{g}")

    def grain_at(self, cx_um, cy_um):
        """Index of the grain under a specimen position (handy for the GUI)."""
        if not hasattr(self, "_seeds_xy") or not hasattr(self, "_vol_shape"):
            return None
        D, H, W = self._vol_shape
        xv = float(np.clip(W / 2.0 + cx_um * (W / self.sample_length_um), 0, W - 1))
        yv = float(np.clip(H / 2.0 + cy_um * (H / self.sample_width_um), 0, H - 1))
        return self._owner_at(xv, yv)

    def _owner_at(self, x_vox, y_vox):
        """Index of the grain owning a voxel location (nearest seed = Voronoi)."""
        d2 = (self._seeds_xy[:, 0] - x_vox)**2 + (self._seeds_xy[:, 1] - y_vox)**2
        return int(np.argmin(d2))

    def column_spacing_A(self, lattice=None):
        """True projected atomic-column spacing (A) for the beam direction.
        The server's high-mag column renderer should gate on this, not on the
        cell-vector length -- see projected_column_spacing_A()."""
        lat = lattice if lattice is not None else self.lattice
        return projected_column_spacing_A(lat)

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