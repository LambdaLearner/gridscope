# STEM Digital Twin + GridScope — Consolidated Change Record

> **Rebuilt from the v4 record.** The previous version had grown to six appended parts
> describing changes on top of changes, so most of it documented code that later revisions
> deleted. This file states the **current state first**, keeps every measured number, and
> compresses the superseded material into §10.
>
> | Section | Contents | Status |
> |---|---|---|
> | §1–§4 | What the twin is now: physics, API, samples | current |
> | §5 | v4 → v5 migration ledger | current |
> | §6 | Verification — every number measured by running the code | current |
> | §7 | GridScope: what the server already did, what is left | partly done |
> | §8 | Open items | current |
> | §9 | Patch index | current |
> | §10 | Compressed history — what was tried and superseded | history |
> | §11 | Defects introduced during this work and how they were caught | process |

---

# PART A — CURRENT STATE

## 1. What the twin is

A **kinematical** STEM simulator with a vendor-neutral instrument-control interface. That
sentence is the entire scope, and v5 spent most of its effort making it true by *removing*
things rather than adding them.

Samples, imaging, kinematical diffraction, thickness selection, drift, contamination, depth
of field, feature-finding, magnification and stage safety, and the backend abstraction.
Seconds per frame, no heavy dependencies, CPU-only in Colab.

One interface underpins the specimen:

```python
positions_A, Z = sample.get_atoms_in_region(cx_um, cy_um, half_width_um, depth_nm)
```

and one underpins the image:

```python
proj = project_with_dof(vol, dX, dY, cx, cy, z0, ...)     # reads (D, H, W), nothing else
```

Anything needing atoms goes through the first; anything needing an image through the second.
Neither has a per-sample branch, so a change lands on all thirteen samples at once.

### 1.1 The render path, in order

| Stage | What it does |
|---|---|
| Window | absolute world position from stage + accumulated drift (§3.2) |
| `project_with_dof` | rigid-rotation tilt + per-depth-slice defocus, coverage-normalised |
| Thickness | scale projected mass by working/total thickness, then `thickness_contrast` |
| `make_psf` + `convolve2d_fft` | probe: aperture, Cs, uniform-defocus broadening |
| `feature_scale_nm` | resolution limit tied to the sample's finest real detail |
| Atomic columns | crystalline samples at high magnification only |
| Contamination | additive brightening from the accumulated dose map |
| Noise | Poisson dose model, or the legacy gaussian path |

## 2. Physics

### 2.1 Tilt is a rigid rotation

The specimen is rotated about Y by β then about X by α, and the projection integrates along
the lab beam axis:

```
x_lab = xs*cb - zs*sb
y_lab = ys*ca - (xs*sb + zs*cb)*sa
z_lab = ys*sa + (xs*sb + zs*cb)*ca        <- distance along the beam
```

Rendering inverts the first two per specimen slice; both stay **affine** in the output
coordinates, so it is one bilinear resample per slice.

`rz = nm_per_vox_z / nm_per_px_xy` converts depth voxels to in-plane pixels. The voxel grid
is strongly anisotropic — ~2.5 nm deep against ~78 nm wide — and that ratio is exactly what
the old shear model omitted.

### 2.2 Depth of field needs no separate tilt term

`z_lab` above **is** the beam distance, so

```
dz_nm = nm_per_px_xy * z_lab + defocus_nm
```

covers the specimen's own depth, the uniform defocus, and the tilted focal plane in one
expression. Sigma is `|dz_nm| * (max_sigma_px / focus_gain_nm)`, clipped.

Slices are binned into `DOF_N_LAYERS` blur buckets. Untilted, sigma is one number per slice
and slices sharing a bucket are summed before resampling — when every slice lands in one
bucket this collapses to a single resample, which is what keeps 2048/4096 px affordable.
Tilted, sigma varies per pixel *and* per slice, so each slice is split across buckets by
mask and composited with **coverage normalisation** (`Σ G(L_k) / Σ G(M_k) × D`): blurring a
masked fragment alone would bleed its cut edges into dark seams.

### 2.3 Contamination is the only degradation mechanism

Beam damage was removed. Contamination survives because it is **geometric** — it leaves a
footprint in a definite place that a workflow has to notice and navigate around — rather
than a contrast decay curve with no spatial story.

`contamination_rate` is a percentage knob: 100 nominal, 200 twice as fast, 0 off.
Accumulation is `inc × (rate/100)` in e⁻/Å²; saturation is `1 − exp(−c / CONTAM_DOSE_SCALE)`
with the scale a single named constant, 7.7 e⁻/Å².

**Observable window.** Below ~0.3 e⁻/Å² per frame nothing accumulates visibly; above ~20 the
first frame already saturates. At 80 pA / 20 µs that is roughly **5–30 µm FOV at 1024 px**,
shifting down 4× in FOV per doubling of resolution.

## 3. API

### 3.1 Acquisition conditions are explicit

There are no named environment presets. A demo states its conditions as numbers:

| Call | Sets |
|---|---|
| `set_drift(vx_nm_per_s=, vy_nm_per_s=, line_jitter_px=, enabled=, reset_accum=)` | stage drift |
| `set_contamination(enabled=, rate=)` | contamination |
| `set_noise(dwell_us=, dqe=, readout_e=, use_dose_model=, noise_sigma=)` | dose and detector noise |
| `set_autofocus_limits(min_contrast=)` | AF non-convergence threshold |
| `reset_specimen()` | clear the accumulated contamination map |

A preset name told you nothing about what was actually set. What you read at the call site is
now what the twin is set to.

### 3.2 Roaming: every sample, one edge behaviour

Earlier builds had **two** edge behaviours for what is physically one motion — a stage move
wrapped modulo the volume while accumulated drift clamped at a margin. A workflow correcting
drift by issuing stage moves saw them disagree at the boundary.

The window is now tracked in absolute world pixels for every sample, with two mechanisms:

