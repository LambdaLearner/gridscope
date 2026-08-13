# STEM Digital Twin — Change Breakdown, v2 → v3

> **Four changes are documented here.** **Part A** (§1–§7) is the v2 → v3 diff you
> built. **Part B** (§8) is the acquisition-resolution change applied *on top of* v3:
> the window set moves from 512/1024/2048 to **1024/2048/4096**. Part B touches files
> Part A did not, so review them separately. **Part C** (§9) records review items
> R1, R2 and R3, which are now **applied** — §5 is kept as the original finding for
> context, and §9 is what actually shipped. **Part D** (§10) covers the two abTEM
> notebooks, which needed changes after all. **Part E** (§11) fixes the dark border and
> tilt artifacts seen in Demo J, and the `tile_lattice_in_region` bug they exposed.

---

# PART A — v2 → v3

**Base (old):** `STEM_Digital_Twin_Modular_final_w_PyJEM_with_abTEM.ipynb`
**Head (new):** `STEM_Digital_Twin_Modular_final_w_PyJEM_with_abTEM_v3.ipynb`

**Scope of the diff:** 106 cells in, 106 cells out. **98 cells byte-identical; 8 changed.**
No cells added, removed, reordered, or retyped. +449 / −121 source lines
(294,049 → 310,095 chars).

Everything below was derived by md5-hashing every cell source in both notebooks and
diffing only the ones that moved — not by reading and summarising. Behavioural claims
were then checked by executing the v3 sample modules (see §6).

---

## 1. One-paragraph summary

v3 makes the high-magnification atomic-column image **read the sample's real atoms**
instead of re-tiling an idealised lattice. Before, `_render_atomic_columns()` took a
`lattice` object and tiled a perfect crystal to fill the field — so the picture was of an
ideal crystal regardless of what the sample actually contained. Now it takes the `sample`
and calls `get_atoms_in_region()`, the same entry point the diffraction engine already
used. That single seam change is what makes dislocation strain visibly distort the imaged
columns, makes each polycrystal grain image in its own orientation, and makes stage tilt
re-project real 3-D coordinates. Supporting that are three new capabilities in the sample
layer: region-honest atom return with a documented large-aperture fallback
(`atoms_in_requested_box`), a configurable zone axis on the dislocation sample (default
`[111]`), and per-grain zone axes on the polycrystal (default `random_zone_axes`).

---

## 2. Change inventory — in notebook order

| Cell | Type | Target | +/− lines | What changed |
|---:|---|---|---:|---|
| 0 | markdown | title / overview | +12 / −0 | New "Single source of truth" section documenting the revision |
| 4 | code | `samples/base.py` | +27 / −0 | Added `atoms_in_requested_box()` |
| 7 | code | `samples/fcc_single_crystal.py` | +9 / −17 | `get_atoms_in_region` now honours the requested region |
| 8 | code | `samples/bcc_single_crystal.py` | +9 / −17 | Same change as FCC |
| 9 | code | `samples/hcp_single_crystal.py` | +9 / −12 | Same change as FCC |
| 11 | code | `samples/polycrystal_grains.py` | +165 / −17 | Per-grain zone axes; `lattice_at`, `grain_at`, `column_spacing_A` |
| 12 | code | `samples/dislocation_crystal.py` | +138 / −33 | Configurable zone axis (default `[111]`); corrected Burgers vector |
| 25 | code | `stem_server_twisted_colab.py` | +80 / −25 | `_render_atomic_columns` re-signatured to consume the sample |

**Unchanged (98 cells)** — including `samples/__init__.py`, `amorphous_film.py`,
`shape_assembly.py`, all five Au/nanoparticle samples, `core_shell.py`,
`atomsk_polycrystal.py`, `stem_client.py`, `twin_io.py`, `microscope_backend.py`,
`feature_finding.py`, `abtem_diffraction.py`, and every demo/markdown cell after cell 25.
**No RPC signature, wire protocol, or backend interface changed**, so existing client code
and vendor adapters are unaffected.

---

## 3. Module-by-module detail

### 3.1 `samples/base.py` — new `atoms_in_requested_box()`

Purely additive; no existing function touched. New module-level helper:

```python
def atoms_in_requested_box(lattice, half_width_A, depth_A, max_atoms=250000):
    """Returns (positions_A, Z, is_representative)."""
```

It estimates atom count from lattice density × requested volume, then branches:

- **n ≤ max_atoms** → tiles the *actual requested box*. This is the imaging case: a few-nm
  field of view returns exactly the atoms that are really there.
- **n > max_atoms** → returns a **representative cube** centred on the same point, sized to
  the budget, and flags `is_representative=True`. This is the SAED case: a ~0.4 µm aperture
  contains ~10⁸ atoms and cannot be enumerated.

**Why it matters:** the old code always returned a fixed ~90,000-atom cube regardless of
what was asked for, so "give me the atoms in this 2 nm field" and "give me the atoms in
this 0.4 µm aperture" returned the same thing. That was fine for diffraction (which only
needs a representative volume) but wrong for imaging (which needs the actual field).

*Measured:* 2 nm FOV → 1,391 atoms spanning 17.9 Å (exact). 0.4 µm aperture → 71,771 atoms
spanning 139 Å (representative fallback, correctly flagged).

### 3.2 `fcc` / `bcc` / `hcp_single_crystal.py` — region-honest atoms

All three received the identical edit. Import line gains `atoms_in_requested_box`, and
`get_atoms_in_region` shrinks from ~15 lines to ~7:

