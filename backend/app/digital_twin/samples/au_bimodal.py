"""
samples/au_bimodal.py
Bimodal Au nanoparticles — two size populations (small + large) dispersed
uniformly. Useful for ML-based segmentation / size-classification tests where
the model must distinguish two distinct particle classes.
"""
import numpy as np
from .base import Sample, SampleMetadata
from . import register


@register
class AuBimodalNanoparticles(Sample):
    feature_scale_nm = 1.5   # smallest particle mode (~1.5 nm)
    meta = SampleMetadata(
        name="au_bimodal",
        display_name="Au Nanoparticles (Bimodal Size)",
        description="Two distinct size populations of Au nanoparticles, dispersed uniformly.",
        default_params={
            "n_small": 900,
            "n_large": 150,
            "seed": 31,
            "base_level": 150.0,
            "base_noise": 6.0,
            # small population radius ranges (voxels)
            "small_rz_min": 1, "small_rz_max": 3,
            "small_ry_min": 2, "small_ry_max": 5,
            "small_rx_min": 2, "small_rx_max": 5,
            # large population radius ranges (voxels)
            "large_rz_min": 2, "large_rz_max": 6,
            "large_ry_min": 12, "large_ry_max": 26,
            "large_rx_min": 12, "large_rx_max": 26,
            # intensity ranges per population
            "small_intensity_min": 600.0, "small_intensity_max": 2500.0,
            "large_intensity_min": 2500.0, "large_intensity_max": 7000.0,
            "profile_sharpness": 2.2,
        },
        param_schema={
            "n_small":        {"type": "int", "min": 0, "max": 50000},
            "n_large":        {"type": "int", "min": 0, "max": 50000},
            "seed":           {"type": "int", "min": 0, "max": 2**31-1},
        },
    )

    def _splat(self, V, rng, n, r_ranges, i_range, sharp, D, H, W):
        rz_min, rz_max, ry_min, ry_max, rx_min, rx_max = r_ranges
        i_min, i_max = i_range
        for _ in range(int(n)):
            cz = int(rng.integers(0, D))
            cy = int(rng.integers(0, H))
            cx = int(rng.integers(0, W))
            rz = int(rng.integers(rz_min, rz_max + 1))
            ry = int(rng.integers(ry_min, ry_max + 1))
            rx = int(rng.integers(rx_min, rx_max + 1))
            self._particles.append({"center_vox": (cz, cy, cx), "radii_vox": (rz, ry, rx)})
            intensity = float(rng.uniform(i_min, i_max))

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

        # small population
        self._splat(
            V, rng, p["n_small"],
            (int(p["small_rz_min"]), int(p["small_rz_max"]),
             int(p["small_ry_min"]), int(p["small_ry_max"]),
             int(p["small_rx_min"]), int(p["small_rx_max"])),
            (float(p["small_intensity_min"]), float(p["small_intensity_max"])),
            sharp, D, H, W,
        )
        # large population
        self._splat(
            V, rng, p["n_large"],
            (int(p["large_rz_min"]), int(p["large_rz_max"]),
             int(p["large_ry_min"]), int(p["large_ry_max"]),
             int(p["large_rx_min"]), int(p["large_rx_max"])),
            (float(p["large_intensity_min"]), float(p["large_intensity_max"])),
            sharp, D, H, W,
        )

        return np.clip(V, 0, 65535).astype(np.float32)