| `roaming_mode` | Mechanism | Repeats? | Used by |
|---|---|---|---|
| `"periodic"` (default) | the volume is one tile of a repeating specimen; the **sampler** wraps. No regeneration, no copy | yes, period `generation_range_um` | 12 samples |
| `"world"` | the sample implements `generate_volume_at()` over a position hash; the server re-tiles | **no** | `shape_assembly` |

`supports_roaming = False` remains available for a specimen that is genuinely finite and
where showing a continuation would be a lie.

Honest limitation of `"periodic"`: the specimen repeats every 20 µm by default. At a
realistic 1 nm/s drift that is ~5.5 hours before anything recurs, but it is periodicity, not
an infinite specimen.

## 4. Samples

Thirteen, all roaming. `shape_assembly` is the one built for underspecified tasks:

- **Cell-hashed world generation.** The world is partitioned into cells and each cell's RNG
  derives from `hash(seed, cell_y, cell_x)`, so a cell holds the same shapes no matter who
  asks or from which window.
- **`num_shapes` retained** as the caller-facing knob, converted internally to a per-cell
  Poisson mean. The mean is calibrated once against a **reference window at world origin** —
  never the caller's window, or density would vary with where you were looking.
- **`z_spread`** scatters shape centres through `±z_spread·(D/2 − rz)`, bounded by each
  shape's own half-height so nothing clips. `z_spread = 0` reproduces the flat v4 sample
  exactly, making it an A/B switch rather than a silent reinterpretation.
- **`depth_fraction`** keeps its exact v4 meaning and default.

## 5. v4 → v5 ledger

### 5.1 Physics

| Area | v4 | v5 |
|---|---|---|
| Depth of field | blur **after** projection; depth reconstructed from tilt angles, i.e. a flat-specimen assumption | blurred **per depth slice inside** the projection, from each sample's own voxel z axis |
| Stage tilt | shear, `tan(angle) × 0.35` | **rigid rotation**; the shear was 10.9× too strong |
| Foreshortening | absent | tracks cos(β) to ~1% |
| Tilt/DOF coupling | separate `tan(α)` wedge beside the shear — two descriptions of one rotation | one expression; the wedge is gone |
| Beam damage | modelled | **removed** |
| Contamination | present but ~1000× too slow to see | recalibrated; percentage knob, 100 = nominal |
| Layer compositing | mask-select + 0.5 px smear to hide seams | coverage-normalised sum; no seams, no smear |
| PSF kernel cap | `max_radius = 24` px — defocus response saturated at 0.087 µm on a 1 µm field | `96`, ~4× more usable defocus range |
| Border sampling | interpolation weights from **clamped** indices → a one-pixel dark rim | weights from unclamped positions |

### 5.2 API

| v4 | v5 |
|---|---|
| `set_environment(...)`, `get_environment()` | **removed** → four explicit setters (§3.1) |
| `set_specimen(beam_damage_enabled=, …)` | `set_contamination(enabled=, rate=)` |
| `set_mode("IMG" / "DIFF" / "EELS")` | `"IMG"` / `"DIFF"` only |
| `acquire_spectrum(...)` | removed → Appendix B |
| `tilt_strength_px_per_slice` | deleted |
| — | `Sample.supports_roaming`, `Sample.roaming_mode`, `generate_volume_at(...)` |
| — | `use_analytic_particles` optics flag (Appendix E only) |
| — | `set_drift(max_dt_s=...)` — the per-frame elapsed-time cap is now settable |

Unchanged: `dof_focus_gain_nm`, `dof_max_sigma_px`, the RPC protocol, `MicroscopeBackend`
and every vendor adapter.

### 5.3 Samples

| | v4 | v5 |
|---|---|---|
| `shape_assembly` placement | rejection sampling into a fixed field | cell-hashed world, unbounded and deterministic |
| `shape_assembly` depth | every shape on the mid-plane | `z_spread` scatters through the slab |
| `num_shapes` | honoured by retrying | calibrated Poisson mean; exact to 40, packing-limited at 67 |
| Drift at the specimen edge | clamped | every sample roams |
| `atoms_in_particles` | dropped each particle's z | carries it, so imaging and diffraction describe one specimen |

### 5.4 Files

| v4 | v5 |
|---|---|
| `STEM_Digital_Twin_Clean_Kinematical_v4` | `STEM_Digital_Twin_Kinematical_v5` |
| `..._Limits_Playground_v4` | `Demo_Limits_and_Bounds_v5` |
| `Additional_Shape_Assembly_2_edit` | `Demo_ShapeAssembly_v5` (later merged with Appendix E — §12) |
| `..._abTEM_Diffraction_Module_v4` + `..._Appendix_abTEM_multislice_v4` | merged → `Appendix_A_abTEM_Multislice` |
| §7 of the main notebook | `Appendix_C_Portability_Backends` |
| §8 of the main notebook | `Appendix_D_Ambiguous_Workflow` |
| — | `Appendix_B_EELS` |
| `..._Modular_final_w_PyJEM_with_abTEM_v4` | **deleted** — see §5.5 |

Every notebook writes a **byte-identical** `samples/` package, server and client, verified by
md5. They differ only in what they demonstrate.

### 5.5 Why the PyJEM notebook was deleted

It shared 69 of 86 cells with the main notebook and contained nothing PyJEM-specific: its
`microscope_backend.py` was byte-identical to Appendix C's, and it had zero PyJEM mentions
outside that file. What it *did* still carry was a stale **"Example 3 — Dose-budget study on
a beam-sensitive specimen"** built on the beam-damage model that v5 removed, plus §7 and §8
which had already been split into Appendices C and D — and it was missing Demo P and Demo Q.
It was not a variant; it was an un-migrated copy, and keeping it meant shipping a demo of a
mechanism that no longer exists.

## 6. Verification

Every number below comes from running the code, not from reading it.

### 6.1 Tilt

Two vertical bars 100 volume-px apart, blur disabled to isolate geometry:

| β | separation | ratio to 0° | cos(β) | error |
|---:|---:|---:|---:|---:|
| 0° | 493.00 px | 1.0000 | 1.0000 | 0.00% |
| 10° | 489.00 px | 0.9919 | 0.9848 | 0.72% |
| 20° | 469.00 px | 0.9513 | 0.9397 | 1.24% |
| 30° | 432.00 px | 0.8763 | 0.8660 | 1.18% |

