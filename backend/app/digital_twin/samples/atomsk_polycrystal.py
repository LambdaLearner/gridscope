"""
samples/atomsk_polycrystal.py

Loads atomistic structure files (typically from Atomsk's `--polycrystal` mode)
and rasterizes them into the digital-twin's voxel volume.

Supported input formats (via ASE if installed; falls back to a built-in XYZ
reader otherwise):
  - XYZ                (.xyz)         — universal, no dependencies needed
  - LAMMPS data        (.lmp, .data)  — Atomsk's default polycrystal output
  - CFG                (.cfg)         — common Atomsk output
  - CIF                (.cif)         — crystallographic info file
  - VASP POSCAR        (POSCAR/.vasp) — VASP structure file
  - XSF                (.xsf)         — XCrySDen

Atomsk example to produce a usable file:
    atomsk --create fcc 4.05 Au seed.cfg
    atomsk --polycrystal seed.cfg poly.txt poly.lmp xyz cfg
                                              ^      ^
                                              also writes poly.xyz, poly.cfg

Default file path: 'sample_data/polycrystal.xyz' (override with file_path param).

A note on units:
  Atomsk works in Angstroms. The voxel grid is whatever physical scale you set
  via `sample_fov_um`. The `scale_factor` parameter controls how atomistic
  coordinates map to voxels; the default tries to fit the whole structure
  into the volume. Use `auto_fit=True` to ignore scale_factor and just stretch
  the bounding box to fill the volume.
"""
import os
import numpy as np
from .base import Sample, SampleMetadata
from . import register


# ---------------------------------------------------------------------------
# File reading: prefer ASE for breadth, fall back to a built-in XYZ reader.
# ---------------------------------------------------------------------------
def _read_xyz_fallback(path):
    """Minimal extended-XYZ reader. Returns (positions_A, symbols)."""
    with open(path, "r") as f:
        lines = [ln.rstrip("\n") for ln in f]
    if not lines:
        raise ValueError(f"Empty file: {path}")
    try:
        n_atoms = int(lines[0].strip())
    except ValueError:
        raise ValueError(
            f"Could not parse atom count from first line of {path!r} "
            "(not an XYZ file?)"
        )
    if len(lines) < n_atoms + 2:
        raise ValueError(
            f"File claims {n_atoms} atoms but only has {len(lines) - 2} data lines"
        )
    positions = np.zeros((n_atoms, 3), dtype=np.float32)
    symbols = []
    for i in range(n_atoms):
        parts = lines[2 + i].split()
        if len(parts) < 4:
            raise ValueError(
                f"Line {3+i} of {path!r} has fewer than 4 columns: {parts!r}"
            )
        symbols.append(parts[0])
        positions[i] = [float(parts[1]), float(parts[2]), float(parts[3])]
    return positions, symbols


def _read_structure_file(path):
    """
    Returns (positions_A: (N,3) float32, symbols: list[str]).
    Tries ASE first; falls back to XYZ-only if ASE isn't available.
    """
    ext = os.path.splitext(path)[1].lower()
    try:
        from ase.io import read as ase_read
    except ImportError:
        if ext != ".xyz":
            raise ImportError(
                f"Reading '{ext}' files requires the `ase` package. "
                "Install with: pip install ase. "
                "Alternatively, convert your file to .xyz format (e.g. with "
                "Atomsk: atomsk input.lmp output.xyz)."
            )
        positions, symbols = _read_xyz_fallback(path)
        return positions, symbols

    # ASE format hints for files Atomsk commonly emits
    fmt_hint = None
    if ext in (".lmp", ".data"):
        fmt_hint = "lammps-data"
    elif ext == ".cfg":
        fmt_hint = "cfg"
    elif ext == ".cif":
        fmt_hint = "cif"
    elif ext == ".xsf":
        fmt_hint = "xsf"

    try:
        if fmt_hint:
            atoms = ase_read(path, format=fmt_hint)
        else:
            atoms = ase_read(path)
    except Exception as e:
        raise ValueError(
            f"ASE could not parse {path!r}: {e}. "
            "If it's an Atomsk file, try converting to XYZ first: "
            "`atomsk infile outfile.xyz`."
        )

    positions = np.asarray(atoms.get_positions(), dtype=np.float32)
    symbols = list(atoms.get_chemical_symbols())
    return positions, symbols


# ---------------------------------------------------------------------------
# Atomic-number proxy → Z-contrast intensity. Real STEM HAADF roughly ∝ Z^1.7,
# but we use a small lookup so unknown elements still get a sane value.
# ---------------------------------------------------------------------------
_Z_TABLE = {
    "H": 1,  "C": 6,  "N": 7,  "O": 8,
    "Na": 11, "Mg": 12, "Al": 13, "Si": 14,
    "Ti": 22, "V": 23, "Cr": 24, "Mn": 25, "Fe": 26, "Co": 27, "Ni": 28,
    "Cu": 29, "Zn": 30,
    "Mo": 42, "Ag": 47, "W": 74, "Pt": 78, "Au": 79, "Pb": 82,
}


