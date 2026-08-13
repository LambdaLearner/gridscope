"""v3 sample-layer physics invariants.

These pin the measured numbers from the v3 changelog (Digital_twin_revised_v3/
STEM_Digital_Twin_v3_CHANGELOG.md) as regression tests: region-honest atom
returns, true projected column spacings, the corrected Burgers vector, per-grain
orientation, and the exact tile_lattice_in_region cell bracket. All values are
deterministic — a change here means the projection geometry or region logic
changed behaviour, not just implementation.
"""

import numpy as np
import pytest

from app.digital_twin.samples import base
from app.digital_twin.samples.base import (
    atoms_in_requested_box,
    projected_column_spacing_A,
    rotation_taking_to_beam,
    tile_lattice_in_region,
)
from app.digital_twin.samples.dislocation_crystal import (
    ZONE_AXES,
    DislocationCrystal,
)
from app.digital_twin.samples.fcc_single_crystal import FCCSingleCrystal
from app.digital_twin.samples.polycrystal_grains import PolycrystalGrains


# ---------------------------------------------------------------------------
# Region-honest atom returns (changelog §3.1-3.2)
# ---------------------------------------------------------------------------
class TestRegionHonestAtoms:
    def test_small_fov_returns_exactly_the_requested_atoms(self):
        """2 nm FOV at the renderer's 4 nm default depth -> 1391 atoms, 17.9 A
        span (the changelog's measured 'exact branch' numbers)."""
        s = FCCSingleCrystal()
        pos, Z = s.get_atoms_in_region(0, 0, half_width_um=0.001, depth_nm=4.0)
        assert len(pos) == 1391
        span = float(pos[:, 0].max() - pos[:, 0].min())
        assert span == pytest.approx(17.9, abs=0.1)

    def test_huge_aperture_falls_back_to_representative_cube(self):
        """A 0.4 um SAED aperture (~1e8 atoms) cannot be enumerated: the
        fallback fires, is flagged, and stays under the atom budget."""
        s = FCCSingleCrystal()
        pos, Z, rep = atoms_in_requested_box(s.lattice, 0.2 * 1e4, 120.0)
        assert rep is True
        assert 0 < len(pos) <= 250000

    def test_exact_branch_not_flagged_representative(self):
        s = FCCSingleCrystal()
        pos, Z, rep = atoms_in_requested_box(s.lattice, 10.0, 40.0)
        assert rep is False
        assert len(pos) == 1391


# ---------------------------------------------------------------------------
# Zone axes and projected column spacing (changelog §3.3, §9.2)
# ---------------------------------------------------------------------------
class TestZoneAxesAndSpacing:
    @pytest.mark.parametrize("zone", sorted(ZONE_AXES))
    def test_rotation_puts_zone_axis_on_beam(self, zone):
        R = rotation_taking_to_beam(ZONE_AXES[zone])
        v = np.asarray(ZONE_AXES[zone], float)
        v = v / np.linalg.norm(v)
        assert np.allclose(R @ v, [0, 0, 1], atol=1e-4)

    def test_rotation_degenerate_cases(self):
        assert np.allclose(rotation_taking_to_beam([0, 0, 1]), np.eye(3))
        # antiparallel: a valid rotation (det=+1) taking -z to +z
        R = rotation_taking_to_beam([0, 0, -1])
        assert np.allclose(R @ np.array([0.0, 0.0, -1.0]), [0, 0, 1], atol=1e-12)
        assert np.linalg.det(R) == pytest.approx(1.0)
        # zero vector: identity, not an error
        assert np.allclose(rotation_taking_to_beam([0, 0, 0]), np.eye(3))

    def test_fcc_111_projected_spacing_is_a_over_sqrt6(self):
        """The moire-aliasing fix (R2): FCC down [111] projects to columns
        a/sqrt(6) = 1.458 A apart, NOT the cell vector 3.571 A. The server's
        Nyquist gate must see this number."""
        d = DislocationCrystal(zone_axis="111")
        assert d.column_spacing_A() == pytest.approx(1.458, abs=0.005)

    def test_dislocation_exposes_column_spacing_method(self):
        """R2 regression: the hasattr gate the server uses must find it."""
        assert hasattr(DislocationCrystal(), "column_spacing_A")

    def test_burgers_vector_is_fcc_slip_vector(self):
        """Physics correction: |a/2<110>| = a/sqrt(2) = 2.525 A (was a)."""
        d = DislocationCrystal()
        assert d.params["burgers_A"] == pytest.approx(2.525, abs=0.001)

    def test_zone_axis_schema_has_choices(self):
        schema = DislocationCrystal.meta.param_schema["zone_axis"]
        assert schema["choices"] == ["001", "011", "110", "111", "112"]
        assert DislocationCrystal.meta.default_params["zone_axis"] == "111"


