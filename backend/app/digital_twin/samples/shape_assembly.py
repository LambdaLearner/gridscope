"""
samples/shape_assembly.py
Assembly of random convex shapes (circles/ellipses, rectangles, hexagons) with
random rotations and aspect ratios, extruded through depth. Built on the user's
Shape Generator. Each shape is filled with crystalline Au atoms (so it diffracts)
OR amorphous atoms, selectable. Designed as a testbed for "find and characterize
isolated features" workflows.

Shapes are distributed THROUGH THE SLAB, not pinned to its mid-plane. That is the
whole point of this sample now: with the server projecting depth-slice by
depth-slice (project_with_dof), features at different heights are in focus by
different amounts in the SAME frame, and walking stage z walks the in-focus plane
through the specimen. Nothing about that is sample-specific -- it is the server's
projection reading the z axis every sample already fills in -- but this sample is
the one built to show it.
"""
import numpy as np
from .base import Sample, SampleMetadata, atoms_in_particles
from . import register


def generate_shapes_array(height=600, width=800, num_shapes=200, min_size=8,
                          max_size=45, aspect_min=0.6, aspect_max=1.8, seed=None,
                          background_value=0.0, shape_intensity=1.0,
                          enable_rotation=True, non_overlapping=False,
                          shape_types=None, depth=0.0, _return_placed=False):
    """Adapted from the user's Shape Generator. Returns the 2D array, and
    optionally the list of placed shapes (cy, cx, cz, size, type, aspect, angle).

    `depth` is the full z range (in the caller's units) over which shape CENTRES
    are scattered; cz is drawn uniformly in +/- depth/2 and is 0.0 when depth is
    0, which reproduces the flat, single-plane behaviour exactly.

    Overlap rejection is done in 3-D when depth > 0: two shapes at the same (y, x)
    but opposite ends of the slab are not overlapping, they are stacked, and on a
    real specimen that is a perfectly ordinary thing for them to be.
    """
    if seed is not None:
        np.random.seed(seed)
    if shape_types is None:
        shape_types = ['circle', 'rect', 'hex']
    array = np.full((height, width), background_value, dtype=float)
    placed = []
    half_depth = 0.5 * max(float(depth), 0.0)
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
        cz = np.random.uniform(-half_depth, half_depth) if half_depth > 0 else 0.0
        if non_overlapping:
            overlaps = False
            for py, px, pz, psize, _, _, _ in placed:
                if np.sqrt((cy-py)**2 + (cx-px)**2 + (cz-pz)**2) < (psize+size)*0.95:
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
        placed.append((cy, cx, cz, size, shape_type, aspect, angle))
        successful += 1
    if _return_placed:
        return array, placed
    return array


_LAM_CACHE = {}     # calibrated Poisson means, keyed by generator parameters


