"""
samples/hcp_single_crystal.py
Hexagonal close-packed single crystal (e.g. Ti, Mg, Zn, Co). Two-atom basis
in a hexagonal cell with c/a ratio. Carries a CrystalLattice so the server can
render real kinematical diffraction (note: hexagonal reciprocal lattice gives
the characteristic 6-fold diffraction symmetry down the c-axis).
"""
import numpy as np
from .base import Sample, SampleMetadata, CrystalLattice
from . import register


@register
class HCPSingleCrystal(Sample):
    feature_scale_nm = 0.2   # atomic-column spacing (~0.2 nm)
    meta = SampleMetadata(
        name="hcp_single_crystal",
        display_name="HCP Single Crystal",
        description="Hexagonal close-packed single-crystal volume (Ti/Mg-like).",
        default_params={
            "a_px": 22,            # in-plane lattice spacing in pixels
            "sigma_px": 1.1,
            "base_level": 80.0,
            "atom_intensity": 9000.0,
            "a_angstrom": 2.95,    # Ti basal lattice parameter
            "c_over_a": 1.587,     # ideal ~1.633; Ti ~1.587
            "atomic_number": 22,   # Ti
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
        """For a uniform crystal, the diffraction pattern is the same anywhere.
        We tile an approximately CUBIC region (equal extent in x, y, z) sized to
        the atom budget. A cube is important: a region much deeper than it is wide
        has an anisotropic shape transform (a broad pancake in qx/qy) that smears
        into a cloud at intermediate tilts. Keeping it cubic makes the shape
        transform isotropic so off-axis zone-axis patterns stay sparse and clean.
        (Thickness/relrod effects are exercised separately via the diffraction
        `thickness_nm` control, not by deforming this region.)"""
        from .base import tile_lattice_in_region
        a1, a2, a3 = self.lattice.real_vectors
        cell_vol = abs(np.dot(a1, np.cross(a2, a3)))
        density = len(self.lattice.basis) / cell_vol     # atoms / A^3
        target = 90000.0  # stay UNDER the 100k diffraction atom-cap so no random subsampling (which would break lattice interference and fill the background with a diffuse cloud)
        side_A = float((target / max(1e-9, density)) ** (1.0 / 3.0))
        half_A = side_A / 2.0
        return tile_lattice_in_region(self.lattice, half_A, side_A)

    def generate_volume(self, D, H, W):
        p = self.params
        a_px = float(p["a_px"])
        c_px = a_px * float(p["c_over_a"])
        V = np.zeros((D, H, W), dtype=np.float32) + float(p["base_level"])

        # In-plane (x,y) hexagonal lattice vectors in pixels
        v1 = np.array([a_px, 0.0])
        v2 = np.array([-0.5 * a_px, np.sqrt(3) / 2 * a_px])
        # Basis atoms: (frac along v1, frac along v2, z-fraction of c)
        basis_2d = [
            (0.0, 0.0, 0.0),
            (1.0/3.0, 2.0/3.0, 0.5),
        ]

        # Range of integer cell indices needed to tile the volume
        n_i = int(np.ceil(W / a_px)) + 3
        n_j = int(np.ceil(H / (np.sqrt(3) / 2 * a_px))) + 3
        n_layers = int(np.ceil(D / c_px)) + 3

        for layer in range(n_layers):
            z_base = layer * c_px
            for i in range(-2, n_i):
                for j in range(-2, n_j):
                    origin_xy = i * v1 + j * v2
                    for (f1, f2, fz) in basis_2d:
                        xy = origin_xy + f1 * v1 + f2 * v2
                        x = int(round(xy[0]))
                        y = int(round(xy[1]))
                        z = int(round(z_base + fz * c_px))
                        if 0 <= z < D and 0 <= y < H and 0 <= x < W:
                            V[z, y, x] += float(p["atom_intensity"])

        def gfreq(n, s):
            f = np.fft.fftfreq(n).astype(np.float32)
            return np.exp(-2.0 * (np.pi ** 2) * (s ** 2) * (f ** 2)).astype(np.float32)

        s = float(p["sigma_px"])
        gz, gy, gx = gfreq(D, s), gfreq(H, s), gfreq(W, s)
        F = np.fft.fftn(V)
        F *= gz[:, None, None]
        F *= gy[None, :, None]
        F *= gx[None, None, :]
        Vb = np.fft.ifftn(F).real.astype(np.float32)
        return np.clip(Vb, 0, 65535).astype(np.float32)
