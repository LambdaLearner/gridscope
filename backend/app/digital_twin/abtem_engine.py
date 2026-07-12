"""
abtem_engine.py — high-fidelity (dynamical, multislice) diffraction engine.

This is the *high-fidelity path* of the two-path design: the twin's built-in
kinematical engine stays the fast, interactive default (correct spot positions,
~seconds/frame, no heavy deps); this module computes *dynamical* diffraction
with abTEM multislice — correct spot intensities, thickness effects, and (with
frozen phonons) the thermal-diffuse background — so simulated patterns can be
analysed by external tools (py4DSTEM, strain/orientation mappers) as if they
were real data.

It ingests atoms from ANY twin sample through the shared
`get_atoms_in_region(cx_um, cy_um, half_width_um, depth_nm) -> (positions_A, Z)`
interface, or builds common crystals directly with ASE.

The abTEM/ASE dependencies are OPTIONAL: this module imports without them and
reports availability via `abtem_available()`. Constructing `AbtemDiffraction`
without them raises ImportError (the HTTP layer maps that to 501). The engine
is simulation-side only — it never appears on the portable control surface.
"""
from __future__ import annotations

import numpy as np

try:  # optional heavy dependencies
    import abtem
    from ase import Atoms
    from ase.build import bulk

    _ABTEM_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover — exercised via abtem_available()
    abtem = None
    Atoms = None
    bulk = None
    _ABTEM_IMPORT_ERROR = exc

ABTEM_MISSING_MSG = (
    "The dynamical-diffraction engine requires `abtem` and `ase` "
    "(`pip install abtem ase`)."
)


def abtem_available() -> bool:
    """True when the optional abtem/ase dependencies are importable."""
    return _ABTEM_IMPORT_ERROR is None