```python
# OLD — ignored the request, always returned a ~90k-atom cube
target = 90000.0
side_A = float((target / max(1e-9, density)) ** (1.0 / 3.0))
return tile_lattice_in_region(self.lattice, side_A / 2.0, side_A)

# NEW — honours the request, falls back only when it has to
half_A  = max(1.0, float(half_width_um) * 1.0e4)
depth_A = max(1.0, float(depth_nm) * 10.0)
pos, Z, _rep = atoms_in_requested_box(self.lattice, half_A, depth_A)
return pos.astype(np.float64), Z.astype(np.int32)
```

The removed docstrings explained why a *cubic* region kept the shape transform isotropic
for off-zone patterns. **Correction (see §11):** that rationale survives only in the
*representative* branch of `atoms_in_requested_box`. The *exact* branch returns
`half_width x half_width x depth`, which at a 5 nm field with 100 nm working thickness is a
1:20 aspect column, not a cube — and that anisotropy is what produced the tilt artifacts in
Demo J. The column renderer now caps its own depth; the diffraction path is unaffected
because a SAED aperture always lands in the representative (cubic) branch.

### 3.3 `samples/dislocation_crystal.py` — configurable zone axis

**New module-level:**

- `ZONE_AXES` — dict mapping `"001" | "011" | "110" | "111" | "112"` to direction vectors.
- `rotation_taking_to_beam(zone)` — Rodrigues rotation putting a crystal direction on +z.
- `projected_column_spacing_A(lattice, nmax=2)` — the **true** minimum spacing between
  distinct projected atomic columns.

**Parameter changes:**

| Param | Old | New | Note |
|---|---|---|---|
| `zone_axis` | *(did not exist)* | `"111"` | New; schema `choices` = 001/011/110/111/112 |
| `burgers_A` | `3.571` (= a) | `2.525` (= a/√2) | **Physics correction:** \|a/2⟨110⟩\|, the real FCC slip vector |
| `display_name` | Fe FCC with Edge Dislocations (many) | Fe FCC **[111]** with Edge Dislocations (many) | |

`__init__` now builds a cube-axis cell and rotates it: `real_vectors = cube @ R.T`, storing
`self.zone_axis_hkl` and `self.orientation_R`. Lattice name becomes `FCC-dislocation[111]`.

`get_atoms_in_region` switches to `atoms_in_requested_box` and — importantly — recomputes
the half-width the strain field acts over, so strain is applied across whatever box was
actually returned rather than an assumed one:

```python
box_half_A = half_A if not is_rep else float(np.abs(bp[:, :2]).max() + 1e-6)
```

**Honesty note carried in the new file header (worth reading in full):** the dislocation
*lines* run along the beam so cores are seen end-on. For real FCC {111}⟨110⟩ slip, an edge
dislocation on (111) has line direction ⟨112⟩ — so the strictly correct end-on view is
`zone_axis="112"`. The `[111]` default gives the legible hexagonal projection with cores
end-on, and the file explicitly labels that a modelling convenience rather than a
crystallographic claim. Good — but make sure your colleague reads it before quoting the
[111] view in anything published.

*Measured:* each zone axis rotates its direction onto +z to within 1e-4. With
`n_dislocations=12` vs `0` over a 4 nm field, 100% of atoms are displaced, mean 1.80 Å,
max 6.56 Å — the strain genuinely reaches the atoms the imager receives.

### 3.4 `samples/polycrystal_grains.py` — per-grain orientation

Largest change in the sample layer (+165 lines).

**New module-level:** `GRAIN_ZONE_AXES` (six low-index axes: 001, 011, 111, 112, 013, 123),
`_rot_axis_to_beam()`, `projected_column_spacing_A()` (identical body to the dislocation
copy — see review item R3).

**New parameter `orientation_mode`**, default `"random_zone_axes"`, schema choices
`["random_zone_axes", "random_3d", "in_plane"]`:

| Mode | Behaviour | Trade-off |
|---|---|---|
| `random_zone_axes` **(default)** | Each grain on a *different low-index zone axis* + random spin | Grains differ **and** stay resolvable — best for seeing orientation change across a boundary |
| `random_3d` | Uniform SO(3) per grain (Shoemake quaternion) | Physically honest for an untextured polycrystal, but a random orientation is almost never near a zone axis, so most grains show no resolvable columns |
| `in_plane` | Legacy: every grain keeps [001] on the beam, spun about it | All grains give the *same* square net, merely rotated. Kept for the didactic orientation-mapping demo |

`max_tilt_deg` is now used **only** by the legacy `in_plane` mode.

**New methods on `PolycrystalGrains`:**

- `lattice_at(cx_um, cy_um)` → the oriented `CrystalLattice` of the grain under that
  position, so the column renderer draws each grain's own orientation. Returns `None`
  before `generate_volume()`.
- `grain_at(cx_um, cy_um)` → grain index (useful for the GUI).
- `column_spacing_A(lattice=None)` → true projected column spacing, the number the
  server's Nyquist gate should use.
- `_uniform_random_rotation(rng)` (static) → Shoemake uniform SO(3).

`get_atoms_in_region` is **unchanged** — it already did per-grain Voronoi assignment.

*Measured:* over a 5-grain specimen all five grains are reachable, each returning a
distinct rotated lattice (`FCC-poly-grain0` … `grain4`). In `random_zone_axes`, five grains
landed on four distinct zone axes; `in_plane` gave identical beam-axis components for all
five, as designed.

### 3.5 `stem_server_twisted_colab.py` — the seam change

**`_render_atomic_columns` re-signatured:**

```python
# OLD
def _render_atomic_columns(lattice, fov_nm, out_size, tilt_a_deg, tilt_b_deg,
                           thickness_nm=4.0, probe_nm=0.05, max_atoms=250000)

# NEW
def _render_atomic_columns(sample, cx_um, cy_um, fov_nm, out_size,
                           tilt_a_deg, tilt_b_deg, thickness_nm=4.0, probe_nm=0.05)
```