def _intensity_from_symbol(sym):
    z = _Z_TABLE.get(sym, 14)  # default ~ Si
    return float(z) ** 1.7


# ---------------------------------------------------------------------------
@register
class AtomskPolycrystal(Sample):
    meta = SampleMetadata(
        name="atomsk_polycrystal",
        display_name="Atomsk Polycrystal (file-driven)",
        description=("Loads an atomistic structure file (xyz, lmp, cfg, cif, xsf) "
                     "and rasterizes it. Designed for Atomsk --polycrystal output."),
        default_params={
            # Path to the structure file. Relative paths are resolved against cwd.
            "file_path": "sample_data/polycrystal.xyz",
            # If True, auto-scale the structure's bounding box to fill the volume
            # in XY. Z gets centered with no stretching beyond what fits.
            "auto_fit": True,
            # Manual scaling: voxels per Angstrom (only used if auto_fit=False).
            "scale_factor": 0.1,
            # Gaussian sigma used to splat each atom (voxels). Larger = blurrier.
            "atom_sigma_px": 0.9,
            # Cap how many atoms to render (random subsample if exceeded).
            # Keeps generation time bounded for huge polycrystals.
            "max_atoms": 200000,
            "seed": 42,
            "base_level": 60.0,
            "intensity_scale": 30.0,   # multiplies the Z^1.7 contribution
        },
        param_schema={
            "file_path":        {"type": "str"},
            "auto_fit":         {"type": "bool"},
            "scale_factor":     {"type": "float", "min": 1e-4, "max": 100.0},
            "atom_sigma_px":    {"type": "float", "min": 0.2,  "max": 8.0},
            "max_atoms":        {"type": "int",   "min": 100,  "max": 5_000_000},
            "seed":             {"type": "int",   "min": 0,    "max": 2**31-1},
            "base_level":       {"type": "float", "min": 0,    "max": 10000},
            "intensity_scale":  {"type": "float", "min": 0,    "max": 10000},
        },
    )

    # Polycrystals are atomistic — much smaller real extent than µm samples.
    # Override the physical mapping so a single Atomsk structure spans the
    # active FOV nicely. Users can still rescale via load_sample(...) params.
    tilt_strength_px_per_slice = 0.35

    def generate_volume(self, D, H, W):
        p = self.params
        path = str(p["file_path"])
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"Atomsk file not found: {path!r}. "
                "Upload it to the Colab session or set `file_path` to its actual location. "
                "See the notebook's 'How to provide a polycrystal file' section."
            )

        positions, symbols = _read_structure_file(path)
        n_total = len(positions)
        if n_total == 0:
            raise ValueError(f"File {path!r} contained zero atoms.")

        # Subsample if too big
        rng = np.random.default_rng(int(p["seed"]))
        max_n = int(p["max_atoms"])
        if n_total > max_n:
            idx = rng.choice(n_total, size=max_n, replace=False)
            positions = positions[idx]
            symbols = [symbols[i] for i in idx]
            n_used = max_n
        else:
            n_used = n_total

        # Compute element intensities
        intensities = np.array([_intensity_from_symbol(s) for s in symbols],
                               dtype=np.float32)
        intensities *= float(p["intensity_scale"])

        # ---- Map atom coordinates (Angstroms) → voxel coordinates ----
        pmin = positions.min(axis=0)
        pmax = positions.max(axis=0)
        extent_A = np.maximum(pmax - pmin, 1e-6)

        if bool(p["auto_fit"]):
            # TRUE-SCALE mapping (not stretch-to-fill). 1 voxel = generation range
            # per W pixels, so atoms sit at their real physical size and the loaded
            # structure occupies the correct fraction of the field -- consistent
            # with get_atoms_in_region (which uses true Angstrom positions). A tiny
            # cell will therefore look small (as it physically is); scale it up in
            # Atomsk if you want it to fill more of the field.
            #   voxels per Angstrom = (W / generation_range_um) / 1e4
            vox_per_A = (W / float(self.generation_range_um)) / 1.0e4
            scales = np.array([vox_per_A, vox_per_A, vox_per_A], dtype=np.float32)
            # if the structure is far larger than the volume, fall back to a fit so
            # it is at least visible (with a warning-friendly comment)
            if (extent_A[0] * vox_per_A > W) or (extent_A[1] * vox_per_A > H):
                margin = 0.92
                sxy = min((W * margin) / extent_A[0], (H * margin) / extent_A[1])
                sz = min(sxy, (D * margin) / max(extent_A[2], 1e-6))
                scales = np.array([sxy, sxy, sz], dtype=np.float32)
        else:
            s = float(p["scale_factor"])
            scales = np.array([s, s, s], dtype=np.float32)

        # Center the mapped structure inside the volume
        centered = (positions - (pmin + pmax) * 0.5) * scales
        # voxel coords: (x, y, z) -> indices in (z, y, x)
        xv = centered[:, 0] + 0.5 * W
        yv = centered[:, 1] + 0.5 * H
        zv = centered[:, 2] + 0.5 * D

        # ---- Splat each atom as a small 3D Gaussian ----
        V = np.full((D, H, W), float(p["base_level"]), dtype=np.float32)
        sigma = float(p["atom_sigma_px"])
        rad = max(1, int(np.ceil(3.0 * sigma)))  # truncate Gaussian at 3σ
        two_sig_sq = 2.0 * sigma * sigma

        # Precompute the 1D Gaussian kernel for axis-separable splatting
        offsets = np.arange(-rad, rad + 1, dtype=np.float32)
        gauss_1d = np.exp(-(offsets * offsets) / two_sig_sq).astype(np.float32)
        # Outer-product 3D kernel (small, since rad is small)
        k3d = (gauss_1d[:, None, None]
               * gauss_1d[None, :, None]
               * gauss_1d[None, None, :])

        # Iterate (works fine up to a few hundred thousand atoms)
        skipped = 0
        for i in range(n_used):
            ix = int(round(xv[i])); iy = int(round(yv[i])); iz = int(round(zv[i]))
            if not (0 <= ix < W and 0 <= iy < H and 0 <= iz < D):
                skipped += 1
                continue

            z0 = max(0, iz - rad); z1 = min(D, iz + rad + 1)
            y0 = max(0, iy - rad); y1 = min(H, iy + rad + 1)
            x0 = max(0, ix - rad); x1 = min(W, ix + rad + 1)

            kz0 = z0 - (iz - rad); kz1 = k3d.shape[0] - ((iz + rad + 1) - z1)
            ky0 = y0 - (iy - rad); ky1 = k3d.shape[1] - ((iy + rad + 1) - y1)
            kx0 = x0 - (ix - rad); kx1 = k3d.shape[2] - ((ix + rad + 1) - x1)

            V[z0:z1, y0:y1, x0:x1] += (
                intensities[i] * k3d[kz0:kz1, ky0:ky1, kx0:kx1]
            )

        if skipped > 0:
            print(f"[atomsk] {skipped}/{n_used} atoms fell outside the volume "
                  "(consider lowering scale_factor or enabling auto_fit).")

        # Store atom positions in microns relative to the centered sample, plus
        # atomic numbers, for local-region diffraction. centered[] is in
        # Angstroms; convert to microns for stage-frame coordinate matching.
        # Map symbol -> atomic number for diffraction form factors.
        _Z_TABLE = {"H":1,"He":2,"Li":3,"Be":4,"B":5,"C":6,"N":7,"O":8,"F":9,"Ne":10,
                    "Na":11,"Mg":12,"Al":13,"Si":14,"P":15,"S":16,"Cl":17,"Ar":18,
                    "K":19,"Ca":20,"Ti":22,"V":23,"Cr":24,"Mn":25,"Fe":26,"Co":27,
                    "Ni":28,"Cu":29,"Zn":30,"Ga":31,"Ge":32,"As":33,"Se":34,
                    "Mo":42,"Pd":46,"Ag":47,"Cd":48,"In":49,"Sn":50,"Sb":51,
                    "W":74,"Pt":78,"Au":79,"Pb":82,"U":92}
        Zs = np.array([_Z_TABLE.get(s, 6) for s in symbols], dtype=np.int32)
        # Centered positions are still in Angstroms (before voxel scaling). Use
        # those directly so diffraction sees real interatomic spacings.
        self._atoms_A = (positions - (pmin + pmax) * 0.5).astype(np.float64)
        self._atoms_Z = Zs
        # Sample extent (sample_fov_um) for stage-frame conversion
        # 1 voxel = (extent / volume_size); the sample occupies the volume center
        self._extent_A = extent_A
        self._n_atoms = n_used
        print(f"[atomsk] retained {n_used} atom positions for local diffraction")

        return np.clip(V, 0, 65535).astype(np.float32)

    def get_atoms_in_region(self, cx_um, cy_um, half_width_um, depth_nm):
        """Return atoms inside an aperture-sized region centered at the stage
        position. Atoms are returned in Angstroms relative to the region center."""
        if not hasattr(self, "_atoms_A") or self._atoms_A is None:
            return None, None
        # Convert stage-frame microns to atom-frame Angstroms
        cx_A = cx_um * 1e4
        cy_A = cy_um * 1e4
        half_A = half_width_um * 1e4
        depth_A = depth_nm * 10.0
        # The atom positions are centered on the sample, so the box in atom
        # coords is centered at (cx_A, cy_A, 0) with half-widths (half_A, half_A, depth_A/2)
        pos = self._atoms_A
        mask = ((np.abs(pos[:, 0] - cx_A) <= half_A) &
                (np.abs(pos[:, 1] - cy_A) <= half_A) &
                (np.abs(pos[:, 2]) <= depth_A / 2))
        kept = pos[mask].copy()
        kept[:, 0] -= cx_A
        kept[:, 1] -= cy_A
        # If too many, subsample
        if len(kept) > 100000:
            rng = np.random.default_rng(0)
            idx = rng.choice(len(kept), 100000, replace=False)
            kept = kept[idx]
            Zs = self._atoms_Z[mask][idx]
        else:
            Zs = self._atoms_Z[mask]
        return kept, Zs