# ---------------------------------------------------------------------------
# Dislocation strain reaches the imaged atoms (changelog §3.3)
# ---------------------------------------------------------------------------
class TestDislocationStrain:
    def test_strain_displaces_the_returned_atoms(self):
        """12 dislocations vs 0 over a 4 nm field: every atom displaced,
        mean displacement 1.80 A (changelog measured values)."""
        kw = dict(seed=3)
        d0 = DislocationCrystal(n_dislocations=0, **kw)
        d12 = DislocationCrystal(n_dislocations=12, **kw)
        p0, _ = d0.get_atoms_in_region(0, 0, 0.002, 4.0)
        p12, _ = d12.get_atoms_in_region(0, 0, 0.002, 4.0)
        n = min(len(p0), len(p12))
        assert n > 1000
        disp = np.linalg.norm(p12[:n] - p0[:n], axis=1)
        assert (disp > 1e-6).mean() == pytest.approx(1.0, abs=0.01)
        assert disp.mean() == pytest.approx(1.80, abs=0.15)


# ---------------------------------------------------------------------------
# Per-grain orientation (changelog §3.4)
# ---------------------------------------------------------------------------
class TestPolycrystalOrientation:
    def _grains(self, **params):
        pc = PolycrystalGrains(n_grains=5, seed=3, **params)
        pc.generate_volume(12, 96, 96)
        return pc

    def test_all_grains_reachable_with_distinct_lattices(self):
        pc = self._grains()
        # Probe a coarse position grid and collect the grain under each point
        span = pc.generation_range_um / 2 * 0.9
        seen = {}
        for x in np.linspace(-span, span, 12):
            for y in np.linspace(-span, span, 12):
                g = pc.grain_at(x, y)
                if g is not None:
                    seen[int(g)] = pc.lattice_at(x, y)
        assert sorted(seen) == [0, 1, 2, 3, 4]
        names = {lat.name for lat in seen.values()}
        assert len(names) == 5  # each grain its own oriented lattice

    def test_default_orientation_mode_is_random_zone_axes(self):
        assert PolycrystalGrains.meta.default_params["orientation_mode"] == \
            "random_zone_axes"
        schema = PolycrystalGrains.meta.param_schema["orientation_mode"]
        assert schema["choices"] == ["random_zone_axes", "random_3d", "in_plane"]

    def test_in_plane_mode_keeps_beam_axis_fixed(self):
        """Legacy mode: every grain keeps [001] on the beam (identical
        beam-axis cell components), merely spun about it."""
        pc = self._grains(orientation_mode="in_plane")
        z_components = set()
        span = pc.generation_range_um / 2 * 0.9
        for x in np.linspace(-span, span, 12):
            lat = pc.lattice_at(x, 0)
            if lat is not None:
                z_components.add(round(float(lat.real_vectors[2][2]), 6))
        assert len(z_components) == 1

    def test_lattice_at_before_generate_is_none(self):
        pc = PolycrystalGrains(n_grains=3, seed=1)
        assert pc.lattice_at(0, 0) is None


