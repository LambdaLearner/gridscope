"""
samples/bcc_single_crystal.py
Body-centered cubic single crystal (e.g. alpha-Fe, W, Mo). Two-atom basis.
Carries a CrystalLattice so the server can render real kinematical diffraction.
"""
import numpy as np
from .base import Sample, SampleMetadata, CrystalLattice
from . import register


@register
class BCCSingleCrystal(Sample):
    feature_scale_nm = 0.2   # atomic-column spacing (~0.2 nm)
    meta = SampleMetadata(
        name="bcc_single_crystal",
        display_name="BCC Single Crystal",
        description="Body-centered cubic single-crystal volume (Fe/W-like).",
        default_params={
            "a_px": 24,
            "sigma_px": 1.1,
            "base_level": 80.0,
            "atom_intensity": 9000.0,
            "a_angstrom": 2.87,    # alpha-Fe lattice parameter
            "atomic_number": 26,   # Fe
        },
        param_schema={
            "a_px":           {"type": "int",   "min": 8,   "max": 64},
            "sigma_px":       {"type": "float", "min": 0.5, "max": 4.0},
            "base_level":     {"type": "float", "min": 0,   "max": 1000},
            "atom_intensity": {"type": "float", "min": 100, "max": 60000},
            "a_angstrom":     {"type": "float", "min": 1.0, "max": 20.0},
            "atomic_number":  {"type": "int",   "min": 1,   "max": 100},
        },
    )

    def __init__(self, **params):
        super().__init__(**params)
        a = float(self.params["a_angstrom"])
        Z = int(self.params["atomic_number"])
        self.lattice = CrystalLattice(
            real_vectors=np.array([[a, 0, 0], [0, a, 0], [0, 0, a]], dtype=np.float64),
            basis=[
                ((0.0, 0.0, 0.0), Z),
                ((0.5, 0.5, 0.5), Z),
            ],
            name="BCC",
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
        a_px = int(p["a_px"])
        V = np.zeros((D, H, W), dtype=np.float32) + float(p["base_level"])

        basis = np.array([
            [0.0, 0.0, 0.0],
            [0.5, 0.5, 0.5],
        ], dtype=np.float32)

        nz = int(np.ceil(D / a_px)) + 2
        ny = int(np.ceil(H / a_px)) + 2
        nx = int(np.ceil(W / a_px)) + 2

        for iz in range(nz):
            for iy in range(ny):
                for ix in range(nx):
                    cell = np.array([iz, iy, ix], dtype=np.float32) * a_px
                    for b in basis:
                        pos = cell + b * a_px
                        z = int(round(pos[0]))
                        y = int(round(pos[1]))
                        x = int(round(pos[2]))
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