The body no longer imports `tile_lattice_in_region` or synthesises a lattice. It calls
`sample.get_atoms_in_region(cx_um, cy_um, half_um, thickness_nm)` — the same call the
diffraction engine makes — and projects whatever comes back. Also gains a guard for
`sample is None` / missing method, a try/except around the atom fetch, and an early return
when no atoms land in frame.

**At the call site (`_render_image`)**, three things were added before the gate:

1. Probe position derived from stage: `cx_um_probe`, `cy_um_probe`.
2. Per-grain lattice lookup — `sample.lattice_at(cx, cy)` when the sample provides it,
   falling back to `sample.lattice`.
3. Resolvability now gated on `sample.column_spacing_A(lat)` when available, instead of
   `norm(lat.real_vectors[0])`. This matters: FCC down [111] projects to columns
   **1.458 Å** apart (= a/√6), not 3.571 Å — a 2.45× difference. Gating on the cell vector
   would draw columns below Nyquist, which alias into a moiré grid.

The `3.5 px` resolvability threshold and the `0.6 × w × local` blend are unchanged.

---

## 4. Behavioural consequences

| Before v3 | After v3 |
|---|---|
| High-mag columns tiled from an ideal lattice — a dislocated crystal imaged as a perfect one | Columns projected from real atoms; strain visibly distorts them |
| Every polycrystal grain imaged with the same column pattern | Each grain images in its own orientation; panning a boundary changes the pattern |
| Tilt rotated a synthesised ideal lattice | Tilt re-projects the sample's real 3-D coordinates |
| `get_atoms_in_region` returned a fixed ~90k cube whatever you asked for | Small FOV → exactly those atoms; huge aperture → flagged representative volume |
| Dislocation sample fixed on [001] | Zone axis configurable, default [111] hexagonal |
| `burgers_A` = a (3.571 Å) | `burgers_A` = a/√2 (2.525 Å), the real FCC slip vector |
| Nyquist gate used the cell vector | Gate uses true projected column spacing where the sample provides it |

The header claim of **S/N 27 vs 1.3** for dislocation strain coupling is consistent with
what the code now does (strain reaches 100% of imaged atoms, mean 1.80 Å), but the figure
itself comes from your run, not from anything reproduced here — cite it as such.

---

## 5. Review items — as originally found

> **STATUS: all three are now FIXED.** This section is retained as the original
> diagnosis so the reasoning is on record; see **§9** for exactly what changed.

None of these broke the v3 output. All three were worth fixing before this went further.

### R1 — Duplicated column-render block in the server (dead code, silently failing)

`stem_server_twisted_colab.py`, `_render_image`, **lines 1167–1214 of the cell source**:
the new block was inserted but the old one was **not removed**. There are now two
consecutive `if lat is not None and nm_per_px > 0:` blocks. The second still calls the old
signature:

```python
cols = _render_atomic_columns(lat, fov_um * 1000.0, out_size, a_deg2, b_deg2)
```

Against the new 7-required-argument signature this raises
`TypeError: _render_atomic_columns() missing 2 required positional arguments:
'tilt_a_deg' and 'tilt_b_deg'` — which is swallowed by the block's bare
`except Exception: pass`. *(Verified by reproducing the call.)*

**Impact today:** images are correct, because the first block already did the work. The
cost is a wasted `column_spacing_A()` computation plus a raised-and-discarded exception on
every high-mag frame.

**Impact tomorrow:** this is a live trap. Anyone who "fixes" that call to match the new
signature will silently apply the column blend **twice**. And the bare `except` means a
genuine failure in the working block would also disappear without trace.

**Fix:** delete the second block (the one whose `_render_atomic_columns` call has five
arguments). Nothing else references it.

### R2 — `DislocationCrystal` never exposes `column_spacing_A`

`dislocation_crystal.py` defines module-level `projected_column_spacing_A()` — but never
wraps it as a `column_spacing_A` **method** on the class, which is what the server's
`hasattr(self.current_sample, "column_spacing_A")` gate looks for. `PolycrystalGrains`
does define it; `DislocationCrystal` does not.

So the sample whose whole point is the [111] hexagonal projection is the one that falls
back to `norm(real_vectors[0])`:

| zone | true projected spacing | server fallback | overestimate |
|---|---|---|---|
| [001] | 1.786 Å | 3.571 Å | 2.00× |
| [011] | 2.187 Å | 3.571 Å | 1.63× |
| **[111] (default)** | **1.458 Å** | **3.571 Å** | **2.45×** |
| [112] | 1.263 Å | 3.571 Å | 2.83× |

The gate fires at `period_px ≥ 3.5` computed from 3.571 Å, so at the default [111] it
draws columns whose true period is 3.5/2.45 ≈ **1.43 px** — below the 2 px Nyquist limit,
producing exactly the moiré aliasing the new docstring warns about.

**Fix** — four lines, mirroring the polycrystal method:

```python
    def column_spacing_A(self, lattice=None):
        """True projected atomic-column spacing (A) for the beam direction."""
        lat = lattice if lattice is not None else self.lattice
        return projected_column_spacing_A(lat)
```

### R3 — Docstring/default mismatch and a duplicated helper

- `polycrystal_grains.py`, `_grain_setup` docstring says
  `* "random_3d" (DEFAULT, physically realistic)` — but the actual default is
  `random_zone_axes`. The inline comment above the parameter documents `random_3d` and
  `in_plane` and doesn't mention the mode it's actually set to.