The shear model gave ratio 1.000 at every angle. Against exact rigid rotation on the twin's
geometry it was also **10.9× too large** in lateral shift, at every angle.

### 6.2 Depth of field

Autofocus sharpness peaks at z=0, monotonic either side, `converged=True`,
`best_z_um_relative=0.0`, curve contrast **0.812**.

Tilt band, `amorphous_film`, α=30°, row-band sharpness as % of the sharpest band:

| | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | contrast |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| flat | 100.0 | 70.0 | 90.1 | 92.5 | 96.2 | 97.5 | 79.4 | 78.3 | 1.53× |
| α=30° | 45.7 | 32.5 | 51.6 | **100.0** | 85.8 | 64.0 | 27.8 | 39.0 | **3.60×** |

The band sits mid-field, which is where `z_lab = ys·sinα` vanishes.

Depth-resolved focus, `shape_assembly` at `dof_focus_gain_nm=60`: stage z of
−0.10 / −0.05 / 0 / +0.05 / +0.10 µm gives sharpness 4.60e5 / 5.85e5 / **9.14e5** / 6.03e5 /
4.60e5 — the in-focus plane moves *through* the specimen.

Propagation with **zero sample edits**: `amorphous_film` sharpness ratio 0.224 and
`au_dispersed` 0.665 between z=0 and z=0.3 µm.

### 6.3 Contamination

Demo H4 conditions, 4 µm / 128 px / 60 µs / 400 pA:

| frames | old fraction | new |
|---|---:|---:|
| 1 | 0.0002 | 0.329 |
| 6 | 0.0012 | 0.752 |
| 12 | 0.0025 | 0.925 |

Small-field mean 26262 → 41232 (**+57.0 %**); wide-view centre/edge ratio 0.989 → **1.868**.

Dose versus resolution, 20 µm FOV, 80 pA, 20 µs:

| res | nm/px | e⁻/Å² per frame | after 5 | brighter |
|---:|---:|---:|---:|---:|
| 1024 | 19.53 | 0.262 | 1.57 | +13.1 % |
| 2048 | 9.77 | 1.047 | 6.28 | +34.4 % |

Dose ratio **4.00×** for a 2× resolution change — exactly the resolution² law.

### 6.4 Roaming

`shape_assembly` (world mode), stage x driven 0 → 8 → 80 → 800 → 8 → 0 µm: revisits
**bit-identical**, 0 µm and 800 µm genuinely different, volume origin re-tiling to 10240 px.

All twelve periodic samples: **no clamp at any offset**, and the frame at an offset of one
volume width is identical to the frame at zero, i.e. the period is exact.

Before this change, non-roaming samples clamped after `(generation_range_um − fov_um)/2` of
travel — measured 9.1 / 7.5 / 5.0 / 2.5 µm at 2 / 5 / 10 / 15 µm FOV, against predictions of
9.0 / 7.5 / 5.0 / 2.5. At a 20 µm field there was **no** headroom at all.

### 6.5 Drift — realistic, and sub-pixel at low magnification

The nm/s → px/s conversion is exact: 1 nm/s is `sample_px_per_um/1000` volume px/s,
measured 0.01280 against a predicted 0.01280. Drift **is** applied — six frames at 2 nm/s
produce a different frame each time.

What decides whether you *see* it is the output pixel size, `fov_nm / out_size`:

| FOV (µm) | nm per output px | px/s at 2 nm/s | s for 1 px | s for 10 px |
|---:|---:|---:|---:|---:|
| 30.0 | 58.594 | 0.0341 | 29.3 | 293.0 |
| 5.0 | 9.766 | 0.2048 | 4.9 | 48.8 |
| 1.0 | 1.953 | 1.0240 | 1.0 | 9.8 |
| 0.2 | 0.391 | 5.1200 | 0.2 | 2.0 |

512 px frames. Six back-to-back acquisitions at a 5 µm field take ~1 s and accumulate
1.88 nm = **0.19 output pixels** — sub-pixel, which is why drift can look switched off when
it is working correctly. Visibility is bought with **magnification and time**, not with rate:
real stage drift is 0.1–5 nm/s and anything above that is a mechanical fault, not a setting.

Two demo defects fixed as a result. The `Demo_Limits_and_Bounds` drift slider had
`vy value=15` against its own `max=10` — an invalid default the widget silently clamped —
and a `vx` default of 10 nm/s, five times a realistic rate. Rates are now capped at 5 nm/s
with defaults of 2.0/1.0, the demo takes an explicit FOV rather than a magnification, and it
prints the expected shift in output pixels with a warning when that is below one pixel. The
one remaining 5.8 nm/s condition in the notebooks was lowered to 2.5 nm/s.

### 6.6 Defocus saturates — twice, and one of them is an artifact

Lowering stage z stops making the image worse past a point, and there are **two**
independent reasons, only one of which is intentional.

**1. Depth of field.** Sigma is `|dz_nm| × (dof_max_sigma_px / dof_focus_gain_nm)`, clipped
at `dof_max_sigma_px`. So the DOF contribution saturates at `|z| = dof_focus_gain_nm`,
350 nm by default. FOV-independent, tunable with `set_optics`, and deliberate.

**2. PSF kernel truncation.** `make_psf` capped its kernel at `max_radius = 24` px. PSF sigma
grows as `0.18 × defocus_nm / pixel_nm` — expressed in **pixels** — so the cap bites *sooner
at higher magnification*, where a pixel is smaller. It saturated at `|z| ≈ 44 × pixel_nm`:

| FOV | nm per px | PSF saturates at | usable range, old cap | new cap (96) |
|---|---:|---:|---:|---:|
| 5.0 µm | 9.77 | 0.43 µm | −41 % | **−89 %** |
| 1.0 µm | 1.95 | **0.087 µm** | −6.7 % | **−34.8 %** |
| 0.2 µm | 0.39 | **0.017 µm** | −4.3 % | **−15.1 %** |