def generate_shapes_in_world(x0, y0, W, H, num_shapes=40, min_size=8, max_size=28,
                             aspect_min=0.6, aspect_max=1.8, seed=42,
                             shape_types=None, depth=0.0, non_overlapping=True,
                             enable_rotation=True, _lam_override=None,
                             _calibrate=True):
    """Cell-hashed world generator, adapted from the reference Shape Generator.

    Returns the shapes whose centres fall in the world rectangle
    [x0, x0+W) x [y0, y0+H), each as (cy, cx, cz, size, stype, aspect, angle) in
    WORLD pixel coordinates.

    Why cell hashing instead of the previous rejection sampler
    ---------------------------------------------------------
    The old generator seeded once and scattered `num_shapes` into a fixed (H, W)
    grid. That makes the specimen a finite picture: drift had to be clamped at the
    edge or it would walk into vacuum, and the same world position produced
    different shapes depending on which window you asked for.

    Here the world is partitioned into square cells and each cell's RNG is derived
    from `hash(seed, cell_y, cell_x)`. A cell therefore contains the same shapes no
    matter who asks, when, or what window they asked for. Two consequences:

    * the specimen is UNBOUNDED -- drift reveals genuinely new material, and
      driving back reveals what you left, because it was never stored;
    * generation is LOCAL -- rendering a window costs work proportional to the
      window, not to the world.

    `num_shapes` is retained as the knob (it is what every caller and demo passes)
    and converted internally to the per-cell Poisson mean that reproduces that
    count over one W x H window. So `num_shapes=40` still means "about 40 shapes in
    a field this size", now at any position in an endless specimen.
    """
    if shape_types is None:
        shape_types = ['circle', 'rect', 'hex']
    cell = max(int(max_size * 3), 40)
    half_depth = 0.5 * max(float(depth), 0.0)

    # Poisson mean per cell. The naive value, num_shapes / cells-per-window, is
    # what you would want if every candidate survived -- but overlap rejection
    # removes roughly half at typical densities, so it lands ~2x short. (The old
    # rejection sampler hid this by retrying until it had placed num_shapes; a
    # position-hashed generator cannot retry, because the count in a cell has to
    # depend only on that cell.)
    #
    # So `lam` is calibrated once against a REFERENCE window at world origin,
    # never against the caller's window -- otherwise density would vary with
    # where you happened to be looking, which is exactly the property cell
    # hashing exists to guarantee.
    n_cells = max(1.0, (float(W) / cell) * (float(H) / cell))
    lam = max(0.0, float(num_shapes) / n_cells)
    if lam > 0 and non_overlapping and _calibrate:
        key = (int(seed), int(num_shapes), int(min_size), int(max_size), int(W), int(H),
               round(float(aspect_min), 4), round(float(aspect_max), 4),
               round(float(depth), 4), tuple(shape_types))
        cached = _LAM_CACHE.get(key)
        if cached is None:
            for _ in range(6):
                probe = generate_shapes_in_world(
                    0.0, 0.0, W, H, num_shapes=num_shapes, min_size=min_size,
                    max_size=max_size, aspect_min=aspect_min, aspect_max=aspect_max,
                    seed=seed, shape_types=shape_types, depth=depth,
                    non_overlapping=True, enable_rotation=enable_rotation,
                    _lam_override=lam, _calibrate=False)
                got = sum(1 for s in probe if 0 <= s[0] < H and 0 <= s[1] < W)
                if got <= 0:
                    lam *= 2.0
                    continue
                if abs(got - num_shapes) <= max(1, 0.05 * num_shapes):
                    break
                # damped so the fixed point does not oscillate at high density
                lam *= (1.0 + 0.7 * (float(num_shapes) / got - 1.0))
                lam = float(np.clip(lam, 1e-4, 40.0))
            _LAM_CACHE[key] = lam
        else:
            lam = cached
    if _lam_override is not None:
        lam = float(_lam_override)

    pad = max_size + 2                      # a shape centred just outside can still
    cy0 = int(np.floor((y0 - pad) / cell))   # overlap the window, so widen the scan
    cy1 = int(np.floor((y0 + H + pad) / cell))
    cx0 = int(np.floor((x0 - pad) / cell))
    cx1 = int(np.floor((x0 + W + pad) / cell))

    out = []
    for gy in range(cy0, cy1 + 1):
        for gx in range(cx0, cx1 + 1):
            # Deterministic per-cell seed. The large odd multipliers are the usual
            # spatial-hash primes; XOR mixes the axes without correlating them.
            cs = ((int(seed) * 73856093) ^ (gy * 19349663) ^ (gx * 83492791)) & 0xFFFFFFFF
            rng = np.random.RandomState(cs)
            # Cap guards against a pathological draw, but must scale with lam or
            # it becomes the binding constraint at high density -- which silently
            # flattened num_shapes=40 and num_shapes=120 onto the same count.
            n = int(min(rng.poisson(lam), max(8, int(4 * lam)))) if lam > 0 else 0
            for _ in range(n):
                size   = int(rng.randint(min_size, max_size + 1))
                aspect = float(rng.uniform(aspect_min, aspect_max))
                angle  = float(rng.uniform(0, 2 * np.pi)) if enable_rotation else 0.0
                stype  = str(rng.choice(shape_types))
                wy = gy * cell + float(rng.uniform(0, cell))
                wx = gx * cell + float(rng.uniform(0, cell))
                cz = float(rng.uniform(-half_depth, half_depth)) if half_depth > 0 else 0.0
                out.append((wy, wx, cz, size, stype, aspect, angle))

    if non_overlapping:
        # Rejection is order-dependent, so sort into a canonical world order first:
        # otherwise which shape survives would depend on the window you asked for,
        # and the specimen would change as you drove around it. 3-D, because two
        # shapes at the same (y, x) but opposite ends of the slab are stacked, not
        # overlapping.
        out.sort(key=lambda s: (s[0], s[1]))
        kept = []
        for s in out:
            if all(np.sqrt((s[0]-k[0])**2 + (s[1]-k[1])**2 + (s[2]-k[2])**2)
                   >= (s[3] + k[3]) * 0.92 for k in kept):
                kept.append(s)
        out = kept

    # Cells are scanned in whole units, so the scan reaches up to one cell beyond
    # the padded window and can return shapes that cannot touch it at all. Drop
    # them: they would otherwise be deposited nowhere but still be recorded as
    # particles, inflating the atom/diffraction path with specimen that is not in
    # the field. Rejection ran BEFORE this filter, so a dropped neighbour still
    # excluded its overlaps -- the surviving set does not depend on the window.
    return [s for s in out
            if (y0 - s[3]) <= s[0] <= (y0 + H + s[3])
            and (x0 - s[3]) <= s[1] <= (x0 + W + s[3])]


