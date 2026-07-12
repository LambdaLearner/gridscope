"""
samples/au_dispersed.py
Dispersed Au nanoparticles — port of the original Au notebook generator.
Particles are placed uniformly at random across the volume.
"""
import numpy as np
from .base import Sample, SampleMetadata
from . import register


@register
class AuDispersedNanoparticles(Sample):
    feature_scale_nm = 2.0   # small nanoparticle diameter (~2 nm)
    meta = SampleMetadata(
        name="au_dispersed",
        display_name="Au Nanoparticles (Dispersed)",
        description="Gold nanoparticles distributed uniformly at random — the original Au sample.",
        default_params={
            "n_particles": 1200,
            "seed": 123,
            "base_level": 150.0,
            "base_noise": 6.0,
            # particle radius ranges (voxels)
            "rz_min": 1, "rz_max": 6,
            "ry_min": 3, "ry_max": 18,
            "rx_min": 3, "rx_max": 18,
            "intensity_min": 800.0,
            "intensity_max": 6000.0,
            "profile_sharpness": 2.2,
        },
        param_schema={
            "n_particles":        {"type": "int",   "min": 1,   "max": 50000},
            "seed":               {"type": "int",   "min": 0,   "max": 2**31-1},
            "base_level":         {"type": "float", "min": 0,   "max": 10000},
            "base_noise":         {"type": "float", "min": 0,   "max": 1000},
            "intensity_min":      {"type": "float", "min": 0,   "max": 60000},
            "intensity_max":      {"type": "float", "min": 0,   "max": 60000},
            "profile_sharpness":  {"type": "float", "min": 0.1, "max": 20.0},
        },
    )

    def generate_volume(self, D, H, W):
        p = self.params
        rng = np.random.default_rng(int(p["seed"]))
        V = rng.normal(loc=float(p["base_level"]),
                       scale=float(p["base_noise"]),
                       size=(D, H, W)).astype(np.float32)

        n = int(p["n_particles"])
        sharp = float(p["profile_sharpness"])
        self._particles = []   # record for atom-based diffraction
        self._vol_shape = (D, H, W)

        for _ in range(n):
            cz = int(rng.integers(0, D))
            cy = int(rng.integers(0, H))
            cx = int(rng.integers(0, W))

            rz = int(rng.integers(int(p["rz_min"]), int(p["rz_max"]) + 1))
            ry = int(rng.integers(int(p["ry_min"]), int(p["ry_max"]) + 1))
            rx = int(rng.integers(int(p["rx_min"]), int(p["rx_max"]) + 1))

            self._particles.append({"center_vox": (cz, cy, cx),
                                    "radii_vox": (rz, ry, rx)})

            intensity = float(rng.uniform(float(p["intensity_min"]),
                                          float(p["intensity_max"])))

            z0 = max(0, cz - rz*2); z1 = min(D, cz + rz*2 + 1)
            y0 = max(0, cy - ry*2); y1 = min(H, cy + ry*2 + 1)
            x0 = max(0, cx - rx*2); x1 = min(W, cx + rx*2 + 1)

            if z1 <= z0 or y1 <= y0 or x1 <= x0:
                continue

            zz, yy, xx = np.mgrid[z0:z1, y0:y1, x0:x1]
            dz = (zz - cz).astype(np.float32)
            dy = (yy - cy).astype(np.float32)
            dx = (xx - cx).astype(np.float32)

            d = ((dx*dx)/(rx*rx + 1e-6)
                 + (dy*dy)/(ry*ry + 1e-6)
                 + (dz*dz)/(rz*rz + 1e-6))
            profile = np.exp(-sharp * d).astype(np.float32)

            V[z0:z1, y0:y1, x0:x1] += intensity * profile

        return np.clip(V, 0, 65535).astype(np.float32)

    # Crystalline Au nanoparticles -> real spots/rings via the unified atom path.
    crystalline_particles = True
    particles_random_orientation = True