At a 1 µm field the whole defocus response was spent within 87 nm of focus, after which
lowering z did essentially nothing — a 6.7 % total sharpness change across ±20 µm of stage
travel. That is the "defocus stops getting worse" behaviour, and it is an implementation
artifact, not physics.

`max_radius` raised 24 → 96, extending the usable range ~4×. Autofocus still converges at
both 5 µm and 1 µm fields (`converged=True`, correct `best_z_um_relative=−1.50` from a
+1.5 µm start).

**Correction to an earlier claim.** This was first written up as "a bigger kernel is nearly
free, because convolution is FFT-based." Measured, that is wrong: on a 512² frame a
193×193 kernel takes **78.2 ms** against 17.0 ms for 49×49, a 4.6× slowdown. What rescues
the change is not that the kernel is free but that `r = min(max_radius, ceil(3σ))` — the cap
only binds once σ is large, so the cost is paid **only when the frame is already badly
defocused**:

| \|z\| | σ (px) | radius at cap 24 | at cap 96 | ms at 24 | ms at 96 |
|---:|---:|---:|---:|---:|---:|
| 0 | 1.4 | 5 | 5 | 18.4 | 18.4 |
| 0.05 µm | 4.8 | 15 | 15 | 16.2 | 16.9 |
| 0.1 µm | 9.3 | 24 | 28 | 20.7 | 38.1 |
| 1.0 µm | 92.2 | 24 | 96 | 18.0 | 82.2 |

In-focus rendering is untouched. The extra cost lands on defocused frames, which in practice
means autofocus sweeps — a sweep of 13 steps pays roughly an extra 0.5 s.

### 6.7 Drift over a long gap needs `max_dt_s` raised

`sim.drift["max_dt_s"]` caps the elapsed time a **single** frame may accrue drift over,
defaulting to 2 s so an idle notebook cannot teleport the field on the next acquisition.
It was not settable through the API, which made a long deliberate wait silently useless:

| `max_dt_s` | drift accrued over a 100 s gap | measured image shift |
|---:|---:|---:|
| 2.0 (default) | 3.00 nm | **0.0 px** |
| 120.0 | 150.00 nm | **78.9 px** |

`set_drift(max_dt_s=...)` added. Demo H2 now uses a 1 µm field (1.95 nm/px), a 100 s gap and
`max_dt_s = 120`, and prints the expected shift alongside the measured one. Measured lands
about 12 % below the ideal (154 nm against 175 nm) — the cross-correlation peak is
integer-pixel and line jitter blurs it — so the demo shows both numbers rather than claiming
agreement.

### 6.8 Demo Q: implicit specimen state, and what the DOF knob means

The α=30° panel of Demo Q inherited `z_spread = 1.0` and `dof_focus_gain_nm = 60` from the
block above it without stating either. So the focus variation across that panel came from
**two** sources — the tilt band and the features' own depths — and there was no way to tell
them apart from one image. `shape_assembly` measures 4.04× band contrast even untilted, on
its internal depth spread alone, against 1.53× for `amorphous_film`.

Rewritten so every panel sets its own specimen and optics, and the tilt figure now has
**three** panels: flat specimen untilted, flat specimen at α=30° (the band alone), and
scattered specimen at α=30° (band plus internal depth).

**Specimen parameterisation.** `depth_fraction` moved from the default 0.5 to **0.15**:

| `depth_fraction` | feature thickness | `z_spread=1` centres | occupied |
|---:|---:|---:|---:|
| 0.50 (default) | 50 nm | ±25 nm | 100 nm |
| 0.15 (Demo Q) | 15 nm | ±42 nm | 100 nm |

At 0.5 each feature is half the foil thickness and they nearly fill it — an agglomerate.
At 0.15 you get 15 nm features scattered through ~85 nm of a 100 nm foil, which is a
plausible dispersed-nanoparticle specimen. The sample default is unchanged; only Demo Q
overrides it.

**`dof_focus_gain_nm` is a convergence semi-angle in disguise.** STEM depth of field is
roughly `2λ/α²`, and at 200 kV (λ = 2.508 pm):

| α (mrad) | DOF (nm) |
|---:|---:|
| 4 | 313 |
| 5 | 201 |
| 10 | 50 |
| 20 | 12.5 |

So the default **350 nm ≈ 3.8 mrad** (uncorrected, small probe angle) and **60 nm ≈ 9 mrad**
(a modern corrected probe). Demo Q's comment previously described 60 as "turned down only to
make it visible", which undersold it — 60 is the more representative instrument of the two.
The demo now prints the equivalent angle so the number is interpretable rather than magic.

### 6.8b `z_spread` and `dof_focus_gain_nm` are a ratio, not alternatives

Measured after the above: correlation of the local-sharpness map between the two ends of a z
sweep, 60 shapes at a 15 µm field. ≈1 means the same regions are sharp at both ends, i.e. no
depth resolution at all.

| `depth_fraction` | `z_spread` | gain | Δz | σ spread | sharp-map corr | resolved? |
|---:|---:|---:|---:|---:|---:|---|
| 0.5 | 0.0 | 350 | 0 nm | 0.00 | 1.000 | no |
| 0.5 | 1.0 | 350 | 50 nm | 1.29 | 0.999 | no |
| 0.1 | 1.0 | 350 | 90 nm | 2.31 | 0.992 | no |
| 0.5 | 1.0 | 60 | 50 nm | 7.50 | 0.878 | partly |
| 0.1 | 1.0 | 60 | 90 nm | 9.00 | **0.628** | yes |
| 0.1 | 1.0 | 25 | 90 nm | 9.00 | 0.775 | yes |

`z_spread` alone can never do it: it is a fraction capped at 1.0 and the foil is 100 nm,
while the default 350 nm gain is a depth of field larger than the whole specimen. The visible
effect is `Δz × dof_max_sigma_px / dof_focus_gain_nm` — a ratio.

> **Depth range cannot be bought by thickening the specimen.** `total_nm` comes from the
> sample class attribute; `params={"thickness_nm": 500}` is **silently ignored** and
> `set_thickness` clamps working thickness to total. Logged as O23.

