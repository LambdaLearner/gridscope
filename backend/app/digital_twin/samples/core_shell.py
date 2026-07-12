"""
samples/core_shell.py
Core-shell nanoparticles: each particle is two concentric ellipsoids — a bright
core (e.g. Au) surrounded by a lower-intensity shell (e.g. Ag or oxide). Useful
for testing Z-contrast analysis, radial intensity profiling, and segmentation
of multi-component particles.
"""
import numpy as np
from .base import Sample, SampleMetadata
from . import register


@register
class CoreShellNanoparticles(Sample):
    feature_scale_nm = 1.0   # shell thickness (~1 nm)
    meta = SampleMetadata(
        name="core_shell",
        display_name="Core-Shell Nanoparticles",
        description="Concentric bright-core / dim-shell particles for Z-contrast tests.",
        default_params={
            "n_particles": 250,
            "seed": 5,
            "base_level": 120.0,
            "base_noise": 5.0,
            # core radius range (voxels)
            "core_r_min": 4, "core_r_max": 10,
            # shell thickness added on top of core radius (voxels)
            "shell_thickness_min": 3, "shell_thickness_max": 8,
            # z-radius scaling relative to in-plane radius (thin-slab anisotropy)
            "z_scale": 0.5,
            "core_intensity_min": 4000.0,
            "core_intensity_max": 8000.0,
            "shell_intensity_min": 800.0,
            "shell_intensity_max": 2500.0,
            "core_sharpness": 3.0,
            "shell_sharpness": 2.0,
        },
        param_schema={
            "n_particles":          {"type": "int",   "min": 0,   "max": 20000},
            "seed":                 {"type": "int",   "min": 0,   "max": 2**31-1},
            "core_r_min":           {"type": "int",   "min": 1,   "max": 50},
            "core_r_max":           {"type": "int",   "min": 1,   "max": 50},
            "shell_thickness_min":  {"type": "int",   "min": 0,   "max": 50},
            "shell_thickness_max":  {"type": "int",   "min": 0,   "max": 50},
            "z_scale":              {"type": "float", "min": 0.05, "max": 2.0},
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

        z_scale = float(p["z_scale"])
        core_sharp = float(p["core_sharpness"])
        shell_sharp = float(p["shell_sharpness"])

        for _ in range(int(p["n_particles"])):
            cz = int(rng.integers(0, D))
            cy = int(rng.integers(0, H))
            cx = int(rng.integers(0, W))

            core_r = int(rng.integers(int(p["core_r_min"]), int(p["core_r_max"]) + 1))
            shell_t = int(rng.integers(int(p["shell_thickness_min"]),
                                       int(p["shell_thickness_max"]) + 1))
            shell_r = core_r + shell_t

            core_rz = max(1, int(round(core_r * z_scale)))
            shell_rz = max(1, int(round(shell_r * z_scale)))
            self._particles.append({"center_vox": (cz, cy, cx),
                                    "radii_vox": (shell_rz, shell_r, shell_r)})

            core_I = float(rng.uniform(float(p["core_intensity_min"]),
                                       float(p["core_intensity_max"])))
            shell_I = float(rng.uniform(float(p["shell_intensity_min"]),
                                        float(p["shell_intensity_max"])))

            # bounding box uses the outer (shell) radius
            z0 = max(0, cz - shell_rz*2); z1 = min(D, cz + shell_rz*2 + 1)
            y0 = max(0, cy - shell_r*2);  y1 = min(H, cy + shell_r*2 + 1)
            x0 = max(0, cx - shell_r*2);  x1 = min(W, cx + shell_r*2 + 1)
            if z1 <= z0 or y1 <= y0 or x1 <= x0:
                continue

            zz, yy, xx = np.mgrid[z0:z1, y0:y1, x0:x1]
            dzf = (zz - cz).astype(np.float32)
            dyf = (yy - cy).astype(np.float32)
            dxf = (xx - cx).astype(np.float32)

            # shell ellipsoid (normalized distance, 1.0 at shell surface)
            d_shell = ((dxf*dxf)/(shell_r*shell_r + 1e-6)
                       + (dyf*dyf)/(shell_r*shell_r + 1e-6)
                       + (dzf*dzf)/(shell_rz*shell_rz + 1e-6))
            # core ellipsoid
            d_core = ((dxf*dxf)/(core_r*core_r + 1e-6)
                      + (dyf*dyf)/(core_r*core_r + 1e-6)
                      + (dzf*dzf)/(core_rz*core_rz + 1e-6))

            shell_profile = np.exp(-shell_sharp * d_shell).astype(np.float32)
            core_profile = np.exp(-core_sharp * d_core).astype(np.float32)

            # Make the shell *hollow*: suppress the shell contribution inside the
            # core radius so the two components are distinguishable. d_core < 1.0
            # means "inside the core ellipsoid".
            shell_only = shell_profile * np.clip(d_core, 0.0, 1.0)

            # shell forms a ring/annulus; core forms a bright center.
            # Together: bright center, dim surrounding shell, vacuum outside.
            V[z0:z1, y0:y1, x0:x1] += shell_I * shell_only
            V[z0:z1, y0:y1, x0:x1] += core_I * core_profile

        return np.clip(V, 0, 65535).astype(np.float32)
