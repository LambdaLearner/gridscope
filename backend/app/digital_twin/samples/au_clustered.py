"""
samples/au_clustered.py
Clustered Au nanoparticles — particles are grouped into N clusters scattered
across the volume, with a small fraction of isolated background particles for
realism. Useful for testing shape/morphology detection, cluster counting, and
dispersion-metric routines.
"""
import numpy as np
from .base import Sample, SampleMetadata
from . import register


@register
class AuClusteredNanoparticles(Sample):
    feature_scale_nm = 2.0   # small nanoparticle diameter (~2 nm)
    meta = SampleMetadata(
        name="au_clustered",
        display_name="Au Nanoparticles (Clustered)",
        description="Gold nanoparticles grouped into clusters, plus a few isolated particles.",
        default_params={
            "n_clusters": 25,                # number of cluster centers (in the XY plane)
            "particles_per_cluster_mean": 40,
            "particles_per_cluster_std": 12,
            "cluster_radius_px_mean": 60.0,  # spatial spread of a cluster (voxels)
            "cluster_radius_px_std": 20.0,
            "isolated_fraction": 0.05,       # fraction of total particles placed uniformly
            "seed": 7,
            "base_level": 150.0,
            "base_noise": 6.0,
            # particle radius ranges (voxels) — slightly tighter than dispersed
            "rz_min": 1, "rz_max": 5,
            "ry_min": 3, "ry_max": 14,
            "rx_min": 3, "rx_max": 14,
            "intensity_min": 800.0,
            "intensity_max": 6000.0,
            "profile_sharpness": 2.2,
        },
        param_schema={
            "n_clusters":                 {"type": "int",   "min": 1,    "max": 1000},
            "particles_per_cluster_mean": {"type": "int",   "min": 1,    "max": 2000},
            "particles_per_cluster_std":  {"type": "int",   "min": 0,    "max": 500},
            "cluster_radius_px_mean":     {"type": "float", "min": 1.0,  "max": 1000.0},
            "cluster_radius_px_std":      {"type": "float", "min": 0.0,  "max": 500.0},
            "isolated_fraction":          {"type": "float", "min": 0.0,  "max": 1.0},
            "seed":                       {"type": "int",   "min": 0,    "max": 2**31-1},
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

        # 1. Generate cluster centers (in XY, with z spanning the slab)
        n_clusters = int(p["n_clusters"])
        cluster_cx = rng.uniform(0, W, size=n_clusters)
        cluster_cy = rng.uniform(0, H, size=n_clusters)
        cluster_radii = np.maximum(
            1.0,
            rng.normal(float(p["cluster_radius_px_mean"]),
                       float(p["cluster_radius_px_std"]),
                       size=n_clusters),
        )

        # 2. For each cluster, generate a list of particle centers
        all_centers = []  # list of (cz, cy, cx)
        total_clustered = 0
        for k in range(n_clusters):
            n_in = max(
                1,
                int(rng.normal(float(p["particles_per_cluster_mean"]),
                               float(p["particles_per_cluster_std"]))),
            )
            # Gaussian spread around the cluster center in XY,
            # uniform across Z (thin slab anyway).
            dx = rng.normal(0.0, cluster_radii[k], size=n_in)
            dy = rng.normal(0.0, cluster_radii[k], size=n_in)
            cx = np.clip(cluster_cx[k] + dx, 0, W - 1)
            cy = np.clip(cluster_cy[k] + dy, 0, H - 1)
            cz = rng.integers(0, D, size=n_in)
            for i in range(n_in):
                all_centers.append((int(cz[i]), int(cy[i]), int(cx[i])))
            total_clustered += n_in

        # 3. Add isolated background particles
        iso_n = int(total_clustered * float(p["isolated_fraction"]) /
                    max(1e-6, (1.0 - float(p["isolated_fraction"]))))
        for _ in range(iso_n):
            all_centers.append((
                int(rng.integers(0, D)),
                int(rng.integers(0, H)),
                int(rng.integers(0, W)),
            ))

        # 4. Splat each particle as a 3D Gaussian ellipsoid
        for cz, cy, cx in all_centers:
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