- `projected_column_spacing_A()` is defined **identically in two files**
  (`polycrystal_grains.py` and `dislocation_crystal.py`). It belongs in `samples/base.py`
  alongside `atoms_in_requested_box`, imported by both. Likewise `_rot_axis_to_beam` and
  `rotation_taking_to_beam` are the same function under two names.

*(All three are now applied across all three notebooks — see §9.)*

---

## 6. What was propagated, and how

`samples/base.py`, the three single crystals, `polycrystal_grains.py`,
`dislocation_crystal.py`, and `stem_server_twisted_colab.py` also ship inside two other
notebooks. Both were confirmed by md5 to hold **byte-identical old copies** of all seven
modules, so propagation was a straight source swap keyed on the `%%writefile` target
(not on cell position), leaving every other cell untouched.

| Delivered file | Cells replaced |
|---|---|
| `STEM_Digital_Twin_Clean_Kinematical_v3.ipynb` | 4, 7, 8, 9, 11, 12, 25 |
| `STEM_Digital_Twin_Limits_Playground_v3.ipynb` | 4, 6, 7, 8, 9, 10, 19 |
| `STEM_Twin_GUI_Build_Spec_v3.md` | §1.1, §1.2, §2.3b (new), A2 table |
| `STEM_Digital_Twin_ReadMe_v3.ipynb` | §0 (new) |

Both notebooks pass `nbformat.validate()` and all seven module hashes now match v3 exactly.
`abtem_diffraction.py`'s *code* is unchanged in v3, but its **documentation went stale** as a result of the sample-layer change — see §10, which corrects it and updates the two abTEM notebooks.

*(Pre-existing, not introduced: 4 cells in the Clean Kinematical notebook lack `id` fields.
Colab tolerates this; `nbformat.normalize()` fixes it if you want it clean.)*

### Verification log

| Check | Result |
|---|---|
| Cell count / type / order preserved | 106 → 106, no adds/removes/reorders |
| Cells changed | 8 of 106, by md5 |
| v3 sample modules import and construct | pass |
| `atoms_in_requested_box` exact vs representative branch | pass — 2 nm exact, 0.4 µm falls back |
| Zone-axis rotations land on +z | pass, all five axes, ≤1e-4 |
| Strain reaches imaged atoms (12 vs 0 dislocations) | pass — 100% displaced, mean 1.80 Å |
| `orientation_mode` distinguishes all three modes | pass |
| `lattice_at` / `grain_at` resolve distinct grains | pass — 5/5 reachable, distinct lattices |
| Stale call site raises TypeError (R1) | confirmed |
| Propagated notebooks valid + hashes match v3 | pass |

---

## 7. Appendix — cell hashes (md5, first 10)

| Module | old | v3 |
|---|---|---|
| `samples/base.py` | `208f488deb` | `be365fa431` |
| `samples/fcc_single_crystal.py` | `400f17156a` | `90df86da74` |
| `samples/bcc_single_crystal.py` | `134e92061b` | `cdbaa99bf2` |
| `samples/hcp_single_crystal.py` | `36c29e3bcb` | `855e04f472` |
| `samples/polycrystal_grains.py` | `a8aed22abd` | `e48ed68738` |
| `samples/dislocation_crystal.py` | `3d728a09f1` | `2221663f6e` |
| `stem_server_twisted_colab.py` | `08a70190cc` | `4d5467ff88` |

New public API introduced in v3:

```
samples/base.py                atoms_in_requested_box(lattice, half_width_A, depth_A, max_atoms=250000)
samples/dislocation_crystal.py ZONE_AXES
                               rotation_taking_to_beam(zone)
                               projected_column_spacing_A(lattice, nmax=2)
                               DislocationCrystal.zone_axis_hkl, .orientation_R
samples/polycrystal_grains.py  GRAIN_ZONE_AXES
                               _rot_axis_to_beam(zone)
                               projected_column_spacing_A(lattice, nmax=2)
                               PolycrystalGrains.lattice_at(cx_um, cy_um)
                               PolycrystalGrains.grain_at(cx_um, cy_um)
                               PolycrystalGrains.column_spacing_A(lattice=None)
                               PolycrystalGrains._uniform_random_rotation(rng)
```

New sample parameters for any GUI built against the registry:

```
dislocation_crystal.zone_axis        str, choices 001|011|110|111|112, default "111"
polycrystal_grains.orientation_mode  str, choices random_zone_axes|random_3d|in_plane,
                                     default "random_zone_axes"
```

Both are `type: "str"` **with a `choices` key** — render them as dropdowns, not text
fields. This is the first time `choices` appears in any `param_schema`, so schema-driven
control builders need a new branch (see the updated GUI spec §1.2).


---

# PART B — acquisition resolution: 512/1024/2048 → 1024/2048/4096

## 8. Resolution change

512 is **removed** and 4096 added, so the default moves to **1024**. This is not a
documentation-only change: 512 was the detector default and appears as a literal in demo
code, which would now raise `ValueError` on `set_resolution(512)`.

### 8.1 Every place changed

