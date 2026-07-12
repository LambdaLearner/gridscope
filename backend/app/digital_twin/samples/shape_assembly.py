"""
samples/shape_assembly.py
Assembly of random convex shapes (circles/ellipses, rectangles, hexagons) with
random rotations and aspect ratios, extruded through depth. Built on the user's
Shape Generator. Each shape is filled with crystalline Au atoms (so it diffracts)
OR amorphous atoms, selectable. Designed as a testbed for "find and characterize
isolated features" workflows.
"""
import numpy as np
from .base import Sample, SampleMetadata, atoms_in_particles
from . import register


def generate_shapes_array(height=600, width=800, num_shapes=200, min_size=8,
                          max_size=45, aspect_min=0.6, aspect_max=1.8, seed=None,
                          background_value=0.0, shape_intensity=1.0,
                          enable_rotation=True, non_overlapping=False,
                          shape_types=None, _return_placed=False):
    """Adapted from the user's Shape Generator. Returns the 2D array, and
    optionally the list of placed shapes (cy, cx, size, type, aspect, angle)."""
    if seed is not None:
        np.random.seed(seed)
    if shape_types is None:
        shape_types = ['circle', 'rect', 'hex']
    array = np.full((height, width), background_value, dtype=float)
    placed = []
    num_to_attempt = int(num_shapes * (2.0 if non_overlapping else 1.0)) + 100
    successful = 0
    for _ in range(num_to_attempt):
        if successful >= num_shapes:
            break
        size = np.random.randint(min_size, max_size + 1)
        aspect = np.random.uniform(aspect_min, aspect_max)
        shape_type = np.random.choice(shape_types)
        angle = np.random.uniform(0, 2*np.pi) if enable_rotation else 0.0
        cy = np.random.randint(0, height)
        cx = np.random.randint(0, width)
        if non_overlapping:
            overlaps = False
            for py, px, psize, _, _, _ in placed:
                if np.hypot(cy-py, cx-px) < (psize+size)*0.95:
                    overlaps = True; break
            if overlaps:
                continue
        y, x = np.ogrid[:height, :width]
        dy = y - cy; dx = x - cx
        ca, sa = np.cos(angle), np.sin(angle)
        dx_rot = dx*ca - dy*sa; dy_rot = dx*sa + dy*ca
        if shape_type == 'circle':
            mask = ((dx_rot/aspect)**2 + dy_rot**2) <= size**2
        elif shape_type == 'rect':
            mask = (np.abs(dx_rot) <= size*aspect) & (np.abs(dy_rot) <= size)
        else:  # hex
            dx_h = dx_rot/aspect; dy_h = dy_rot; s = size
            mask = ((np.abs(dx_h) <= s) & (np.abs(dy_h) <= s*0.866) &
                    (np.abs(dx_h*0.5 + dy_h*0.866) <= s) &
                    (np.abs(dx_h*0.5 - dy_h*0.866) <= s))
        array[mask] += shape_intensity
        placed.append((cy, cx, size, shape_type, aspect, angle))
        successful += 1
    if _return_placed:
        return array, placed
    return array


@register
class ShapeAssembly(Sample):
    feature_scale_nm = 30.0   # smallest shape feature (~30 nm)
    sample_fov_um = 5.0
    meta = SampleMetadata(
        name="shape_assembly",
        display_name="Shape Assembly (synthetic features)",
        description="Random rotated convex shapes extruded to 3D; testbed for feature-finding workflows.",
        default_params={
            "num_shapes": 40,
            "min_size": 8,
            "max_size": 28,
            "aspect_min": 0.6,
            "aspect_max": 1.8,
            "seed": 42,
            "non_overlapping": True,
            "crystalline": True,        # True -> shapes diffract as crystals; False -> amorphous
            "depth_fraction": 0.5,      # fraction of D each shape spans
            "base_level": 100.0,
            "shape_intensity": 4000.0,
            "sigma_px": 1.2,
        },
        param_schema={
            "num_shapes":     {"type": "int",   "min": 1,    "max": 400},
            "min_size":       {"type": "int",   "min": 2,    "max": 100},
            "max_size":       {"type": "int",   "min": 3,    "max": 200},
            "aspect_min":     {"type": "float", "min": 0.2,  "max": 2.0},
            "aspect_max":     {"type": "float", "min": 0.5,  "max": 5.0},
            "seed":           {"type": "int",   "min": 0,    "max": 2**31-1},
            "crystalline":    {"type": "int",   "min": 0,    "max": 1},
            "base_level":     {"type": "float", "min": 0,    "max": 1000},
            "shape_intensity":{"type": "float", "min": 100,  "max": 60000},
            "sigma_px":       {"type": "float", "min": 0.5,  "max": 4.0},
        },
    )

    @property
    def crystalline_particles(self):
        return bool(self.params.get("crystalline", True))

    particles_random_orientation = True

    def generate_volume(self, D, H, W):
        p = self.params
        self._vol_shape = (D, H, W)
        arr2d, placed = generate_shapes_array(
            height=H, width=W, num_shapes=int(p["num_shapes"]),
            min_size=int(p["min_size"]), max_size=int(p["max_size"]),
            aspect_min=float(p["aspect_min"]), aspect_max=float(p["aspect_max"]),
            seed=int(p["seed"]), shape_intensity=1.0, enable_rotation=True,
            non_overlapping=bool(p["non_overlapping"]),
            shape_types=['circle','rect','hex'], _return_placed=True)

        # Record each shape as a particle for the unified atom diffraction path.
        # Treat shape 'size' as the in-plane radius; z-extent = depth_fraction*D/2.
        rz = max(1, int(round(float(p["depth_fraction"]) * D / 2)))
        self._particles = []
        for (cy, cx, size, stype, aspect, angle) in placed:
            ry = int(round(size))
            rx = int(round(size * aspect))
            self._particles.append({"center_vox": (D//2, int(cy), int(cx)),
                                    "radii_vox": (rz, ry, rx)})

        # Build the 3D volume by extruding the 2D shape map through the central slab
        V = np.zeros((D, H, W), dtype=np.float32) + float(p["base_level"])
        zc = D // 2
        prof = np.zeros(D, dtype=np.float32)
        for z in range(D):
            prof[z] = np.exp(-((z - zc) / max(1, rz))**2)
        for z in range(D):
            if prof[z] > 0.02:
                V[z] += float(p["shape_intensity"]) * prof[z] * arr2d.astype(np.float32)

        def gfreq(n, s):
            f = np.fft.fftfreq(n).astype(np.float32)
            return np.exp(-2.0*(np.pi**2)*(s**2)*(f**2)).astype(np.float32)
        s = float(p["sigma_px"])
        F = np.fft.fftn(V)
        F *= gfreq(D,s)[:,None,None]; F *= gfreq(H,s)[None,:,None]; F *= gfreq(W,s)[None,None,:]
        V = np.clip(np.fft.ifftn(F).real, 0, 65535).astype(np.float32)
        return V