### 6.8c Depth-of-field recalibration: gain 350 → 2000, tilt-scaled ceiling

Both knobs changed on visual grounds, and it is worth being explicit about how they
interact, because they **multiply**:

```
sigma = |dz_nm| * (dof_max_sigma_px / dof_focus_gain_nm)
```

| | old | new (untilted) | new (α=β=30°) |
|---|---:|---:|---:|
| `dof_focus_gain_nm` | 350 | **2000** | 2000 |
| `dof_max_sigma_px` | 9 | 9 | **127** |
| blur growth rate | 0.026 px/nm | 0.0045 px/nm | **0.064 px/nm** |
| band half-width to saturation, α=30° | 0.70 µm | 4.00 µm | 2.83 µm (both axes) |

**What the change buys is not a wider band.** Raising the gain alone widens it 5.7×, but
scaling the ceiling with tilt more than takes that back — at α=β=30° the blur gradient is
2.5× *steeper* than the old setting. What changes is the **depth of the peripheral blur**:
the ceiling goes from 9 px to 127 px, so everything outside the band is genuinely wiped
rather than mildly softened. Measured along the diagonal at a 15 µm field, band-to-periphery
sharpness contrast rises from 1.4× untilted to ~4400× at α=β=30°.

That is why it reads as convincing. The old setting looked like a sharp stripe on an
otherwise-fine image, which is not what an out-of-focus region looks like.

`dof_focus_gain_nm` is now **2000.0** in `SimMicroscope.optics`, in `project_with_dof`'s
signature, and in both `.get()` fallbacks. `dof_max_sigma_px` stays 9.0 as a default, since a
default has no tilt to scale against; demos set it per frame.

**A floor was added to the proposed rule.** `3*sqrt(alpha^2 + beta^2)` gives **0** at zero
tilt, which switches depth of field off entirely on an untilted specimen and would hide the
specimen's own depth — the thing `z_spread` exists to show. Demo Q uses
`max(9.0, 3*sqrt(a^2+b^2))`; the floor binds only below ~3° of total tilt, so it never
interferes with the tilted case the rule was written for.

Autofocus still converges at 30 / 5 / 1 µm fields with the new default gain
(`converged=True`, correct sign and magnitude, curve contrast 3.51 / 4.39 / 0.40).

**Demo Q** now also compares `z_spread` 0 vs 1 **untilted and at α=β=30°** as a 2×2: a row
isolates the tilt, a column isolates the specimen. With both axes tilted the sharp band runs
**diagonally**, because the beam-distance term is `ys·sinα + xs·sinβ` and the in-focus locus
is perpendicular to the combined tilt axis.

### 6.9 The tilt band is a depth-of-field width

Half-width to full blur is closed-form:

```
half-width  =  dof_focus_gain_nm / (1000 * sin(alpha))   micrometres
```

At α=30° the default 350 nm gives 0.70 µm against a 2.5 µm half-field, which is why the band
is narrow and obvious. Measured band contrast on `amorphous_film` (max/min row-band
sharpness — noisy on a textured sample, but the endpoints are clean):

| setting | band contrast |
|---|---:|
| `gain=150` | 11.43× |
| `gain=350` (default) | 3.60× |
| `gain=5000` | 1.95× |
| `dof_max_sigma_px = 0` | **1.42×** |
| untilted, for reference | 1.53× |

To cover a whole field: `gain ≥ (FOV/2) × 1000 × sin(alpha)` — 1250 nm at 5 µm and 30°. To
remove the band entirely: `dof_max_sigma_px = 0`.

That second switch removes **all** depth of field, not just the tilt part, and there is no
switch that keeps it on the depth axis while removing it across the field. The tilted focal
plane and the specimen's own thickness are one expression in `project_with_dof` (§2.2);
separating them would reintroduce the two-descriptions-of-one-rotation problem that §10
records. On a real instrument the same knob is the convergence angle.

### 6.10 shape_assembly counts

| requested | in-field | old sampler |
|---:|---:|---:|
| 5 | 5 | 5 |
| 15 | 15 | 15 |
| 40 | 40 | 40 |
| 80 | 67 | — |
| 120 | 67 | 46 |

67 is the genuine hard-disk packing limit for default sizes in a 256² field.

### 6.11 Appendix E — what voxelisation costs

`shape_assembly`, 49 shapes over 49 nm, `dof_focus_gain_nm=60`:

| quantity | value |
|---|---|
| continuous sigma | 0.016 – 3.794 px, **49 distinct values** |
| bucketed sigma | **4 distinct values** |
| mean error | **0.314 px** |
| max error | **0.630 px** |
| image correlation, no tilt / α=20° | **0.9668 / 0.9836** |

Sub-pixel — which is why the twin keeps the voxel path and this stays an appendix.

### 6.12 Notebooks

| Notebook | Result |
|---|---|
| `STEM_Digital_Twin_Kinematical_v5` | 30 cells, **0 errors** |
| `Demo_Limits_and_Bounds_v5` | 9 cells, **0 errors** |
| `Demo_ShapeAssembly_DepthOfField_v5` | 6 cells, **0 errors** |
| `Appendix_B_EELS` | 8 cells, **0 errors**; server reports `mode: EELS` |
| `Appendix_C_Portability_Backends` | 1 cell, **0 errors**; 4/4 backend signatures match |
| `Appendix_D_Ambiguous_Workflow` | 6 cells, **0 errors** |
| `Appendix_E_Analytic_Particle_Physics` | 8 cells, **0 errors** |

Plus: zero syntax errors in any non-magic code cell; server, client, `base.py` and
`shape_assembly.py` byte-identical everywhere by md5.

---

# PART B — GRIDSCOPE

## 7. What the server already did, and what is left

The original G1/G2 asks were *UI* changes. The server has since gone further than requested,
which changes what GridScope has to do.

