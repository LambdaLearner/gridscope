"""
samples/hcp_single_crystal.py
Hexagonal close-packed single crystal — clean Mg (no defects). Two-atom basis in
a hexagonal cell with c/a ratio. Carries a CrystalLattice so the server renders
real kinematical diffraction (hexagonal reciprocal lattice -> characteristic
6-fold symmetry down the c-axis). Edge dislocations live in `dislocation_crystal`.
"""
import numpy as np
from .base import Sample, SampleMetadata, CrystalLattice, make_lamella_slab, atoms_in_requested_box
from . import register


@register
class HCPSingleCrystal(Sample):
    feature_scale_nm = 0.2   # atomic-column spacing (~0.2 nm)
    meta = SampleMetadata(
        name="hcp_single_crystal",
        display_name="Mg (HCP)",
        description="Hexagonal close-packed single-crystal magnesium (clean).",
        default_params={
            "a_px": 22,            # in-plane lattice spacing in pixels
            "sigma_px": 1.1,
            "base_level": 80.0,
            "atom_intensity": 9000.0,
            "a_angstrom": 3.209,   # Mg basal lattice parameter
            "c_over_a": 1.624,     # Mg c/a ratio (near-ideal)
            "atomic_number": 12,   # Mg
        },
        param_schema={
            "a_px":           {"type": "int",   "min": 8,   "max": 64},
            "sigma_px":       {"type": "float", "min": 0.5, "max": 4.0},
            "base_level":     {"type": "float", "min": 0,   "max": 1000},
            "atom_intensity": {"type": "float", "min": 100, "max": 60000},
            "a_angstrom":     {"type": "float", "min": 1.0, "max": 20.0},
            "c_over_a":       {"type": "float", "min": 1.0, "max": 2.5},
            "atomic_number":  {"type": "int",   "min": 1,   "max": 100},
        },
    )

    def __init__(self, **params):
        super().__init__(**params)
        a = float(self.params["a_angstrom"])
        c = a * float(self.params["c_over_a"])
        Z = int(self.params["atomic_number"])
        # Hexagonal lattice vectors:
        # a1 = a (1,0,0); a2 = a (-1/2, sqrt(3)/2, 0); a3 = c (0,0,1)
        a1 = np.array([a, 0.0, 0.0])
        a2 = np.array([-0.5 * a, np.sqrt(3) / 2 * a, 0.0])
        a3 = np.array([0.0, 0.0, c])
        self.lattice = CrystalLattice(
            real_vectors=np.array([a1, a2, a3], dtype=np.float64),
            basis=[
                ((0.0, 0.0, 0.0), Z),
                ((1.0/3.0, 2.0/3.0, 0.5), Z),
            ],
            name="HCP",
        )

    def get_atoms_in_region(self, cx_um, cy_um, half_width_um, depth_nm):
        """Atoms really present in the requested region (single source of truth for
        both the atomic-column image and the diffraction pattern). Small imaging
        FOV -> exactly those atoms; huge SAED aperture -> a representative cube."""
        from .base import tile_lattice_in_region  # noqa: F401  (used indirectly)
        half_A = max(1.0, float(half_width_um) * 1.0e4)
        depth_A = max(1.0, float(depth_nm) * 10.0)
        pos, Z, _rep = atoms_in_requested_box(self.lattice, half_A, depth_A)
        return pos.astype(np.float64), Z.astype(np.int32)

    def generate_volume(self, D, H, W):
        p = self.params
        # A single crystal is a roughly uniform slab in HAADF at these scales;
        # the crystallinity is in the diffraction (get_atoms_in_region). Render
        # the lamella footprint in vacuum (see make_lamella_slab).
        return make_lamella_slab(
            D, H, W,
            generation_range_um=self.generation_range_um,
            sample_length_um=self.sample_length_um,
            sample_width_um=self.sample_width_um,
            base_level=float(p.get("base_level", 90.0)),
            slab_level=38000.0,
            texture=0.05, seed=1)
