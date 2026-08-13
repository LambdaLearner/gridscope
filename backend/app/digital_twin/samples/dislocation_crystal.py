"""
samples/dislocation_crystal.py
Fe FCC single crystal containing MANY edge dislocations, viewed down a
CONFIGURABLE ZONE AXIS (default [111]).

Each dislocation's isotropic-elasticity displacement field is applied to the atom
positions, so diffraction shows the cumulative local lattice distortion (streaking
/ spot broadening / mosaic spread) and the high-mag atomic-column image shows the
distorted lattice around each core.

ORIENTATION
-----------
`zone_axis` rotates the whole crystal so that crystallographic direction points
along the beam (+z). Down [111] an FCC crystal projects as the characteristic
HEXAGONAL column pattern (6-fold) instead of the square [001] net -- that is the
view you want for looking at cores on the (111) slip plane.

Honest note on the geometry: the dislocation LINES in this model run along the
beam, so cores are always seen END-ON (that is what makes a core visible at all).
For FCC the real slip system is {111}<110>: an edge dislocation gliding on (111)
with b = a/2<110> has line direction along <112>. So the strictly correct
"end-on edge dislocation on the (111) glide plane" view is zone_axis="112", which
this file also supports. zone_axis="111" gives the hexagonal (111) projection with
cores end-on -- the requested view, and the most legible for finding cores -- but
treat the line direction there as a modelling convenience rather than a claim
about FCC slip crystallography.

The Burgers vector magnitude defaults to a/sqrt(2) (= |a/2<110>|), the real FCC
slip vector, rather than the full lattice parameter.
"""
import numpy as np
from .base import (Sample, SampleMetadata, CrystalLattice, tile_lattice_in_region,
                   atoms_in_requested_box, make_lamella_slab,
                   rotation_taking_to_beam, projected_column_spacing_A)  # noqa: F401
# rotation_taking_to_beam / projected_column_spacing_A now live in base.py (R3).
# They are imported into this namespace so `from .dislocation_crystal import
# projected_column_spacing_A` keeps working for any existing caller.
from . import register


# Named zone axes (string keys keep this GUI/JSON friendly).
ZONE_AXES = {
    "001": (0.0, 0.0, 1.0),    # square net (the old behaviour)
    "011": (0.0, 1.0, 1.0),
    "110": (1.0, 1.0, 0.0),
    "111": (1.0, 1.0, 1.0),    # hexagonal projection -- default
    "112": (1.0, 1.0, -2.0),   # end-on edge dislocation on the (111) glide plane
}