| Item | Original ask | Now |
|---|---|---|
| **G1** Remove environment presets | hide the picker; keep `set_environment` on the server | **`set_environment` is deleted.** GridScope cannot call it. The custom bar is no longer optional — it is the only interface |
| **G2** Remove EELS and abTEM | remove the panels | **removed server-side.** The app can only expose what the server has; the panel removal is still a GridScope-side task |
| **G3** Parameter boundaries | open | **still open, and now more urgent** — §7.2 |

### 7.1 The bar GridScope must build

| Group | RPC | Knobs |
|---|---|---|
| Drift | `sim.set_drift(...)` | `enabled`, `vx_nm_per_s`, `vy_nm_per_s`, `line_jitter_px`, `reset_accum` |
| Contamination | `sim.set_contamination(...)` | `enabled`, `rate` (percentage, 100 = nominal) |
| Noise / dose | `sim.set_noise(...)` | `dwell_us`, `dqe`, `readout_e`, `use_dose_model` |
| Autofocus | `control.set_autofocus_limits(...)` | `min_contrast` |
| Reset | `sim.reset_specimen()` | clears the contamination map |

The beam-damage group from the original spec is gone. Use the **physical nm/s** drift
interface, not the legacy px/s one.

### 7.2 Why boundaries matter more now

The presets were doing two jobs: convenience, **and implicitly guaranteeing that every value
was a sane, mutually-consistent combination**. With them deleted rather than merely hidden,
every number arrives from a user-typed field and there is no fallback.

Measured against a live server — each call made, not assumed:

| Call | Out-of-range input | Server response |
|---|---|---|
| `set_stage` | `z = +2 mm` (limit ±1 mm) | **rejected**, `ValueError` |
| `set_stage` | `a = 45°` (limit ±30°) | **rejected**, `ValueError` |
| `set_resolution` | `3000` | **rejected**, lists allowed set |
| `set_mode` | `"SEM"` | **rejected** |
| `set_thickness` | `5000 nm` vs 100 nm total | **silently clamped** |
| `set_beam` | `current_pA = −50` | **accepted** |
| `set_beam` | `voltage_kV = 0`, `1e6` | **accepted** |
| `set_magnification` | `0` | **`ZeroDivisionError`** (crash, not validation) |
| `set_magnification` | `−5000` | **accepted** → FOV −18.88 µm, and a frame still renders |
| `device_settings` | `size = 333` | **accepted**, bypassing `ALLOWED_RESOLUTIONS` |
| `device_settings` | `dqe = 50`, `readout_e = −3`, `dwell_us = 0` | **accepted** |
| `set_drift` | `vx_nm_per_s = 1e6` | **accepted** |
| `set_diffraction_settings` | `camera_length_mm = −100` | **accepted** |
| `set_optics` | `cs_mm = −10`, `dof_max_sigma_px = 500` | **accepted** |

**None of the knobs the new bar will expose is bounds-checked by the server.** Enforce
min/max on the widget *and* clamp on the GridScope side before the RPC, so a pasted value
cannot bypass a slider's range.

> One correction to the original G3 write-up: it listed `set_specimen(damage_rate=−5)` as
> accepted. That call no longer exists — the whole damage group went with it.

---

# PART C — HISTORY AND PROCESS

## 8. Open items

| # | Item | Owner |
|---|---|---|
| O12 | `CONTAM_DOSE_SCALE = 7.7 e⁻/Å²` calibrated for visibility, not measured against real deposition rates | Twin |
| O13 | Contamination brightens but adds no diffuse background to DIFF, though a carbon overlayer would | Twin |
| O15 | Server-side parameter validation is nearly absent (§7.2) | Twin |
| O17 | The Poisson-mean calibration runs up to 6 probe generations on first use of a parameter set; cached, but the first `load_sample` pays it | Twin |
| O18 | Stage tilt is capped at ±30°, so foreshortening beyond cos(30°) = 0.866 is untested | Twin |
| O22 | Drift visibility is FOV-dependent by physics, not by bug: at a 30 µm field 2 nm/s needs ~5 minutes for 10 px of shift. Demos must pick magnification deliberately | Twin |
| O19 | Notebook outputs predate the v5 physics and are stale | docs |
| O20 | **Crystalline samples saturate.** `fcc`/`bcc`/`hcp`/`dislocation_crystal` render a uniform 60000 with zero variance at every FOV above ~10 nm; lattice contrast appears only once `_render_atomic_columns` takes over. Reproduced identically on the pre-roaming build, so pre-existing, not caused by any v5 change | Twin |
| O23 | Specimen `total_nm` is fixed by the sample class and cannot be raised via `load_sample(params=...)` or `set_thickness`; the param is silently ignored rather than rejected | Twin |
| O21 | `"periodic"` roaming repeats every `generation_range_um`. Extending `"world"` to the other twelve samples would make them non-repeating, at the cost of rewriting each generator in world coordinates | Twin |
| B10 | Bounds for the DOF tunables in the GridScope bar | GridScope |

**Closed:** O1, O5, O6 (autofocus `best_z` inconsistency — a symptom of the duplicate tilt
description), O7 (`tilt_strength_px_per_slice`), O10, O11 (`beam_sensitive`/`low_dose` preset
names), O14 server half, O16 (all samples roam).

## 9. Patch index

| Patch file | Covers | Status |
|---|---|---|
| `dof_tilt_changes.patch` | `depth_of_field_blur()` added to the server | **history** — documents a function later deleted |
| `dof_depth_resolved_changes.patch` | `project_with_dof()` replaces it; `base.py` z-carry; `shape_assembly` z-spread | history |
| `scope_reduction_changes.patch` | server: beam damage removed, EELS removed, contamination recalibrated | current |
| `client_eels_removal.patch` | `stem_client.py`: the **correct** EELS removal (§11) | current |
| `dof_recalibration.patch` | `dof_focus_gain_nm` 350 → 2000, tilt-scaled ceiling, `set_drift(max_dt_s=)`, PSF cap 24 → 96 | current |
| `rotation_and_conditions.patch` | true-rotation tilt, explicit condition setters, roaming | current |
| `universal_roaming.patch` | wrapping sampler, absolute-world window, roaming for all samples | current |

Notebook restructuring is not expressed as a patch — diffing `.ipynb` JSON produces noise
rather than signal. §5.4 carries the file inventory instead.

