"""
samples/au_on_substrate.py
Supported-catalyst style sample: a uniform low-Z substrate layer occupying the
lower part of the slab, with Au nanoparticles sitting on top of it. Simulates
nanoparticles supported on a carbon / oxide film, as in heterogeneous catalysis.
"""
import numpy as np
from .base import Sample, SampleMetadata
from . import register


@register
class AuOnSubstrate(Sample):
    feature_scale_nm = 2.0   # small nanoparticle diameter (~2 nm)
    meta = SampleMetadata(
        name="au_on_substrate",
        display_name="Au on Substrate (Supported Catalyst)",
        description="Uniform low-Z substrate layer with Au nanoparticles resting on top.",
        default_params={
            "n_particles": 700,
            "seed": 17,
            "base_level": 60.0,
            "base_noise": 5.0,
            # substrate occupies z in [0, substrate_thickness_frac * D)
            "substrate_thickness_frac": 0.55,
            "substrate_intensity": 380.0,     # low-Z support contrast
            "substrate_texture": 40.0,         # random texture amplitude in substrate
            # particle radii (voxels)
            "rz_min": 2, "rz_max": 6,
            "ry_min": 4, "ry_max": 16,
            "rx_min": 4, "rx_max": 16,
            "intensity_min": 2000.0,
            "intensity_max": 7000.0,
            "profile_sharpness": 2.2,
            # how far above the substrate top particles can sit (voxels)
            "particle_z_jitter": 4,
        },
        param_schema={
            "n_particles":               {"type": "int",   "min": 0,   "max": 50000},
            "seed":                      {"type": "int",   "min": 0,   "max": 2**31-1},
            "substrate_thickness_frac":  {"type": "float", "min": 0.0, "max": 1.0},
            "substrate_intensity":       {"type": "float", "min": 0,   "max": 60000},
        },
    )

    crystalline_particles = True
    particles_random_orientation = True

    def generate_volume(self, D, H, W):
        self._particles = []; self._vol_shape = (D, H, W)
        p = self.params
        rng = np.random.default_rng(int(p["seed"]))
        V = rng.normal(loc=float(p["base_level"]),
                       scale=float(p["base_noise"]),
                       size=(D, H, W)).astype(np.float32)
        sharp = float(p["profile_sharpness"])

        # 1. Build the substrate slab in the lower portion of z
        sub_top = int(round(float(p["substrate_thickness_frac"]) * D))
        sub_top = max(1, min(D, sub_top))
        texture = rng.normal(0.0, float(p["substrate_texture"]),
                             size=(sub_top, H, W)).astype(np.float32)
        V[0:sub_top] += float(p["substrate_intensity"]) + texture

        # 2. Place particles resting on top of the substrate surface
        n = int(p["n_particles"])
        jitter = int(p["particle_z_jitter"])
        for _ in range(n):
            cy = int(rng.integers(0, H))
            cx = int(rng.integers(0, W))
            # particle center near the substrate top surface
            cz = int(np.clip(sub_top + rng.integers(-jitter, jitter + 1), 0, D - 1))

            rz = int(rng.integers(int(p["rz_min"]), int(p["rz_max"]) + 1))
            ry = int(rng.integers(int(p["ry_min"]), int(p["ry_max"]) + 1))
            rx = int(rng.integers(int(p["rx_min"]), int(p["rx_max"]) + 1))
            self._particles.append({"center_vox": (cz, cy, cx), "radii_vox": (rz, ry, rx)})
            intensity = float(rng.uniform(float(p["intensity_min"]),
                                          float(p["intensity_max"])))

            z0 = max(0, cz - rz*2); z1 = min(D, cz + rz*2 + 1)
            y0 = max(0, cy - ry*2); y1 = min(H, cy + ry*2 + 1)
            x0 = max(0, cx - rx*2); x1 = min(W, cx + rx*2 + 1)
            if z1 <= z0 or y1 <= y0 or x1 <= x0:
                continue

            zz, yy, xx = np.mgrid[z0:z1, y0:y1, x0:x1]
            d = (((xx - cx).astype(np.float32)**2)/(rx*rx + 1e-6)
                 + ((yy - cy).astype(np.float32)**2)/(ry*ry + 1e-6)
                 + ((zz - cz).astype(np.float32)**2)/(rz*rz + 1e-6))
            profile = np.exp(-sharp * d).astype(np.float32)
            V[z0:z1, y0:y1, x0:x1] += intensity * profile

        return np.clip(V, 0, 65535).astype(np.float32)