| File | Location | Old → New |
|---|---|---|
| `stem_server_twisted_colab.py` | `ALLOWED_RESOLUTIONS` | `(512, 1024, 2048)` → `(1024, 2048, 4096)` |
| `stem_server_twisted_colab.py` | `default_haadf()` → `"size"` | `512` → `1024` |
| `stem_server_twisted_colab.py` | comment above `ALLOWED_RESOLUTIONS` | rewritten with measured costs |
| `stem_client.py` | resolution section comment | notes the new set; says to read `allowed` at runtime |
| Demo O (markdown) | modular + clean | window list and stated default |
| Demo O (code) | modular + clean | panel list, timing loop, and the reset call |
| Clean nb, DIFF demo | `set_resolution(512)` reset | → `1024` |
| Limits nb, bounds table | Resolution + Magnification rows | new set; mag anchor re-expressed at 1024 px |
| Limits nb, IMG setup | `set_resolution(512)` | → `1024` |
| Limits nb, damage demo | `for res in [512, 1024]` | → `[1024, 2048]` |
| Limits nb, nm/px demo | `for res in [512, 1024, 2048]` | → `[1024, 2048, 4096]` |
| GUI spec | §2.5, intro, threading note, RPC cheat-sheet, A2 table, addendum ×3 | new set, new timings, new guidance |

**Deliberately left alone** — these are different quantities that happen to be 512:

- `sim.load_sample(..., H=512, W=512)` — the **volume** (voxel) grid, unrelated to the
  detector window. 8 occurrences.
- `acquire_spectrum(..., n_channels=512)` — EELS spectrum channels. 2 occurrences.
- Two historical references in the GUI spec addendum that explicitly describe an
  earlier 512→1024 measurement.

### 8.2 Two performance fixes that had to ride along

Adding 4096 without these makes it unusable, so both are included. **Both are
algebraically exact — verified against the pre-change code, not assumed.**

**PERF A — collapse the depth projection when untilted.** `_render_image` resampled the
volume once per z-slice. With no tilt every slice samples the *same* grid, and bilinear
sampling is linear in the slice values, so `Σ_z bilinear(vol[z])` = `bilinear(Σ_z vol[z])`.
Summing along z first turns D resamples into one, guarded by `if sa == 0.0 and sb == 0.0`.

**PERF B — patch-local spot rendering** in `kinematical_diffraction`. The spot loop
evaluated a full `out_size²` Gaussian *per spot* — at 4096 that is a 67 MB temporary each
time. Each spot now writes only into its own ±5σ neighbourhood, where the Gaussian has
fallen to <4e-6 of peak, i.e. below the 16-bit quantisation of the returned image.

Measured (CPU, D=40 volume, FCC lattice):

| | 1024 | 2048 | 4096 |
|---|---|---|---|
| IMG projection, before | 3.4 s | 23.0 s | 178.2 s |
| IMG projection, after (untilted) | 0.11 s | 1.19 s | 4.70 s |
| DIFF fallback, before | 0.19 s | 1.63 s | 7.69 s |
| DIFF fallback, after | 0.03 s | 0.18 s | 0.53 s |
| Relative difference, after vs before | 5e-7 | 6e-7 | 9e-7 |

A relative difference of ~1e-6 on a 0–65535 output is well under one quantisation step:
the images are identical as returned. **To revert either fix, delete the guarded fast path
and keep the `else` branch** — both are written as additions around the original code.

### 8.3 What your colleague should know about 4k

- **Cost scales with pixel count, so each step up is 4× the work**, and a 4096 frame is
  67 MB. A naive "keep the last 10 frames" history is 670 MB.
- **Tilt is what makes 4k expensive, not 4k itself.** An untilted 4096 frame is ~1.2 s; a
  tilted one cannot use PERF A and runs ~140 s. Worth a UI warning when someone selects
  4096 with a non-zero α/β.
- **Dose per pixel quadruples with each step up**, because
  `pixel_area = (FOV/resolution)²`. Beam damage and contamination will accrue markedly
  faster at 4096 than the existing measured numbers suggest. The damage figures quoted in
  the GUI spec addendum were taken on the old 512→1024 pair and are now flagged as
  historical — **re-measure before quoting them.**
- **Anything stored in detector pixels now means a different physical distance.** Beam-shift
  nudges, ROI boxes, marker sizes, and the diffraction beamstop radius should be carried in
  nm and converted through `FOV / resolution`, not held as pixel constants.

### 8.4 One open decision — spot size and beamstop do not scale

`kinematical_diffraction` takes `spot_sigma_px=2.5` and `beamstop_radius_px=6.0` as **fixed
pixel counts**, while spot *positions* scale with the frame (`base_radius = 0.18 *
out_size`). So the pattern geometry grows with resolution but the spots and the beamstop do
not: at 4096 they are 8× smaller relative to the pattern than at 512.

This is pre-existing behaviour, not something the resolution change introduced — going
512→1024 already halved relative spot width. But 4096 is where it becomes visible: spots
render as near-pinpricks and the beamstop barely covers the direct beam.

**Left unchanged on purpose.** Scaling them would alter the appearance of every existing
1024 and 2048 pattern, and that is a calibration decision that belongs to you, not to me.
If you want the pattern to look proportionally identical at every window, the change is to
scale both against a reference size:

```python
spot_sigma_px     = 2.5 * (out_size / 1024.0)
beamstop_radius_px = 6.0 * (out_size / 1024.0)
```

Say the word and I will apply it across all three notebooks.

### 8.5 Verification

| Check | Result |
|---|---|
| `ALLOWED_RESOLUTIONS` updated in all three servers | pass |
| Detector default is a legal value | pass — 1024 ∈ allowed |
| No `set_resolution(512)` call sites remain | pass — would now raise |
| Volume-grid `H=512, W=512` untouched | pass — 8 occurrences intact |
| EELS `n_channels=512` untouched | pass — 2 occurrences intact |
| PERF A exact vs per-slice loop | pass — rel. diff ≤ 6e-7 |
| PERF B exact vs full-grid render | pass — rel. diff ≤ 1.2e-6 |
| Notebooks still `nbformat`-valid | pass |

---

# PART C — review items R1, R2, R3 (applied)

## 9. What was fixed