class AbtemDiffraction:
    """Dynamical diffraction engine built on abTEM multislice.

    Parameters
    ----------
    energy_kev : float
        Accelerating voltage in kV (default 200).
    potential_sampling : float
        Real-space sampling of the projected potential, in Angstrom (default 0.08).
        Smaller = finer reciprocal-space coverage but slower.
    slice_thickness : float
        Multislice slice thickness in Angstrom (default 2.0).
    parametrization : str
        Scattering-factor parametrization for abTEM (default "lobato").
    device : str or None
        "cpu" (default) or "gpu" (needs CuPy). None uses the abTEM default.
    """

    def __init__(self, energy_kev: float = 200.0, potential_sampling: float = 0.08,
                 slice_thickness: float = 2.0, parametrization: str = "lobato",
                 device: str | None = "cpu"):
        if not abtem_available():
            raise ImportError(ABTEM_MISSING_MSG) from _ABTEM_IMPORT_ERROR
        self.energy_ev = float(energy_kev) * 1e3
        self.sampling = float(potential_sampling)
        self.slice_thickness = float(slice_thickness)
        self.parametrization = parametrization
        self.device = device

    # ------------------------------------------------------------------ #
    # Structure building / ingestion
    # ------------------------------------------------------------------ #
    @staticmethod
    def build_crystal(element: str, structure: str, a: float,
                      size: tuple = (6, 6, 20), c: float | None = None):
        """Build a periodic crystal supercell with ASE (best diffraction quality,
        because the cell is inherently periodic).

        element : chemical symbol, e.g. "Au".
        structure : ASE structure, e.g. "fcc", "bcc", "hcp", "diamond", "sc".
        a : lattice constant in Angstrom (c optional for hcp).
        size : (nx, ny, nz) repetitions. nz sets the specimen thickness.
        """
        kw = dict(name=element, crystalstructure=structure, a=float(a), cubic=True)
        if c is not None:
            kw["c"] = float(c)
            kw.pop("cubic", None)   # hcp/tetragonal aren't 'cubic'
        try:
            cell = bulk(**kw)
        except Exception:
            kw.pop("cubic", None)
            cell = bulk(**kw)
        return cell * tuple(int(s) for s in size)

    def atoms_from_twin_sample(self, sample, half_width_um: float = 0.02,
                               depth_nm: float = 12.0, cx_um: float = 0.0,
                               cy_um: float = 0.0, generate_volume: bool = True,
                               vol_shape: tuple = (40, 256, 256),
                               max_lateral_A: float | None = 60.0,
                               max_thickness_A: float | None = 120.0):
        """Pull atoms from a twin sample via its `get_atoms_in_region` interface and
        wrap them as an ASE `Atoms` with a periodic bounding box.

        Note: a bounding box around an arbitrary chunk of a crystal is not perfectly
        periodic at its faces, which can add weak artifacts. For a *clean* crystal
        pattern prefer `build_crystal`; use this when you specifically want the
        diffraction of the twin's actual modeled object (a defect, a grain, an
        Atomsk cell). Larger regions reduce the relative edge effect.

        Performance: the twin sizes its regions for its own (fast) kinematical
        engine and can return ~100k atoms in a ~110 A cube — multislice on that is
        slow (tens of seconds). `max_lateral_A` and `max_thickness_A` crop the
        returned atoms to a tractable box centred on the region (set either to None
        to disable). Cropping keeps the crystal periodicity essentially intact for a
        single crystal and makes runtime comparable to `build_crystal`.
        """
        if generate_volume and hasattr(sample, "generate_volume"):
            try:
                sample.generate_volume(*vol_shape)
            except Exception:
                pass
        positions_A, Z = sample.get_atoms_in_region(cx_um, cy_um, half_width_um, depth_nm)
        positions_A = np.asarray(positions_A, dtype=float)
        Z = np.asarray(Z, dtype=int)
        if positions_A.size == 0:
            raise ValueError("sample.get_atoms_in_region returned no atoms.")

        # Optionally crop to a tractable box centred on the atom cloud.
        centre = 0.5 * (positions_A.max(axis=0) + positions_A.min(axis=0))
        keep = np.ones(len(positions_A), dtype=bool)
        if max_lateral_A is not None:
            half = float(max_lateral_A) / 2.0
            keep &= np.abs(positions_A[:, 0] - centre[0]) <= half
            keep &= np.abs(positions_A[:, 1] - centre[1]) <= half
        if max_thickness_A is not None:
            halfz = float(max_thickness_A) / 2.0
            keep &= np.abs(positions_A[:, 2] - centre[2]) <= halfz
        positions_A = positions_A[keep]
        Z = Z[keep]
        if positions_A.size == 0:
            raise ValueError("cropping removed all atoms; increase max_lateral_A/max_thickness_A.")

        origin = positions_A.min(axis=0)
        positions_A = positions_A - origin
        extent = positions_A.max(axis=0)
        extent = np.where(extent > 1e-6, extent, 1.0) + 0.5
        return Atoms(numbers=Z, positions=positions_A, cell=extent.tolist(), pbc=True)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _potential(self, atoms):
        return abtem.Potential(atoms, sampling=self.sampling,
                               slice_thickness=self.slice_thickness,
                               projection="infinite",
                               parametrization=self.parametrization,
                               device=self.device)

    def _potential_frozen(self, atoms, num_configs, sigmas):
        fp = abtem.FrozenPhonons(atoms, num_configs=int(num_configs),
                                 sigmas=float(sigmas), seed=1)
        return abtem.Potential(fp, sampling=self.sampling,
                               slice_thickness=self.slice_thickness,
                               projection="infinite",
                               parametrization=self.parametrization,
                               device=self.device)

    # ------------------------------------------------------------------ #
    # Diffraction modes
    # ------------------------------------------------------------------ #
    def saed(self, atoms, tilt_mrad: tuple = (0.0, 0.0), num_frozen_phonons: int = 0,
             sigmas: float = 0.1, max_angle_mrad: float = 60.0) -> np.ndarray:
        """Selected-area (plane-wave) diffraction pattern -> sharp spots.

        tilt_mrad : small beam tilt (mrad) for fine zone-axis alignment. For large
            zone-axis changes, rotate `atoms` instead (see `tilted_atoms`).
        num_frozen_phonons : 0 = single static config (fast). >0 averages that many
            frozen-phonon configurations to include thermal-diffuse scattering.
        Returns a 2D intensity array (the full pattern, direct beam included).
        """
        wave = abtem.PlaneWave(energy=self.energy_ev, sampling=self.sampling,
                               tilt=tuple(tilt_mrad), device=self.device)
        if num_frozen_phonons and num_frozen_phonons > 0:
            pot = self._potential_frozen(atoms, num_frozen_phonons, sigmas)
            dp = (wave.multislice(pot)
                      .diffraction_patterns(max_angle=max_angle_mrad)
                      .mean(0).compute())
        else:
            pot = self._potential(atoms)
            dp = (wave.multislice(pot)
                      .diffraction_patterns(max_angle=max_angle_mrad)
                      .compute())
        return np.asarray(dp.array, dtype=np.float32)

    def cbed(self, atoms, convergence_mrad: float = 8.0, tilt_mrad: tuple = (0.0, 0.0),
             num_frozen_phonons: int = 0, sigmas: float = 0.1,
             max_angle_mrad: float = 50.0) -> np.ndarray:
        """Convergent-beam diffraction pattern at a single (central) probe position.

        Each reflection becomes a DISK the size of `convergence_mrad`. If the
        convergence exceeds the spot spacing the disks overlap (Ronchigram /
        ptychography regime). Returns a 2D intensity array.
        """
        probe = abtem.Probe(energy=self.energy_ev, semiangle_cutoff=convergence_mrad,
                            sampling=self.sampling, tilt=tuple(tilt_mrad),
                            device=self.device)
        pot = (self._potential_frozen(atoms, num_frozen_phonons, sigmas)
               if num_frozen_phonons and num_frozen_phonons > 0 else self._potential(atoms))
        probe.grid.match(pot)
        det = abtem.PixelatedDetector(max_angle=max_angle_mrad)
        if num_frozen_phonons and num_frozen_phonons > 0:
            meas = probe.multislice(pot, detectors=det).mean(0).compute()
        else:
            meas = probe.multislice(pot, detectors=det).compute()
        return np.asarray(meas.array, dtype=np.float32)

    def scan_4d(self, atoms, convergence_mrad: float = 8.0, scan_gpts: tuple = (6, 6),
                scan_extent_A: float | tuple | None = None, max_angle_mrad: float = 50.0):
        """4D-STEM scan: a CBED pattern at every probe position.

        Returns (data_4d, meta) where data_4d has shape
        (scan_y, scan_x, det_y, det_x) and meta is a dict with the scan/probe params.
        The 4D array is what py4DSTEM's DataCube wraps directly.

        scan_extent_A : side length (or (x, y)) of the scanned region in Angstrom.
            Defaults to ~2 lattice-ish (a small representative patch). Kept modest
            because cost scales with the number of probe positions.
        """
        probe = abtem.Probe(energy=self.energy_ev, semiangle_cutoff=convergence_mrad,
                            sampling=self.sampling, device=self.device)
        pot = self._potential(atoms)
        probe.grid.match(pot)

        cell_xy = np.array(atoms.cell.lengths()[:2])
        if scan_extent_A is None:
            ext = np.minimum(cell_xy * 0.8, np.array([8.0, 8.0]))  # small patch, within cell
        elif np.isscalar(scan_extent_A):
            ext = np.array([float(scan_extent_A), float(scan_extent_A)])
        else:
            ext = np.array(scan_extent_A, dtype=float)

        scan = abtem.GridScan(start=(0.0, 0.0), end=(float(ext[0]), float(ext[1])),
                              gpts=tuple(int(g) for g in scan_gpts))
        det = abtem.PixelatedDetector(max_angle=max_angle_mrad)
        dataset = probe.scan(pot, scan=scan, detectors=det).compute()
        data_4d = np.asarray(dataset.array, dtype=np.float32)
        meta = {"convergence_mrad": float(convergence_mrad),
                "scan_gpts": tuple(int(g) for g in scan_gpts),
                "scan_extent_A": ext.tolist(),
                "energy_kev": self.energy_ev / 1e3,
                "max_angle_mrad": float(max_angle_mrad),
                "shape": data_4d.shape}
        return data_4d, meta

    # ------------------------------------------------------------------ #
    # Utilities
    # ------------------------------------------------------------------ #
    @staticmethod
    def tilted_atoms(atoms, tilt_deg_x: float = 0.0, tilt_deg_y: float = 0.0):
        """Return a copy of `atoms` rotated for a LARGE zone-axis change (degrees).

        For big tilts, rotating the structure is more correct than a small beam
        tilt. Note: after rotation the periodic cell is only approximate at the
        faces; use a thick enough slab that the region of interest is interior.
        For CRYSTALS, prefer `build_crystal_tilted` (below), which rotates a large
        crystal and re-crops a clean cubic cell so the pattern stays square and the
        faces stay periodic.
        """
        a = atoms.copy()
        if tilt_deg_x:
            a.rotate(tilt_deg_x, "x", rotate_cell=False)
        if tilt_deg_y:
            a.rotate(tilt_deg_y, "y", rotate_cell=False)
        pos = a.get_positions()
        pos = pos - pos.min(axis=0)
        ext = pos.max(axis=0) + 0.5
        return Atoms(numbers=a.get_atomic_numbers(), positions=pos, cell=ext.tolist(), pbc=True)

    @staticmethod
    def build_crystal_tilted(element: str, structure: str, a: float,
                             tilt_deg_x: float = 0.0, tilt_deg_y: float = 0.0,
                             box_A: float = 60.0, thickness_A: float = 100.0,
                             c: float | None = None):
        """Build a crystal at a given SPECIMEN TILT (degrees), as a clean cubic-ish
        cell suitable for a tilt series.

        The recipe that keeps diffraction patterns square and artifact-free under
        tilt: build a crystal large enough to contain the tilted region, rotate the
        whole lattice by the tilt, then CROP a centred box (box_A x box_A laterally,
        thickness_A along the beam) from the interior. Because the crop is taken
        from the middle of a bigger crystal, its faces are clean lattice planes, not
        ragged cuts, so the pattern stays sharp as you tilt.

        This is the recommended way to make a multislice tilt series that mirrors
        the twin's stage a/b tilt.
        """
        # Big enough parent crystal so the rotated crop is fully interior.
        diag = np.sqrt(2 * box_A**2 + thickness_A**2)
        reps = int(np.ceil(diag / a)) + 2
        parent = AbtemDiffraction.build_crystal(element, structure, a,
                                                size=(reps, reps, reps), c=c)
        pos = parent.get_positions()
        Z = parent.get_atomic_numbers()
        # centre at origin, rotate about x (a-tilt) then y (b-tilt)
        pos = pos - pos.mean(axis=0)

        def rot(pos, deg, axis):
            th = np.radians(deg)
            ca, sa = np.cos(th), np.sin(th)
            R = {"x": np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]]),
                 "y": np.array([[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]])}[axis]
            return pos @ R.T

        if tilt_deg_x:
            pos = rot(pos, tilt_deg_x, "x")
        if tilt_deg_y:
            pos = rot(pos, tilt_deg_y, "y")
        # crop a centred cubic-ish box from the interior
        hb = box_A / 2.0
        ht = thickness_A / 2.0
        keep = ((np.abs(pos[:, 0]) <= hb) & (np.abs(pos[:, 1]) <= hb) &
                (np.abs(pos[:, 2]) <= ht))
        pos = pos[keep] - np.array([-hb, -hb, -ht])   # shift to positive octant
        cell = [box_A, box_A, thickness_A]
        return Atoms(numbers=Z[keep], positions=pos, cell=cell, pbc=True)

    @staticmethod
    def save_4d(data_4d: np.ndarray, path: str) -> str:
        """Save a 4D-STEM stack as .npy (py4DSTEM.DataCube(data=np.load(path)))."""
        np.save(path, np.asarray(data_4d, dtype=np.float32))
        return path

    @staticmethod
    def display_u16(pattern: np.ndarray, beamstop_radius: int = 6,
                    log: bool = False) -> np.ndarray:
        """Convert a raw pattern to a display-ready uint16 frame with the DIRECT
        (000) beam suppressed.

        The undiffracted beam is ~100x brighter than the Bragg spots, so a naive
        contrast stretch shows only the central dot. We clip the display maximum
        to the Bragg level (a computational beam stop) so the spots are visible.
        This changes only the display, not the data.
        """
        p = np.asarray(pattern, dtype=np.float64)
        cy, cx = np.unravel_index(np.argmax(p), p.shape)
        Y, X = np.mgrid[0:p.shape[0], 0:p.shape[1]]
        outside = np.hypot(Y - cy, X - cx) > beamstop_radius
        img = np.log1p(p) if log else p
        vmax = np.percentile(img[outside], 99.9) if outside.any() else img.max()
        vmax = max(float(vmax), 1e-12)
        return (np.clip(img / vmax, 0.0, 1.0) * 65535.0).astype(np.uint16)
