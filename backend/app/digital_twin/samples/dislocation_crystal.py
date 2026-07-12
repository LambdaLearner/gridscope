"""
samples/dislocation_crystal.py
FCC single crystal containing an edge dislocation. The dislocation displacement
field is applied to the atom positions, so diffraction shows the local lattice
distortion (streaking / spot broadening near the core) -- a defect signature.
"""
import numpy as np
from .base import Sample, SampleMetadata, CrystalLattice, tile_lattice_in_region
from . import register


@register
class DislocationCrystal(Sample):
    feature_scale_nm = 0.25   # lattice fringe spacing (~0.25 nm)
    sample_fov_um = 0.5
    meta = SampleMetadata(
        name="dislocation_crystal",
        display_name="FCC Crystal with Edge Dislocation",
        description="FCC single crystal with an edge dislocation displacement field.",
        default_params={
            "a_angstrom": 4.05,
            "atomic_number": 79,
            "burgers_A": 4.05,          # Burgers vector magnitude (~ a)
            "poisson_ratio": 0.34,
            "base_level": 90.0,
            "atom_intensity": 9000.0,
            "sigma_px": 1.1,
            "a_px": 24,
        },
        param_schema={
            "a_angstrom":     {"type": "float", "min": 1.0,  "max": 20.0},
            "atomic_number":  {"type": "int",   "min": 1,    "max": 100},
            "burgers_A":      {"type": "float", "min": 0.5,  "max": 10.0},
            "poisson_ratio":  {"type": "float", "min": 0.0,  "max": 0.5},
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

    def _apply_edge_dislocation(self, pos):
        """Apply the displacement field of an edge dislocation lying along z with
        Burgers vector b along x. Classic isotropic elasticity solution."""
        b = float(self.params["burgers_A"])
        nu = float(self.params["poisson_ratio"])
        x = pos[:,0].copy(); y = pos[:,1].copy()
        r2 = x*x + y*y + 1.0  # +1 to soften the core singularity
        # ux, uy from Hirth & Lothe (edge dislocation)
        ux = (b/(2*np.pi)) * (np.arctan2(y, x) + (x*y)/(2*(1-nu)*r2))
        uy = -(b/(2*np.pi)) * ((1-2*nu)/(4*(1-nu))*np.log(r2) + (x*x - y*y)/(4*(1-nu)*r2))
        out = pos.copy()
        out[:,0] += ux
        out[:,1] += uy
        return out

    def generate_volume(self, D, H, W):
        p = self.params
        self._vol_shape = (D, H, W)
        a_px = int(p["a_px"])
        V = np.zeros((D, H, W), dtype=np.float32) + float(p["base_level"])
        # Visualize: a dot lattice with an extra half-plane inserted above center
        cy, cx = H/2.0, W/2.0
        for iy in range(0, H, a_px):
            for ix in range(0, W, a_px):
                # insert extra half-plane: shift columns above the glide plane
                shift = 0.5 * a_px if (iy < cy) else 0.0
                xx = int(ix + shift) % W
                for zz in range(D//2-6, D//2+6):
                    V[zz, iy, xx] += float(p["atom_intensity"])
        def gfreq(n, s):
            f = np.fft.fftfreq(n).astype(np.float32)
            return np.exp(-2.0*(np.pi**2)*(s**2)*(f**2)).astype(np.float32)
        s = float(p["sigma_px"])
        F = np.fft.fftn(V)
        F *= gfreq(D,s)[:,None,None]; F *= gfreq(H,s)[None,:,None]; F *= gfreq(W,s)[None,None,:]
        V = np.clip(np.fft.ifftn(F).real, 0, 65535).astype(np.float32)
        return V

    def get_atoms_in_region(self, cx_um, cy_um, half_width_um, depth_nm):
        if not hasattr(self, "_vol_shape"):
            return None, None
        depth_A = depth_nm * 10.0
        half_A = max(30.0, half_width_um * 1e4 * 0.02)  # compress to ~100k atoms
        bp, bZ = tile_lattice_in_region(self.lattice, half_A, depth_A)
        if len(bp) == 0:
            return np.zeros((0,3)), np.zeros(0, dtype=np.int32)
        # apply the dislocation displacement field (core at region center)
        bp = self._apply_edge_dislocation(bp)
        if len(bp) > 100000:
            ii = np.random.default_rng(0).choice(len(bp), 100000, replace=False)
            bp = bp[ii]; bZ = bZ[ii]
        return bp.astype(np.float64), bZ.astype(np.int32)