All three applied to `samples/base.py`, `samples/polycrystal_grains.py`,
`samples/dislocation_crystal.py` and `stem_server_twisted_colab.py`, in **all three
notebooks**. Diagnosis is in §5; this is the record of what shipped.

### 9.1 R1 — duplicated column-render block removed

The stale second block in `_render_image` is gone, replaced by a five-line comment
explaining what was there and why it went. The live block — the one calling
`_render_atomic_columns(self.current_sample, cx_um_probe, cy_um_probe, ...)` — is untouched.

Verified: each server now contains exactly **one** `column_spacing_A` gate (was two), and
**zero** occurrences of the stale 5-argument call. Every `%%writefile` cell in all three
notebooks still parses as valid Python (62 cells checked with `ast.parse`).

**Left alone deliberately:** the surviving `except Exception: pass` on the live block. It is
broad enough to hide a genuine failure, but narrowing it could turn a currently-graceful
degradation into a hard crash mid-acquisition. Worth revisiting as its own change, with a
`logging.debug` rather than a bare `pass`.

### 9.2 R2 — `DislocationCrystal.column_spacing_A()` added

```python
    def column_spacing_A(self, lattice=None):
        lat = lattice if lattice is not None else self.lattice
        return projected_column_spacing_A(lat)
```

The server's `hasattr(sample, "column_spacing_A")` gate now finds it, so the Nyquist check
uses the true projected spacing instead of the cell-vector length.

What this fixes, measured — "gate fired at" is the *true* column period at the moment the
server decided columns were resolvable:

| zone | true spacing | old fallback | overestimate | gate fired at | verdict |
|---|---|---|---|---|---|
| [001] | 1.786 Å | 3.571 Å | 2.00× | 1.75 px | below 2 px Nyquist |
| [011] | 2.187 Å | 3.571 Å | 1.63× | 2.14 px | marginal |
| **[111] (default)** | **1.458 Å** | 3.571 Å | **2.45×** | **1.43 px** | **below 2 px Nyquist** |
| [112] | 1.263 Å | 3.571 Å | 2.83× | 1.24 px | below 2 px Nyquist |

Worth noting the original §5 write-up understated this: **three of the four zone axes tested
were affected, not just [111].** Only [011] was even marginally above Nyquist. With R2 the
gate uses the true number, so columns are drawn only when their real period is ≥ 3.5 px.

### 9.3 R3 — docstring corrected, duplicated helpers merged

**Docstring/default mismatch.** `_grain_setup` claimed `"random_3d" (DEFAULT, physically
realistic)`; the actual default is `random_zone_axes`. The docstring now documents
`random_zone_axes` as the default and describes `random_3d` on its own merits. The inline
comment on the parameter, which previously documented only the two modes it is *not* set
to, now covers all three. Asserted in the test: the mode named `(DEFAULT` in the docstring
equals `params["orientation_mode"]`.

**Duplicated helpers merged into `samples/base.py`.** Both were verified identical before
merging, not assumed:

- `projected_column_spacing_A` — identical by AST comparison.
- `rotation_taking_to_beam` (dislocation) vs `_rot_axis_to_beam` (polycrystal) — these
  differed in name, docstring and line wrapping, so the AST comparison **failed**. Checked
  numerically instead across 508 directions including the degenerate parallel,
  antiparallel and zero-vector cases: **max elementwise difference 0.0.** Safe to merge.

Both canonical definitions now live in `base.py`. **No import path was broken** — each
sample module imports the helpers into its own namespace, and `polycrystal_grains` keeps
`_rot_axis_to_beam` as an alias:

| import | resolves to base.py object |
|---|---|
| `samples.base.rotation_taking_to_beam` | canonical |
| `samples.dislocation_crystal.rotation_taking_to_beam` | ✓ same object |
| `samples.polycrystal_grains._rot_axis_to_beam` | ✓ same object (alias) |
| `samples.dislocation_crystal.projected_column_spacing_A` | ✓ same object |
| `samples.polycrystal_grains.projected_column_spacing_A` | ✓ same object |

Net effect: ~60 lines of duplicated code removed; one place to change if the projection
geometry is ever revised.

### 9.4 Regression — behaviour unchanged where it should be

Every number below is identical to the pre-R1/R2/R3 run:

| Check | Result |
|---|---|
| Zone axes still land on +z | max deviation 4.4e-16 |
| Atoms in a 4 nm FOV (dislocation) | 5529 — unchanged |
| Mean strain displacement, 12 vs 0 dislocations | 1.8028 Å — unchanged |
| `orientation_mode` spread: zone_axes / 3d / in_plane | 0.122 / 0.218 / 0.000 — unchanged |
| Grains reachable via `grain_at` | [0, 1, 2, 3, 4] — unchanged |
| `PolycrystalGrains.column_spacing_A` | 1.785 Å — unchanged |
| FCC 2 nm FOV atoms (region-honest path) | 1391 — unchanged |
| Sample registry loads | 13 samples |
| All `%%writefile` cells parse | 62/62 |
| Notebooks `nbformat`-valid | 3/3 |

### 9.5 Still open — the one item deliberately not applied

**Spot size and beamstop remain fixed pixel counts** (§8.4). `spot_sigma_px=2.5` and
`beamstop_radius_px=6.0` do not scale with the frame while spot positions do, so at 4096 the
spots render as near-pinpricks and the beamstop barely covers the direct beam. This is
pre-existing behaviour, and scaling it changes the appearance of every existing 1024 and
2048 pattern — a calibration decision that is yours. The two-line patch is in §8.4.


---

# PART D — the two abTEM notebooks

## 10. They did need changing

