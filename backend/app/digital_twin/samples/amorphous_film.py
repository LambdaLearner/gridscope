"""
samples/amorphous_film.py
Amorphous film: atoms placed with short-range order but no long-range lattice
(random close packing with a minimum-distance constraint). Diffraction shows
broad diffuse halos (amorphous rings), not sharp spots -- the correct signature
of an amorphous material.
"""
import numpy as np
from .base import Sample, SampleMetadata
from . import register


@register
class AmorphousFilm(Sample):
    feature_scale_nm = 0.3   # nearest-neighbour distance (~0.3 nm)
    meta = SampleMetadata(
        name="amorphous_film",
        display_name="Amorphous Film",
        description="Amorphous (non-crystalline) film -> diffuse diffraction halos.",
        default_params={
            "seed": 11,
            "atomic_number": 14,      # Si-like (light amorphous former)
            "nn_distance_A": 2.5,     # typical nearest-neighbour distance (Angstrom)
            "base_level": 120.0,
            "atom_intensity": 1200.0,
            "film_intensity_sigma_px": 1.3,
        },
        param_schema={
            "seed":           {"type": "int",   "min": 0,    "max": 2**31-1},
            "atomic_number":  {"type": "int",   "min": 1,    "max": 100},
            "nn_distance_A":  {"type": "float", "min": 1.5,  "max": 5.0},
            "base_level":     {"type": "float", "min": 0,    "max": 1000},
            "atom_intensity": {"type": "float", "min": 100,  "max": 60000},
        },
    )
    crystalline_particles = False  # amorphous

    def generate_volume(self, D, H, W):
        p = self.params
        self._vol_shape = (D, H, W)
        rng = np.random.default_rng(int(p["seed"]))
        # Simple amorphous texture in the image: filtered noise blobs
        V = rng.normal(float(p["base_level"]), 30.0, size=(D, H, W)).astype(np.float32)
        # add a band of denser material in the central slab
        zc = D // 2
        for z in range(max(0, zc-8), min(D, zc+8)):
            V[z] += float(p["atom_intensity"]) * 0.4 * np.exp(-((z-zc)/5.0)**2)
        def gfreq(n, s):
            f = np.fft.fftfreq(n).astype(np.float32)
            return np.exp(-2.0*(np.pi**2)*(s**2)*(f**2)).astype(np.float32)
        s = float(p["film_intensity_sigma_px"])
        F = np.fft.fftn(V)
        F *= gfreq(D,s)[:,None,None]; F *= gfreq(H,s)[None,:,None]; F *= gfreq(W,s)[None,None,:]
        V = np.clip(np.fft.ifftn(F).real, 0, 65535).astype(np.float32)
        return V

    def get_atoms_in_region(self, cx_um, cy_um, half_width_um, depth_nm):
        """Generate amorphous atoms (random close packing) within the region.
        Position-independent statistics (amorphous is uniform), so stage motion
        doesn't change the halo -- which is physically correct for a uniform
        amorphous film."""
        p = self.params
        rng = np.random.default_rng(int(p["seed"]))
        depth_A = depth_nm * 10.0
        # Use a fixed-size box that yields ~target atoms at the given nn distance
        nn = float(p["nn_distance_A"])
        number_density = 0.7 / (nn**3)   # ~RCP packing fraction proxy
        target = 60000
        # box volume to hit target: V = target/density; box is square in-plane * depth
        box_xy_A = float(np.sqrt(target / max(1e-9, number_density * depth_A)))
        half_A = box_xy_A / 2.0
        # Poisson-disk-ish: oversample random points then thin by min distance via grid
        n_try = int(target * 2.5)
        pts = np.column_stack([
            rng.uniform(-half_A, half_A, n_try),
            rng.uniform(-half_A, half_A, n_try),
            rng.uniform(-depth_A/2, depth_A/2, n_try),
        ])
        # grid-based thinning to enforce a minimum separation ~ nn
        cell = nn
        keys = np.floor(pts / cell).astype(np.int64)
        # keep first point per occupied cell (gives roughly nn spacing)
        seen = {}
        keep = np.zeros(len(pts), dtype=bool)
        for i in range(len(pts)):
            k = (keys[i,0], keys[i,1], keys[i,2])
            if k not in seen:
                seen[k] = True
                keep[i] = True
            if keep.sum() >= target:
                break
        pos = pts[keep]
        Z = np.full(len(pos), int(p["atomic_number"]), dtype=np.int32)
        return pos.astype(np.float64), Z