@register
class DislocationCrystal(Sample):
    feature_scale_nm = 0.25   # lattice fringe spacing (~0.25 nm)
    meta = SampleMetadata(
        name="dislocation_crystal",
        display_name="Fe FCC [111] with Edge Dislocations (many)",
        description=("Fe FCC crystal with a field of many edge dislocations, "
                     "viewed down a configurable zone axis (default [111])."),
        default_params={
            "a_angstrom": 3.571,        # gamma-Fe (austenite)
            "atomic_number": 26,        # Fe
            "zone_axis": "111",         # beam direction: 001|011|110|111|112
            "n_dislocations": 12,       # number of edge dislocations in the region
            "burgers_A": 2.525,         # |a/2<110>| = a/sqrt(2) for a=3.571 (FCC slip)
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
            "zone_axis":      {"type": "str",   "choices": ["001", "011", "110", "111", "112"]},
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
        # Cube-axis FCC cell, then rotate so the requested zone axis is along the beam.
        cube = np.array([[a, 0, 0], [0, a, 0], [0, 0, a]], dtype=np.float64)
        key = str(self.params.get("zone_axis", "111"))
        zone = ZONE_AXES.get(key, ZONE_AXES["111"])
        self.zone_axis_hkl = zone
        R = rotation_taking_to_beam(zone)
        self.orientation_R = R
        self.lattice = CrystalLattice(
            real_vectors=cube @ R.T,          # rotated cell -> zone axis || beam
            basis=[((0, 0, 0), Z), ((0, 0.5, 0.5), Z),
                   ((0.5, 0, 0.5), Z), ((0.5, 0.5, 0), Z)],
            name=f"FCC-dislocation[{key}]")

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
        """Superpose the displacement fields of many edge dislocations. Lines run
        along the beam (z) so cores are seen END-ON; the Burgers vector lies in the
        plane perpendicular to the beam (for zone_axis='111' that plane is the
        (111) glide plane, so b = a/2<110> lies in it, as it physically should).
        Classic isotropic elasticity (Hirth & Lothe), softened core."""
        b = float(self.params["burgers_A"])
        nu = float(self.params["poisson_ratio"])
        cores, signs = self._dislocation_cores(half_A)
        out = pos.copy()
        for (cx, cy), sgn in zip(cores, signs):
            x = pos[:, 0] - cx
            y = pos[:, 1] - cy
            r2 = x * x + y * y + 1.0     # +1 softens the core singularity
            ux = sgn * (b / (2 * np.pi)) * (np.arctan2(y, x) + (x * y) / (2 * (1 - nu) * r2))
            uy = sgn * -(b / (2 * np.pi)) * ((1 - 2 * nu) / (4 * (1 - nu)) * np.log(r2)
                                             + (x * x - y * y) / (4 * (1 - nu) * r2))
            out[:, 0] += ux
            out[:, 1] += uy
        return out

    def column_spacing_A(self, lattice=None):
        """True projected atomic-column spacing (A) for the current beam direction.

        R2: the server gates its high-magnification column renderer on
        `hasattr(sample, "column_spacing_A")`. Without this method the gate fell
        back to the cell-vector length -- 3.571 A -- while the real projected
        spacing down the default [111] is a/sqrt(6) = 1.458 A. That 2.45x
        overestimate let the renderer draw columns whose true period was ~1.4 px,
        below the 2 px Nyquist limit, aliasing them into a moire grid.

        Overestimate by zone axis, cell vector vs true projected spacing:
            [001] 3.571 / 1.786 = 2.00x     [011] 3.571 / 2.187 = 1.63x
            [111] 3.571 / 1.458 = 2.45x     [112] 3.571 / 1.263 = 2.83x
        """
        lat = lattice if lattice is not None else self.lattice
        return projected_column_spacing_A(lat)

    def get_atoms_in_region(self, cx_um, cy_um, half_width_um, depth_nm):
        """Return the atoms REALLY PRESENT in the requested region, with the
        dislocation strain fields applied.

        This is the single source of truth for BOTH imaging and diffraction: the
        server's atomic-column renderer and the kinematical diffraction engine
        both call this, so whatever the generated sample contains (strain fields,
        zone-axis orientation) is what gets imaged AND what diffracts.

        For a small imaging FOV the atoms returned are exactly those in the field.
        For a large SAED aperture (~1e8 atoms) a representative cube is returned
        instead (see atoms_in_requested_box).
        """
        half_A = max(1.0, float(half_width_um) * 1.0e4)
        depth_A = max(1.0, float(depth_nm) * 10.0)
        bp, bZ, is_rep = atoms_in_requested_box(self.lattice, half_A, depth_A)
        if len(bp) == 0:
            return np.zeros((0, 3)), np.zeros(0, dtype=np.int32)
        # strain acts over whatever box we actually returned
        box_half_A = half_A if not is_rep else float(np.abs(bp[:, :2]).max() + 1e-6)
        if int(self.params.get("n_dislocations", 12)) > 0:
            bp = self._apply_edge_dislocations(bp, box_half_A)
        return bp.astype(np.float64), bZ.astype(np.int32)

    def generate_volume(self, D, H, W):
        p = self.params
        self._vol_shape = (D, H, W)
        # Like the other crystals, the dislocated crystal is a roughly uniform slab
        # in HAADF at low/moderate magnification (the strain fields modulate the
        # image only subtly). Atomic columns appear at high magnification via the
        # server's real-atom projection (which uses this sample's rotated lattice
        # and dislocated atoms, so the columns show both the [111] hexagonal
        # symmetry and the strain). The defect signature is clearest in DIFFRACTION
        # (broadened / streaked spots).
        return make_lamella_slab(
            D, H, W,
            generation_range_um=self.generation_range_um,
            sample_length_um=self.sample_length_um,
            sample_width_um=self.sample_width_um,
            base_level=float(p.get("base_level", 90.0)),
            slab_level=41000.0, texture=0.06, seed=int(p.get("disl_seed", 7)))