@register
class ShapeAssembly(Sample):
    feature_scale_nm = 30.0   # smallest shape feature (~30 nm)
    meta = SampleMetadata(
        name="shape_assembly",
        display_name="Shape Assembly (synthetic features)",
        description="Random rotated convex shapes distributed through a slab; testbed for feature-finding and depth-of-field workflows.",
        default_params={
            "num_shapes": 40,
            "min_size": 8,
            "max_size": 28,
            "aspect_min": 0.6,
            "aspect_max": 1.8,
            "seed": 42,
            "non_overlapping": True,
            "crystalline": True,        # True -> shapes diffract as crystals; False -> amorphous
            "depth_fraction": 0.5,      # fraction of D each shape spans (unchanged)
            # Fraction of the available slab depth over which feature CENTRES are
            # distributed. 1.0 spreads them through the foil, as for particles in
            # a matrix; 0.0 puts every feature on the mid-plane, as for a
            # drop-cast monolayer on a support. Bounded by each feature's own
            # half-height (see _build) so nothing is clipped by the volume.
            "z_spread": 1.0,
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
            "depth_fraction": {"type": "float", "min": 0.02, "max": 1.0},
            "z_spread":       {"type": "float", "min": 0.0,  "max": 1.0},
            "base_level":     {"type": "float", "min": 0,    "max": 1000},
            "shape_intensity":{"type": "float", "min": 100,  "max": 60000},
            "sigma_px":       {"type": "float", "min": 0.5,  "max": 4.0},
        },
    )

    # World-hashed generation means any patch can be produced on demand, so this
    # sample uses the stronger of the two roaming modes: the server re-tiles and
    # the specimen NEVER repeats. Every other sample falls back to "periodic",
    # which wraps the sampler over one generated tile.
    supports_roaming = True
    roaming_mode = "world"

    def generate_volume_at(self, D, H, W, origin_x_px=0.0, origin_y_px=0.0):
        return self._build(D, H, W, float(origin_x_px), float(origin_y_px))

    @property
    def crystalline_particles(self):
        return bool(self.params.get("crystalline", True))

    particles_random_orientation = True

    def generate_volume(self, D, H, W):
        return self._build(D, H, W, 0.0, 0.0)

    def _build(self, D, H, W, ox, oy):
        p = self.params
        self._vol_shape = (D, H, W)

        # Each shape spans +/- rz voxels in z (depth_fraction, unchanged meaning),
        # so centres may only wander over the depth that is LEFT once a shape's
        # own half-height is accounted for. That guarantees no shape is clipped by
        # the top or bottom of the volume however the two knobs are set, and
        # z_spread is a specimen property, not a microscope setting: it says how
        # much of the foil's depth the features actually occupy. 1.0 = distributed
        # through the thickness (particles in a matrix); 0.0 = all on one plane
        # (a drop-cast monolayer on a support). The bound below is derived from
        # each shape's own half-height, so no shape can be clipped by the top or
        # bottom of the volume however the two knobs are set.
        rz = max(1, int(round(float(p["depth_fraction"]) * D / 2)))
        z_room = max(0.0, (D / 2.0) - rz)
        z_range = 2.0 * float(np.clip(p.get("z_spread", 1.0), 0.0, 1.0)) * z_room

        world = generate_shapes_in_world(
            ox, oy, W, H, num_shapes=int(p["num_shapes"]),
            min_size=int(p["min_size"]), max_size=int(p["max_size"]),
            aspect_min=float(p["aspect_min"]), aspect_max=float(p["aspect_max"]),
            seed=int(p["seed"]), shape_types=['circle','rect','hex'],
            depth=z_range, non_overlapping=bool(p["non_overlapping"]),
            enable_rotation=True)
        # world -> local pixel coordinates for this patch
        placed = [(wy - oy, wx - ox, cz, size, stype, aspect, angle)
                  for (wy, wx, cz, size, stype, aspect, angle) in world]

        # Record each shape as a particle for the unified atom diffraction path.
        # Treat shape 'size' as the in-plane radius; z-extent = depth_fraction*D/2.
        # center_vox now carries the shape's OWN z, so the atom path (DIFF mode,
        # the abTEM bridge) and the imaging path describe the same specimen.
        zc = D // 2
        # Full shape descriptors (type, aspect, angle) -- _particles keeps only
        # centre + radii, which is all the atom path needs but not enough to
        # rebuild a hexagon. Appendix E's analytic projector reads this.
        self._shape_records = [(cy, cx, zc + cz, size, stype, aspect, angle)
                               for (cy, cx, cz, size, stype, aspect, angle) in placed]
        self._particles = []
        for (cy, cx, cz, size, stype, aspect, angle) in placed:
            ry = int(round(size))
            rx = int(round(size * aspect))
            self._particles.append({"center_vox": (zc + cz, int(cy), int(cx)),
                                    "radii_vox": (rz, ry, rx)})

        # Build the 3D volume. Shapes at different depths must land on different
        # slices, so shapes are grouped by their (integer) centre slice, each
        # group's 2-D footprint is accumulated once, and the D x G group-profile
        # matrix is contracted against the G x (H*W) footprints in one matmul.
        # That costs G resamples' worth of work instead of one per shape, and
        # keeps the flat case (G == 1) identical to the old single-profile loop.
        V = np.zeros((D, H, W), dtype=np.float32) + float(p["base_level"])
        groups = {}
        for (cy, cx, cz, size, stype, aspect, angle) in placed:
            k = int(round(zc + cz))
            groups.setdefault(k, []).append((cy, cx, size, stype, aspect, angle))

        if groups:
            keys = sorted(groups)
            foot = np.zeros((len(keys), H, W), dtype=np.float32)
            y, x = np.ogrid[:H, :W]
            for gi, k in enumerate(keys):
                for (cy, cx, size, stype, aspect, angle) in groups[k]:
                    dy = y - cy; dx = x - cx
                    ca, sa = np.cos(angle), np.sin(angle)
                    dx_rot = dx*ca - dy*sa; dy_rot = dx*sa + dy*ca
                    if stype == 'circle':
                        mask = ((dx_rot/aspect)**2 + dy_rot**2) <= size**2
                    elif stype == 'rect':
                        mask = (np.abs(dx_rot) <= size*aspect) & (np.abs(dy_rot) <= size)
                    else:
                        dx_h = dx_rot/aspect; dy_h = dy_rot; s = size
                        mask = ((np.abs(dx_h) <= s) & (np.abs(dy_h) <= s*0.866) &
                                (np.abs(dx_h*0.5 + dy_h*0.866) <= s) &
                                (np.abs(dx_h*0.5 - dy_h*0.866) <= s))
                    foot[gi][mask] += 1.0
            zz = np.arange(D, dtype=np.float32)[:, None]
            prof = np.exp(-((zz - np.array(keys, dtype=np.float32)[None, :]) / max(1, rz))**2)
            prof[prof <= 0.02] = 0.0
            V += float(p["shape_intensity"]) * (
                prof @ foot.reshape(len(keys), -1)).reshape(D, H, W)

        def gfreq(n, s):
            f = np.fft.fftfreq(n).astype(np.float32)
            return np.exp(-2.0*(np.pi**2)*(s**2)*(f**2)).astype(np.float32)
        s = float(p["sigma_px"])
        F = np.fft.fftn(V)
        F *= gfreq(D,s)[:,None,None]; F *= gfreq(H,s)[None,:,None]; F *= gfreq(W,s)[None,None,:]
        V = np.clip(np.fft.ifftn(F).real, 0, 65535).astype(np.float32)
        return V