# ---------------------------------------------------------------------------
# tile_lattice_in_region exact cell bracket (changelog §11.4)
# ---------------------------------------------------------------------------
class TestTileLatticeBracket:
    def _brute_force(self, lattice, half_A, depth_A):
        """Reference: the old conservative bracket, minus its bugs — enumerate
        a generously oversized grid and mask. Slow but obviously correct."""
        a1, a2, a3 = (np.asarray(v, float) for v in lattice.real_vectors)
        n = 40
        ii = np.arange(-n, n + 1)
        atoms = []
        for i in ii:
            for j in ii:
                for k in ii:
                    origin = i * a1 + j * a2 + k * a3
                    for frac, Z in lattice.basis:
                        p = origin + frac[0] * a1 + frac[1] * a2 + frac[2] * a3
                        if (abs(p[0]) <= half_A and abs(p[1]) <= half_A
                                and abs(p[2]) <= depth_A / 2.0):
                            atoms.append((round(p[0], 2), round(p[1], 2),
                                          round(p[2], 2), Z))
        return set(atoms)

    def test_set_equal_to_brute_force_cubic(self):
        lat = FCCSingleCrystal().lattice
        pos, Z = tile_lattice_in_region(lat, 15.0, 30.0)
        got = {(round(p[0], 2), round(p[1], 2), round(p[2], 2), int(z))
               for p, z in zip(pos, Z)}
        assert got == self._brute_force(lat, 15.0, 30.0)

    def test_set_equal_for_rotated_cell(self):
        """FCC rotated to [111] — a non-axis-aligned cell must still fill
        its box exactly (the corner-bracket must handle rotation)."""
        lat = DislocationCrystal(zone_axis="111").lattice
        pos, Z = tile_lattice_in_region(lat, 12.0, 24.0)
        got = {(round(p[0], 2), round(p[1], 2), round(p[2], 2), int(z))
               for p, z in zip(pos, Z)}
        assert got == self._brute_force(lat, 12.0, 24.0)

    def test_wide_thin_request_is_fast_and_bounded(self):
        """The old bracket built a 76-85x oversized grid for wide/thin boxes
        (OOM risk). The exact bracket must handle a very wide request without
        excessive allocation — completing at all (quickly) is the regression."""
        import time
        lat = FCCSingleCrystal().lattice
        t0 = time.time()
        pos, Z = tile_lattice_in_region(lat, 1000.0, 8.0)
        elapsed = time.time() - t0
        assert len(pos) > 100000          # genuinely filled
        assert elapsed < 5.0              # old bracket took ~6 s at 508 A wide

    def test_degenerate_cell_does_not_crash(self):
        class Flat:
            real_vectors = [np.array([3.0, 0.0, 0.0]),
                            np.array([3.0, 0.0, 0.0]),   # linearly dependent
                            np.array([0.0, 0.0, 3.0])]
            basis = [((0.0, 0.0, 0.0), 26)]
        pos, Z = tile_lattice_in_region(Flat(), 10.0, 10.0)
        assert pos.shape[1] == 3  # fell back to the conservative bracket


# ---------------------------------------------------------------------------
# Merged helpers are single-sourced (changelog §9.3)
# ---------------------------------------------------------------------------
class TestHelperMerge:
    def test_helpers_are_the_same_objects(self):
        from app.digital_twin.samples import dislocation_crystal as dc
        from app.digital_twin.samples import polycrystal_grains as pg
        assert dc.rotation_taking_to_beam is base.rotation_taking_to_beam
        assert pg._rot_axis_to_beam is base.rotation_taking_to_beam
        assert dc.projected_column_spacing_A is base.projected_column_spacing_A
        assert pg.projected_column_spacing_A is base.projected_column_spacing_A

    def test_polycrystal_column_spacing_uses_true_projection(self):
        pc = PolycrystalGrains(n_grains=2, seed=1)
        # [001] FCC: projected spacing a/2 = 1.785 A (changelog §9.4)
        assert pc.column_spacing_A() == pytest.approx(1.785, abs=0.005)