## 10. Compressed history

What earlier revisions did, and why each was superseded. The code described here **exists
nowhere**; this section is the record of how the render path arrived at §2.

**Uniform PSF only (pre-v4).** `make_psf` built one defocus PSF applied to the whole frame.
A uniform PSF cannot represent a tilted specimen, so tilt produced foreshortening but no
focus gradient.

**`depth_of_field_blur()` (v4).** A per-pixel blur applied to the already-projected image,
adapted from a layered-Gaussian reference script. Two deliberate improvements over that
reference at the time: depth summed as **signed** z offsets rather than a `sqrt(dx²+dy²)`
magnitude (which cannot distinguish over- from under-focus), and normalisation by
`focus_gain_nm` rather than by the frame's own maximum (which made the blur scale-free).
*Superseded because* acting after projection means the z axis has been summed away, so the
function had to reconstruct depth from the tilt angles alone — which assumes a flat specimen.
Invisible on a uniform slab, wrong on anything with structure through depth.

**`project_with_dof` with a shear (v5 interim).** Moved the blur inside the projection loop,
where z still exists. Correct in principle and still the current design. *But* it tilted by
shearing each slice with a hand-tuned `0.35` factor and carried a separate `tan(α)` wedge for
the focus gradient — two descriptions of one rotation. Superseded by §2.1.

**Beam damage (v4).** A cumulative-dose model that attenuated signal past a critical dose,
with an autofocus sweep that could corrupt its own sharpness curve on beam-sensitive
specimens. Removed: a contrast-decay curve with no spatial story, where contamination does
the same pedagogical job and leaves a navigable footprint.

**EELS (v4).** `acquire_spectrum` returning a structured but non-quantitative spectrum —
plasmon from mean Z, tabulated edge onsets. Removed from the twin because inside it the
spectrum invited being read as a physics model; the acquisition geometry and API surface are
preserved in `Appendix_B_EELS`, spliced into the server source at runtime.

**abTEM / py4DSTEM in-twin (v4).** Real physics, wrong place: slow, GPU-hungry, and pins
`numpy<2`. Moved to `Appendix_A_abTEM_Multislice`. This also closed a standing hazard — with
no engine toggle in the twin there is no longer any way to have two sources of truth for
specimen tilt in one window.

**Particle-list projector (reference script stages 2–4).** `apply_tilt`,
`project_and_defocus`, `composite_blur_layers`. The **model** was right and is the reason
§2.1 exists. The **implementation** could not be used: it operates on analytic particles, and
thirteen samples produce voxel volumes. It lives in `Appendix_E` as a fidelity reference,
measured in §6.11.

## 11. Defects introduced during this work

Recorded because they were self-inflicted, and because four of six share one cause.

| # | Defect | How it was caught |
|---|---|---|
| 1 | **`stem_client.py` lost 66 lines instead of 10.** An index-span cut from the EELS comment to the specimen-degradation comment also took `autofocus`, `close`, the entire `class SimulationHarness` header, `load_sample`, `set_environment`, and the thickness methods. The file still *parsed*, because the orphaned bodies were valid at the previous class's indentation | user report: `NameError: name 'SimulationHarness' is not defined` |
| 2 | **Appendix B's monkey-patch could not reach the server.** Patching `STEMServer` in the notebook kernel only works when the server runs in-process; one notebook launches it with `subprocess.Popen` | notebook execution sweep |
| 3 | **Appendix D imported `TwinBackend` without writing `microscope_backend.py`** — that cell had gone to Appendix C in the split | notebook execution sweep |
| 4 | **The dose-vs-resolution demo measured saturated noise.** Still written for beam damage, printing "% darker"; against contamination at 0.1 µm FOV both cases had accumulated >62 000 e⁻/Å², so both were fully saturated and the comparison reported −0.6 % "brighter" | reading the output rather than the exit code |
| 5 | **Preset expansion broke indentation.** A three-line replacement inserted at an indented call site | compiling every non-magic code cell |
| 6 | **Demo cells leaked instrument state.** A tilt-band demo added to the main notebook ended with the stage still at α=30°, `use_dose_model=0`, and a different sample loaded. `set_noise()` writes only the keys you pass, so the dose model persisted for the rest of the notebook: every later frame roughly **doubled** in brightness and clipped at 65535 (`fcc_single_crystal` mean 32423 → 62477). Demo O and §10 Example 1 looked wrong; everything before the leak looked fine, which is what made it findable | user report: "samples look really weird in imaging condition" |
| 7 | **The state-leak check never ran.** After defect 6 the notebook sweep was made to assert, after every cell, that the stage was untilted — and it reported `NONE` every time. `get_stage()` returns a **list** `[x,y,z,a,b]`, not a dict, so `st.get("a")` raised `AttributeError`, a bare `except Exception: pass` swallowed it, and the assertion was skipped silently. Every "STATE LEAKS: NONE" line reported up to that point was worthless. Fixed to handle both shapes, with the tilt read deliberately **not** wrapped in try/except; it immediately found a real leak (`a=30 b=30`) that the static regex audit had also missed, because that cell passes a dict *variable* to `set_stage` rather than a literal | the leak was found only after the check was repaired |
| 8 | **`set_optics` silently dropped the analytic flag.** It whitelists its keys, so both projectors returned byte-identical frames — correlation exactly `1.0000`, which reads as "perfect agreement" | the result being *too* good |

**Common cause in 1, 2, 5, 7: a mechanical edit that did not respect the structure it was
editing.** Every removal is now an exact-string replacement with an assertion *plus* a
positive check that named survivors are still present; every code cell in every notebook is
compiled; and every notebook is materialised into an isolated directory, given a real server,
and executed cell by cell.

**Lesson from 4, 6, 7 and 8:** a green exit code is not verification. All three ran without
error and produced output that was wrong in a way only *looking at it* would reveal — a
saturated image, a suspiciously perfect correlation, a comparison of two saturated frames.