My earlier statement that these were unaffected was too narrow. It was based on
`abtem_diffraction.py` not appearing in the v3 diff — which is true of the module's *code*,
but says nothing about whether its **documentation** stayed correct, or whether the
notebooks' prose still described the twin accurately. Both had drifted.

### 10.1 F1 — `atoms_from_twin_sample` docstring is factually wrong on v3

The docstring states the twin "can return ~100k atoms in a ~110 A cube". That described v2,
where samples returned a fixed ~90k block regardless of the request. v3's region-honest
samples changed it. Measured, for the exact call the docstring is about
(`half_width_um=0.02`, `depth_nm=12`):

| | atoms from twin | lateral span | after the built-in crop |
|---|---|---|---|
| v2 samples | 92,597 | 100 Å | ~31,000 |
| v3 samples | 209,073 | 139 Å | ~36,500 |

So the claim understates the count by more than 2×. The practical impact is mild — the
`max_lateral_A` / `max_thickness_A` crop still bounds what reaches multislice, which grew
only ~18% — but the twin now generates ~2.3× more atoms and throws most away.

**This docstring is identical in every copy**, so it was stale in the two twin notebooks I
had already delivered as well. Corrected in all three.

**The better fix is a usage change, now documented.** Because v3 samples honour the request,
you can size the *request* instead of relying on the crop:

| `half_width_um` | v2 result | v3 result |
|---|---|---|
| 0.003 (60 Å) | 92,597 atoms, 100 Å span — request ignored | **36,481 atoms, 57 Å span — exact** |
| 0.005 (100 Å) | 92,597 atoms, 100 Å span | 108,841 atoms, 100 Å span — exact |
| 0.02 (400 Å) | 92,597 atoms, 100 Å span | 209,073 atoms, 139 Å — representative |

On v3, `half_width_um=0.003` yields a multislice-sized cell of real atoms directly, and the
crop becomes unnecessary. Both notebooks now say so.

### 10.2 F2 — the module notebook shipped an older `abtem_diffraction.py`

`STEM_Digital_Twin_abTEM_Diffraction_Module.ipynb` is meant to be the standalone home of the
module, but its copy was **15,344 chars against 17,865** in the twin notebooks, missing
`build_crystal_tilted()` and its `rot()` helper. The ReadMe lists `build_crystal_tilted` as
part of the public API, so the documented surface did not exist in the notebook that is
supposed to define it.

This is **pre-existing drift, not caused by v3** — the two copies were already out of sync in
the files you sent. Fixed by syncing the module notebook to the canonical version;
`abtem_diffraction.py` is now byte-identical across all three carriers (md5 `29b4a93cf4`).

### 10.3 F3 — Route B's prose predates the zone-axis and orientation defaults

Both notebooks offer `dislocation_crystal` as a Route B example. On v3 that sample defaults
to the **[111] zone axis**, so the dynamical pattern is a hexagonal projection rather than
the [001] square net the notebooks were written against, and `burgers_A` is now 2.525 Å.
`polycrystal_grains` likewise defaults to `random_zone_axes`. Both notebooks now note this,
and the appendix's commented bridge points at `zone_axis="001"` for the old behaviour.

### 10.4 F4 — resolution change does not reach them

Checked and **no edit needed**: neither notebook calls `set_resolution`, touches the twin
server, or hard-codes a detector size. They drive abTEM directly. The 1024/2048/4096 change
(§8) is confined to the twin.

### 10.5 Files

| File | Change |
|---|---|
| `STEM_Digital_Twin_abTEM_Diffraction_Module_v3.ipynb` | F2 module sync (+`build_crystal_tilted`), F1 docstring, F1/F3 Route B prose |
| `STEM_Digital_Twin_Appendix_abTEM_multislice_v3.ipynb` | F3 Route B prose + bridge-code comments |
| `STEM_Digital_Twin_Modular_final_w_PyJEM_with_abTEM_v3.ipynb` | F1 docstring (cell 94) |
| `STEM_Digital_Twin_Limits_Playground_v3.ipynb` | F1 docstring (cell 23) |

Verified: all four `nbformat`-valid, zero surviving "~100k atoms" claims, and
`abtem_diffraction.py` identical across its three carriers.

---

# PART E — full-frame coverage (no padding, any setting)

## 11. The two artifacts in Demo J, and what fixed them

Reported from Demo J: a dark border around the atomic-column square at 5000 kx, and, with
the stage tilted (a=5, b=10), shaded corners at 5000 kx plus a diagonal band at 20000 kx.
**Neither was physics.** Both were v3 regressions, from two protections dropped when
`_render_atomic_columns` was rewritten to consume `get_atoms_in_region`.

### 11.1 Cause 1 — the renderer assumed coverage it never checked

Atoms are mapped to pixels against the **requested** half-width:

```python
px = (pos[:, 0] + half_A) / fov_A * out_size
```

But `atoms_in_requested_box` silently returns a smaller **representative cube** whenever the
request exceeds its 250k budget — and the samples discard its `is_representative` flag, so
the renderer could not have known. At a 19 nm field with 100 nm working thickness the
request is ~3.2 M atoms, so the fallback fired:

| mag | frame half-width | atoms reach | frame filled |
|---|---|---|---|
| 5000 kx | 95 Å | 69.6 Å | **73.3%** → 13% dark margin per side |
| 20000 kx | 25 Å | 25.0 Å | 100% → no border |

That is exactly the pattern in the images: border at 5000 kx, none at 20000 kx. v2 had no
gap because it tiled `half_A * 1.15` itself — a deliberate 15% overfill.

### 11.2 Cause 2 — the render slab got 25× deeper

