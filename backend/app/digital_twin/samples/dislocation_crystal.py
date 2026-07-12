"""
samples/dislocation_crystal.py
Fe FCC single crystal containing MANY edge dislocations. Each dislocation's
isotropic-elasticity displacement field is applied to the atom positions, so
diffraction shows the cumulative local lattice distortion (streaking / spot
broadening / mosaic spread) -- the signature of a heavily dislocated (worked)
crystal. Contrast with the clean crystals, which give sharp spots.
"""
import numpy as np
from .base import Sample, SampleMetadata, CrystalLattice, tile_lattice_in_region, make_lamella_slab
from . import register


@register
class DislocationCrystal(Sample):
    feature_scale_nm = 0.25   # lattice fringe spacing (~0.25 nm)
    meta = SampleMetadata(
        name="dislocation_crystal",
        display_name="Fe FCC with Edge Dislocations (many)",
        description="Fe FCC crystal with a field of many edge dislocations.",
        default_params={
            "a_angstrom": 3.571,        # gamma-Fe (austenite)
            "atomic_number": 26,        # Fe
            "n_dislocations": 12,       # number of edge dislocations in the region
            "burgers_A": 3.571,         # Burgers vector magnitude (~ a)
            "poisson_ratio": 0.29,
            "disl_seed": 7,
            "base_level": 90.0,
            "atom_intensity": 9000.0,
            "sigma_px": 1.1,
            "a_px": 24,
        },
        param_schema={
            "a_angstrom":     {"type": "float", "min": 1.0,  "max": 20.0},
            "atomic_number":  {"type": "int",   "min": 1,    "max": 100},
            "n_dislocations": {"type": "int",   "min": 1,    "max": 40},
            "burgers_A":      {"type": "float", "min": 0.5,  "max": 10.0},
            "poisson_ratio":  {"type": "float", "min": 0.0,  "max": 0.49},
            "disl_seed":      {"type": "int",   "min": 0,    "max": 2**31-1},
            "base_level":     {"type": "float", "min": 0,    "max": 1000},
            "atom_intensity": {"type": "float", "min": 100,  "max": 60000},
            "sigma_px":       {"type": "float", "min": 0.5,  "max": 4.0},
            "a_px":           {"type": "int",   "min": 8,    "max": 64},
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
            name="FCC-dislocation")

    def _dislocation_cores(self, half_A):
        """Deterministic in-plane core positions (A) via disl_seed. Cores are kept
        away from the very edge so their strain fields act within the region."""
        n = int(self.params.get("n_dislocations", 12))
        rng = np.random.default_rng(int(self.params.get("disl_seed", 7)))
        cores = rng.uniform(-0.8 * half_A, 0.8 * half_A, size=(max(0, n), 2))
        # random Burgers sign per dislocation (edge dipoles / mixed population)
        signs = rng.choice([-1.0, 1.0], size=max(0, n))
        return cores, signs

    def _apply_edge_dislocations(self, pos, half_A):
        """Superpose the displacement fields of many edge dislocations (each line
        along the beam z, Burgers vector along x). Classic isotropic elasticity
        (Hirth & Lothe), softened core."""
        b = float(self.params["burgers_A"])
        nu = float(self.params["poisson_ratio"])
        cores, signs = self._dislocation_cores(half_A)
        out = pos.copy()
        for (cx, cy), sgn in zip(cores, signs):
            x = pos[:, 0] - cx
            y = pos[:, 1] - cy
            r2 = x * x + y * y + 1.0     # +1 softens the core singularity
            ux = sgn * (b/(2*np.pi)) * (np.arctan2(y, x) + (x*y)/(2*(1-nu)*r2))
            uy = sgn * -(b/(2*np.pi)) * ((1-2*nu)/(4*(1-nu))*np.log(r2)
                                         + (x*x - y*y)/(4*(1-nu)*r2))
            out[:, 0] += ux
            out[:, 1] += uy
        return out

    def get_atoms_in_region(self, cx_um, cy_um, half_width_um, depth_nm):
        """Tile an approximately cubic Fe-FCC region under the atom cap (no random
        subsampling, which would itself smear the pattern), then superpose the
        strain fields of many edge dislocations."""
        a1, a2, a3 = self.lattice.real_vectors
        cell_vol = abs(np.dot(a1, np.cross(a2, a3)))
        density = len(self.lattice.basis) / cell_vol
        target = 90000.0  # under the 100k cap -> no random subsampling
        side_A = float((target / max(1e-9, density)) ** (1.0 / 3.0))
        half_A = side_A / 2.0
        bp, bZ = tile_lattice_in_region(self.lattice, half_A, side_A)
        if len(bp) == 0:
            return np.zeros((0,3)), np.zeros(0, dtype=np.int32)
        if int(self.params.get("n_dislocations", 12)) > 0:
            bp = self._apply_edge_dislocations(bp, half_A)
        return bp.astype(np.float64), bZ.astype(np.int32)

    def generate_volume(self, D, H, W):
        p = self.params
        self._vol_shape = (D, H, W)
        # Like the other crystals, the dislocated crystal is a roughly uniform slab
        # in HAADF at low/moderate magnification (the strain fields modulate the
        # image only subtly). Atomic columns appear at high magnification via the
        # server's real-atom projection (which uses this sample's dislocated
        # get_atoms_in_region, so the columns show the strain). The defect signature
        # is clearest in DIFFRACTION (broadened/streaked spots).
        return make_lamella_slab(
            D, H, W,
            generation_range_um=self.generation_range_um,
            sample_length_um=self.sample_length_um,
            sample_width_um=self.sample_width_um,
            base_level=float(p.get("base_level", 90.0)),
            slab_level=41000.0, texture=0.06, seed=int(p.get("disl_seed", 7)))