**Defect 6 has its own lesson: notebook cells share one instrument.** A cell that changes
stage tilt, optics or the dose model and does not restore it corrupts everything downstream,
and the corruption appears far from its cause. Every state-changing demo now ends with an
explicit restore, and the notebook sweep asserts after **every** cell that the stage is
untilted — currently `STATE LEAKS AFTER A CELL: NONE` across 30 executed cells — and the check now
reports **how many cells it actually inspected** (26 of 30), because defect 7 was a check
that silently inspected none of them.


## 12. Shape-assembly material consolidated; Demo Q made sample-agnostic

**Demo Q no longer touches a sample parameter.** It previously drove the depth-of-field
demonstration with `z_spread`, `depth_fraction` and `num_shapes`, which exist only on
`shape_assembly` — so the demo did not transfer. Changing `SAMPLE` to `au_dispersed`
produced two bit-identical panels (`max|diff| = 0`), because `load_sample` **silently
accepts unknown parameters** and echoes them back in `get_current_sample()["params"]`,
making them look as if they had taken effect. That silent acceptance is a validation gap
and belongs with O15.

The demo is now driven only by `set_optics(dof_focus_gain_nm=...)` and
`set_stage(z, a, b)` — server-side controls that apply identically to all thirteen samples.

> **The premise is worth stating precisely.** Microscope-physics parameters were *already*
> universal: one `project_with_dof` reads the `(D, H, W)` volume every sample produces, and
> `dof_focus_gain_nm`, `dof_max_sigma_px`, stage z and tilt live on the server. What differs
> per sample is **specimen structure**, and that has always been true — `au_dispersed` has
> thirteen structure parameters, `fcc_single_crystal` six. `z_spread` is one of those, not a
> microscope setting. Reverting `shape_assembly` to its v4 form would remove one knob while
> leaving every other sample's untouched, and would break the byte-identical-base invariant
> if only some notebooks reverted.
>
> For the record, v4's `shape_assembly` *does* drop into the current server unchanged: it
> boots, roams (inheriting `roaming_mode="periodic"` from the base class), and renders IMG
> and DIFF. It loses `z_spread` (all shapes on the mid-plane, 0 nm depth spread), world
> roaming, and `_shape_records`, so the analytic projector degrades to unavailable.

**Two notebooks merged into one.** `Demo_ShapeAssembly_DepthOfField_v5` and
`Appendix_E_Analytic_Particle_Physics` shared **27 of their ~45 cells** — the entire
build/boot/connect stack, duplicated — while telling one continuous story about a single
sample. Now `Demo_ShapeAssembly_v5.ipynb`, 47 cells: the sample and its parameters, the
`z_spread` depth behaviour, tilt-band control, the analytic-projector splice, and the
quantisation-cost measurement. Verified: 10 cells ran, 0 errors, correlation 0.9668 / 0.9836,
mean quantisation error 0.314 px — unchanged from before the merge.

**FOV guidance instead of a formula.** A first version of the agnostic demo computed the
field from the band geometry, `FOV = 8·gain/(1000·sin α)`. Measured, that gave 0.96 µm, which
is *worse* than a fixed 4 µm for the gain and z sweeps:

| FOV | `au_dispersed` gain sweep / z sweep | `shape_assembly` |
|---:|---|---|
| 1 µm | −3.1 % / 2.9 % | −7.1 % / 11.7 % |
| 2 µm | −3.8 % / 3.0 % | −5.9 % / 8.5 % |
| 4 µm | **−8.8 % / 9.4 %** | **−13.9 % / 18.4 %** |

The formula optimised band width while ignoring whether the field held enough structure to
blur. Replaced with a measured default of 4 µm and the table above in a comment.


## 13. Separation of concerns: microscope vs specimen

The main notebook now demonstrates **only microscope controls**. Not one demo cell sets a
sample parameter, so nothing in it can be read as implying that a knob on one specimen
extends to the others.

| Was | Now |
|---|---|
| Demo Q drove depth of field with `z_spread`, `depth_fraction`, `num_shapes` | driven by `set_optics` and `set_stage` only; `SAMPLE` at the top can be any of the thirteen |
| Demo Q's markdown compared per-sample parameter sets in a table | one line pointing at the shape_assembly notebook |
| Demo I swept `num_shapes`, `min_size`, `max_size`, `aspect_*` | **moved** to `Demo_ShapeAssembly_v5` as Part 1a |
| Demo D passed `params={}` per panel | argument removed |
| Demo I's magnification sweep passed `num_shapes=30` | defaults only |
| Example 2 passed `n_grains=4, seed=7` | defaults only (`n_grains=4` already *was* the default) |

**One deliberate exception.** Section 9 still passes `params={"file_path": ...}` to
`atomsk_polycrystal`. That is a loader argument, not a physics knob — the section exists to
show how to load your own structure file, and without a path it has nothing to load.

### 13.1 `z_spread` documented as a specimen property

It is kept, and it is a legitimate tunable. Three checks supported that: nothing
auto-generates GUI widgets from `param_schema` (every reference is inside the sample files
themselves), so it costs no knob; per-sample parameter counts already range from 6
(`fcc_single_crystal`) to 22 (`au_bimodal`), so 13 is unremarkable; and shape_assembly is the
best-schema'd sample of the thirteen, at 12 of 13 bounded.

What did change is how it is described. It was documented as "`z_spread = 0` reproduces v4
exactly" — true, and useful as a regression check, but it reads as a leftover compatibility
flag. It is now documented as what it physically means:

> Fraction of the available slab depth over which feature **centres** are distributed. `1.0`
> spreads them through the foil, as for particles in a matrix; `0.0` puts every feature on
> the mid-plane, as for a drop-cast monolayer on a support.

That is a real specimen degree of freedom no other sample can express — the others all
hardcode "distributed through the volume". Worth stating plainly, because the earlier
justification here ("it is the same category as `au_dispersed`'s `rz_max`") was loose:
`depth_fraction` is the true analogue of `rz_max`, since both set a feature's z *extent*.
`z_spread` sets the *distribution of centres*, and is the only knob of its kind.

The v4-equivalence fact stays recorded in §6 with its measured numbers, where it belongs.