v2 called the renderer **without** `thickness_nm`, so it used the 4 nm default. v3 passes
the full working thickness. Projecting a slab of depth *d* at tilt θ shears atoms laterally
by *d*·tan θ:

| render slab | shear at 10° | vs the 25 Å frame half-width |
|---|---|---|
| v2, 40 Å | ±3.5 Å | 0.1× — invisible |
| v3, 1000 Å | ±88 Å | **3.5× — atoms leave the field** |

At 20000 kx tilted this threw **76% of atoms out of frame**, leaving the diagonal band, with
moiré where laterally-shifted depth slices superpose. At 5000 kx the block was the 139 Å
representative *cube*, so tilting rotated a finite cube into view — beveled silhouette,
projected thickness tapering at the leading and trailing edges. Correct rendering of a
finite cube; but a real lamella is laterally continuous, so the cube was the artifact.

### 11.3 The fix — size the request from the frame, then verify

`_render_atomic_columns` now:

1. **Caps the render depth** (`COLUMN_RENDER_MAX_DEPTH_A = 60 Å`). Columns repeat along the
   beam, so a deeper slab re-draws the same columns while shearing atoms out of frame. 60 Å
   still smears columns visibly under tilt. This is safe for brightness: the column image is
   normalised before blending, and thickness contrast comes from the volume projection, not
   from here.
2. **Adds a lateral margin** for the residual shear (`depth·tanθ`) plus an 8% overfill.
3. **Shrinks the depth further** if the request would still exceed the sample's budget, so
   the region-honest branch fires instead of the representative fallback.
4. **Verifies coverage instead of assuming it** — if the atoms still fall short, the field is
   filled from the local lattice rather than left unpainted.
5. **Maps pixels against the true frame half-width**, so column spacing on screen stays the
   physical spacing whichever path supplied the atoms.

The call site also computes the blend weight *first* and skips the render when it is zero —
at the resolvability threshold the blend was a no-op, so the most expensive case was doing
the most wasted work.

**Measured: zero unpainted border across all 27 combinations** of {1024, 2048, 4096} ×
{2000, 5000, 20000 kx} × {0°, (5°,10°), (15°,25°)}, and across all five crystalline samples
tilted and untilted.

### 11.4 A serious pre-existing bug this exposed: `tile_lattice_in_region`

Wider, thinner requests made the twin crawl — 5–10 s just to generate atoms. The cause was
in the cell bracket:

```python
max_cell_xy = int(np.ceil(2.0 * half_width_A / min(np.linalg.norm(a1[:2]),
                                                   np.linalg.norm(a2[:2]),
                                                   1.0))) + 2
```

That `1.0` inside `min()` **caps** the assumed cell spacing at 1 Å instead of flooring it.
For a 3.571 Å cell it understates the spacing 3.6×, and the bracket also used
`2 * half_width` where `half_width` was correct. Combined, the generated cell grid was
**76–85× larger than necessary** — 11.5 million cells to keep 203k atoms — with the surplus
discarded by the mask. Correct output, seconds of wasted allocation, on *every* call from
*every* sample, in v2 as well as v3.

Replaced with the exact bracket: a cell origin is `p = [i,j,k] @ A`, so `[i,j,k] = p @ inv(A)`
— evaluating the box's eight corners in fractional coordinates gives the tightest integer
range that can contribute, for any cell shape including non-orthogonal and rotated ones.

Verified **set-equal**, not merely same-count — the identical atoms come out:

| case | atoms | same atoms? | before | after | speedup |
|---|---|---|---|---|---|
| cubic 139 Å block | 228,267 | yes | 4,993 ms | 22 ms | **222×** |
| wide/thin 508 × 8.8 Å | 203,063 | yes | 5,947 ms | 32 ms | **188×** |
| narrow/deep 50 × 1000 Å | 235,901 | yes | 3,537 ms | 30 ms | **118×** |
| very wide 2258 × 4 Å | 2,400,337 | — | **OOM-killed** | 2,301 ms | — |

The last row is the point: the old bracket did not merely waste time, it could exhaust
memory outright. Non-orthogonal (HCP) and rotated (FCC[111]) cells were checked separately
and still fill their boxes.

This fix benefits diffraction and abTEM export too — every atom request in the twin goes
through this function.

### 11.5 What this does *not* change

- **Column spacing on screen is unchanged.** Pixel mapping still uses the true frame
  half-width; the fix changes which atoms are available, never their scale.
- **Brightness is unchanged.** The column image is normalised before blending.
- **Tilt still smears columns** — that was the point of the v3 rewrite and it survives; what
  no longer happens is atoms leaving the field.
- All earlier regression numbers still hold: 5529 atoms in a 4 nm FOV, 1.8028 Å mean strain,
  grain spreads 0.122 / 0.218 / 0.000, grains 0–4 reachable, 1391 FCC atoms at 2 nm.

### 11.6 One cost worth knowing

At 4096 px and very high magnification the probe-blur sigma becomes large in pixels — a
0.5 Å probe across a 5 nm field at 4096 px is genuinely 41 px wide — so `gaussian_filter`
dominates, at ~7.5 s per column render. That is correct physics, not a defect, and it is
inherent to the resolution rather than introduced here. At 1024 px the same view costs
~120 ms.

### 11.7 Files changed

| File | Change |
|---|---|
| all three twin notebooks, `stem_server_twisted_colab.py` | request sizing, coverage guarantee, true-frame mapping, zero-weight skip |
| all three twin notebooks, `samples/base.py` | `tile_lattice_in_region` exact cell bracket |

`nbformat`-valid, all `%%writefile` cells parse, R1/R2/R3 and sample smoke suites re-run
clean.
