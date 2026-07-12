# STEM Digital Twin — GUI Build Specification

A build-ready prompt/spec for a two-window GUI on top of the existing STEM digital-twin
server. Every control below maps to a **real** RPC on `MicroscopeControlClient` (portable
instrument control) or `SimulationHarness` (twin-only simulation state), so the GUI drives the
actual twin with no new backend work. Values, ranges, and defaults are taken from the current
build.

---

## 0. Architecture & how the GUI talks to the twin

The twin is a Twisted JSON-RPC server (netstring protocol, port 9094) already running in the
notebook. The GUI is a **client** that holds one `STEMClient` (which combines
`MicroscopeControlClient` + `SimulationHarness`) and calls its methods on user actions.

- **Recommended stack:** the twin runs in Colab, so the lowest-friction GUI is **ipywidgets**
  rendered in the notebook itself (no packaging, runs next to the server). If you want a
  standalone desktop app, **PyQt/PySide** or a **Dash/Streamlit** web app work too — the
  backend contract is identical; only the widget toolkit changes.
- **Golden rule for responsiveness:** every acquisition or sample-generation call can take from
  ~0.5 s (a 512-px image) to ~30 s (a 2048-px atomic-resolution frame, or generating a fresh
  sample volume). **Run all RPC calls on a worker thread** and post results back to the UI
  thread; never block the event loop. Show a spinner/"busy" state during calls.
- **Two clients, two roles — keep them visually separate in the UI:**
  - `MicroscopeControlClient` = things a *real microscope* also has (stage, beam, mode, FOV/mag,
    resolution, acquire). These belong in **Window 2**.
  - `SimulationHarness` = things only a *simulator* has (which sample, environment, thickness,
    drift/damage injection, reset). These belong in **Window 1**.

```python
from stem_client import STEMClient          # or MicroscopeControlClient + SimulationHarness
client  = STEMClient(host="127.0.0.1", port=9094, timeout=300)
control = client                            # portable control surface
sim     = client                            # simulation-harness surface
control.wait_until_ready(300)               # block until first sample volume is built
```

---

## WINDOW 1 — Sample Registration & Environment

This window **defines the specimen and the conditions it is observed under**, then loads it.
Nothing here exists on a real microscope except implicitly (it's the specimen you happened to
put in and the state of your column) — that's why it's the "simulation" window. Loading is the
commit action; it calls `sim.load_sample(...)` and (optionally) `sim.set_environment(...)`.

### 1.1 Sample selector (dropdown)

Populate from the registry. Show the human-readable `display_name`; keep the internal `name`
as the value. Current samples:

| internal name | display | configurable knobs (besides seed) |
|---|---|---|
| `fcc_single_crystal` | Fe (FCC, γ-austenite) | a_angstrom, atomic_number |
| `bcc_single_crystal` | Fe (BCC, α-ferrite) | a_angstrom, atomic_number |
| `hcp_single_crystal` | Mg (HCP) | a_angstrom, c_over_a, atomic_number |
| `polycrystal_grains` | Polycrystal (Fe FCC, few grains) | **n_grains (2–12)** |
| `dislocation_crystal` | Fe FCC with Edge Dislocations (many) | **n_dislocations (1–40)**, burgers_A |
| `amorphous_film` | Amorphous Film | atomic_number |
| `au_dispersed` | Au Nanoparticles (Dispersed) | **n_particles (1–50000)** |
| `au_clustered` | Au Nanoparticles (Clustered) | — |
| `au_bimodal` | Au Nanoparticles (Bimodal Size) | — |
| `au_on_substrate` | Au on Substrate (Catalyst) | **n_particles (0–50000)** |
| `core_shell` | Core-Shell Nanoparticles | **n_particles (0–20000)** |
| `shape_assembly` | Shape Assembly (synthetic) | — |
| `atomsk_polycrystal` | Atomsk Polycrystal (file-driven) | file_path, auto_fit, scale_factor |

### 1.2 Dynamic per-sample parameters (build controls from the schema)

**Do not hard-code the parameter controls.** Each sample exposes
`sample.meta.param_schema` — a dict of `{param: {type, min, max}}`. When the user picks a
sample, fetch its schema and render a control per parameter:

- `type: "int"` → integer spinbox / slider with the given `min`/`max`.
- `type: "float"` → float spinbox with `min`/`max` (step ~ (max−min)/100).
- `type: "bool"` → checkbox.
- `type: "str"` → text field (e.g. `atomsk_polycrystal.file_path`).

Pre-fill each control with the sample's current default (`sample.params[k]`).

The knobs users will most want, called out explicitly per your request:

- **Number of grains** — `polycrystal_grains.n_grains`, int **2–12** (default 4). More grains =
  more boundaries and more distinct diffraction orientations.
- **Number of dislocations** — `dislocation_crystal.n_dislocations`, int **1–40** (default 12).
  This is the "many dislocations" control; higher = more strain, more mosaic spread in
  diffraction. (Also expose `burgers_A`, the Burgers-vector magnitude, float 0.5–10 Å.)
- **Number of particles** — `au_dispersed.n_particles` (1–50000), `au_on_substrate` (0–50000),
  `core_shell` (0–20000). Particle count / loading.
- **Lattice constant / element** — `a_angstrom` (1–20 Å) and `atomic_number` (1–100) on the
  crystals; `c_over_a` (1.0–2.5) additionally on HCP.
- **Atomsk file** — `file_path` (str), `auto_fit` (bool), `scale_factor` (float). When
  `auto_fit=True` the structure is placed at true physical scale; note this to the user.

### 1.3 Seed field(s) — reproducibility, shown as labeled inputs

Every stochastic sample carries an integer **seed** (label it clearly, e.g. "Structure seed").
Same seed + same parameters ⇒ **bit-identical** sample, so users can explore variants and
return to any one exactly. Range is int `0 … 2147483647`.

- Most samples: the seed param is literally named `seed`.
- `dislocation_crystal`: the seed is `disl_seed` (label it "Dislocation seed").
- Show a small **"🎲 randomize"** button next to each seed that drops in a random int, **and
  always display the resulting number** so it can be written down / re-entered.
- **Also surface the thickness seed here** (see 1.5) — it is a *separate* seed from the
  structure seed, so label them distinctly: "Structure seed" vs "Thickness seed".

### 1.4 Volume resolution (advanced, optional)

`load_sample(..., D, H, W)` sets the voxel volume dimensions (default 64×768×768 for the
registry-built volume; per-load you typically pass e.g. D=40, H=256, W=256). Most users never
touch this; expose it under an "Advanced" expander with a note that **larger volumes take
longer to generate** (this is the "sample registry takes time" cost). Keep H=W.

### 1.5 Thickness selection (per your thickness workflow)

The specimen has a **total physical thickness** (100 nm). At load, the user chooses a **working
thickness** (the slab the beam images through) and a **thickness seed** that decides *where*
within the full 100 nm that slab sits — mirroring how real-specimen thickness varies and where
you land is somewhat arbitrary. Controls:

- **Working thickness (nm)** — slider **1 … total (100)**, default = total. Label: "how thick a
  slab the beam passes through". Thicker ⇒ more signal + more excited diffraction spots.
- **Thickness seed** — int spinbox, with the same randomize+display treatment as 1.3. Label it
  "Thickness seed" and add a read-out showing the resulting z-window, e.g. *"images 30 nm slab
  starting 44.6 nm into the 100 nm specimen"* (comes back from `get_thickness()` as
  `z_start_nm`).

Wire either at load time or after:
```python
sim.load_sample(name, params=params, D=40, H=256, W=256,
                thickness_nm=working_nm, thickness_seed=thickness_seed)
# or, to re-pick thickness without regenerating the sample (simulate navigating to a
# differently-thick region):
sim.set_thickness(thickness_nm=working_nm, thickness_seed=thickness_seed)
info = sim.get_thickness()   # {total_nm, working_nm, z_start_nm, seed} -> show z_start read-out
```

### 1.6 Environment definition (the "conditions" panel)

The environment bundles drift + beam damage + contamination + detector dose. Offer **two
modes**, side by side:

**(A) Preset picker** — a dropdown of the five named scenarios. Applying one calls
`sim.set_environment(name)`. Show a short description and the values it will set (below), so the
user sees what they're getting. Exact preset values in the current build:

| preset | drift vx,vy (px/s), jitter | damage | contamination | dwell µs / DQE / readout e⁻ | thickness override |
|---|---|---|---|---|---|
| `pristine` | 0, 0, 0 (off) | off | off | 20 / 0.9 / 1.0 | — |
| `beam_sensitive` | 2, 1, 0.3 | **on** (thresh 4e3 e⁻/Å², rate 0.7) | off | 10 / 0.8 / 1.5 | — |
| `contaminating` | 3, 2, 0.4 | off | **on** (rate 3.0) | 15 / 0.8 / 1.5 | — |
| `thick_drifting` | **12, 7, 1.0** | off | off | 6 / 0.7 / 2.5 | **90 nm** |
| `low_dose` | 4, 2, 0.5 | on (thresh 2.5e3, rate 0.8) | off | **2** / 0.75 / 2.0 | **25 nm** |

**(B) Custom / expert controls** — expose the underlying knobs directly so users can dial "how
much contamination or drift or anything is happening". These call `sim.set_drift(...)` and
`sim.set_specimen(...)` (both take keyword args; only pass the ones you expose):

- **Drift** (`sim.set_drift`):
  - `enabled` (checkbox) — master on/off.
  - `vx_px_per_s`, `vy_px_per_s` (float sliders, suggest 0–15) — drift velocity. This is the
    dominant "how much drift" control. (Reference: 12,7 = "thick_drifting" is strong.)
  - `line_jitter_px` (float slider, 0–2) — scan-line jitter amplitude.
  - `reset_accum` (button) — zero the accumulated drift offset (re-centres the view).
- **Beam damage** (`sim.set_specimen`):
  - `beam_damage_enabled` (checkbox).
  - `damage_dose_threshold` (float, e⁻/Å², suggest 1e3–1e4) — dose before damage onset; lower =
    more fragile specimen.
  - `damage_rate` (float, 0–2) — how fast contrast is lost past threshold; higher = faster damage.
- **Contamination** (`sim.set_specimen`):
  - `contamination_enabled` (checkbox).
  - `contamination_rate` (float, 0–5) — carbon build-up rate where the beam dwells; higher =
    faster brightening/darkening over successive frames.
- **Detector dose** (via `control.device_settings("haadf", ...)`):
  - `dwell_us` (float, 1–50) — per-pixel dwell; lower = noisier (dose-limited).
  - `dqe` (0–1), `readout_e` (float) — detector quality; expose under Advanced.
- **Reset specimen** (button) — `sim.reset_specimen()` clears accumulated damage/contamination
  maps (fresh area).

> Design tip: give each "how much" slider a qualitative scale label under it — e.g. drift
> velocity: *none · mild · moderate · severe* keyed to ~0 / 3 / 7 / 12 px/s — so users without a
> feel for the units still get intuitive control. Custom controls should **override** a preset
> if changed after one is selected (apply-on-change).

### 1.7 "Register / Load sample" button (commit)

On click, on a worker thread:
```python
sim.load_sample(name, params=collected_params, D=D, H=H, W=W,
                thickness_nm=working_nm, thickness_seed=thickness_seed)
sim.set_environment(preset_name)          # if a preset is chosen; else apply custom set_drift/set_specimen
# then optionally push custom overrides:
sim.set_drift(**custom_drift); sim.set_specimen(**custom_specimen)
```
Then refresh Window 2's read-outs. Show a busy indicator — sample generation can take seconds.
Surface any exception (e.g. bad atomsk file path) in a status line.

---

## WINDOW 2 — Microscope Control & Viewer

This is the "at-the-scope" window: the live image/pattern/spectrum plus the controls a real
operator uses. All calls here are on `MicroscopeControlClient` (portable — the same calls work
on a real backend later).

### 2.1 The viewer (central panel)

A single image canvas that shows the current acquisition, with a title strip showing mode,
FOV, mag, and resolution.

- **Acquire button** (and optional "Live" toggle that re-acquires every N ms — but keep N ≥ the
  frame time, and never overlap calls). Acquisition:
  - **IMG / DIFF:** `img = control.acquire_image("haadf")` → 2-D array → render (grayscale for
    IMG, an "inferno"-style colormap for DIFF). DIFF already has the direct beam removed and
    Bragg spots normalized, so display it directly.
  - **EELS:** `spec = control.acquire_spectrum(ev_min, ev_max, n_channels)` → **line plot**
    (energy-loss x-axis, log-y works well) with the returned `edges` marked as vertical lines.
- Show a **busy spinner** while acquiring; disable Acquire during a call.

### 2.2 Mode selector (radio / segmented control)

`control.set_mode(m)` with `m ∈ {"IMG", "DIFF", "EELS"}`. Switching mode should swap the viewer
render type (image vs image vs line plot) and reveal the mode-specific controls (2.6/2.7).

### 2.3 Stage controls (x, y, z, α, β) with limits

Five controls. **x/y/z are in metres** in the RPC, **α/β in degrees**. In the UI, present x/y/z
in **µm or mm** (convert on the way in/out) and α/β in **degrees**. Enforce the twin's hard
**safety limits** in the widgets (min/max) *and* handle the server's rejection:

| axis | UI unit | limit (RPC) | limit (UI) |
|---|---|---|---|
| x | µm | ±1.5e-3 m | ±1500 µm |
| y | µm | ±1.5e-3 m | ±1500 µm |
| z | µm | ±1.0e-3 m | ±1000 µm |
| α (a) | ° | ±30° | ±30° |
| β (b) | ° | ±30° | ±30° |

- Provide both **absolute** (set-to) and **relative** (nudge ±step) controls; a step-size field
  is handy. Call:
  ```python
  control.set_stage({"x": x_m, "y": y_m, "z": z_m, "a": a_deg, "b": b_deg}, relative=False)
  # or nudge:
  control.set_stage({"a": +step_deg}, relative=True)
  ```
- **The server rejects any move whose target exceeds a limit (nothing moves) and raises.** Catch
  that, keep the widget at the last valid value, and flash the reason in the status line. Clamp
  the widget ranges to the table above so users rarely hit it, but still handle the raise.
- α is the **horizontal** tilt axis, β the **vertical** tilt axis (perpendicular double-tilt
  holder) — you can label them that way. On refresh, read back with `control.get_stage()` →
  `[x, y, z, a, b]`.

### 2.4 FOV and Magnification (linked pair)

FOV and mag are two views of the same quantity: `mag = MAG_K / fov_metres`,
`MAG_K = 0.0944177811456`. Provide **both fields, linked** — editing one updates the other.

```python
control.set_magnification(mag)             # sets mag; server computes FOV
info = control.get_magnification()         # {"magnification", "field_of_view_um"}
# FOV-first UX: convert the typed FOV to a mag, then set it:
control.set_magnification(0.0944177811456 / (fov_um * 1e-6))
```
Show FOV in µm (or nm when < 1 µm) and mag in "kx" (mag/1000). Reasonable UI range: mag ~1 kx →
20 000 kx (FOV ~19 µm → ~5 nm). Higher mag ⇒ smaller FOV; at high mag the crystals show atomic
columns (below).

### 2.5 Resolution windows (discrete)

A segmented control / dropdown with the **fixed set 512 / 1024 / 2048** px (default 512):
```python
control.set_resolution(px)                 # px ∈ {512,1024,2048}; invalid raises
control.get_resolution()                   # {"resolution_px", "allowed":[512,1024,2048]}
```
Higher resolution ⇒ smaller pixel for the same FOV ⇒ atomic columns resolve at **lower**
magnification, but the frame is slower (512 ≈ 0.6 s; 2048 ≈ 30 s when rendering columns). Put a
small "(slower)" hint on 1024/2048 and always run acquisition off-thread.

### 2.6 Beam: current and voltage

`control.set_beam({...}, relative=False)` / `control.get_beam()`:

- **Probe current (pA)** — `current_pA`, suggest 1–1000 pA. Lower current = noisier (dose).
- **Accelerating voltage (kV)** — `voltage_kV`, typical set {80, 120, 200, 300}. Offer as a
  dropdown of standard values plus a free field.
- (`x`, `y` beam-shift also exist but are advanced; hide by default.)
- **Beam blank/disable** (safety, optional): the backends accept `set_beam(..., disabled=True)`;
  expose a "Blank beam" toggle if you want to mirror the safety interlock.

```python
control.set_beam({"current_pA": current, "voltage_kV": kv}, relative=False)
```

### 2.7 Diffraction controls + the **kinematical ⇄ abTEM toggle**

Show these only in DIFF mode.

- **Kinematical settings** (always available; `control.set_diffraction_settings(**kw)`):
  `aperture_um` (selected-area aperture), `depth_nm` (probed depth), `camera_length_mm`
  (pattern zoom), `beamstop_radius_px` (size of the removed direct-beam disk). Sensible defaults
  aperture_um=0.4, depth_nm=20.
- **Engine toggle — "Diffraction engine: [ Kinematical ⇄ abTEM ]"** (default **Kinematical**):
  - **Kinematical (default):** `control.acquire_image("haadf")` in DIFF mode — the fast built-in
    engine (~sub-second). This is the normal path.
  - **abTEM (dynamical):** when toggled on, **do not** call the server for the pattern. Instead
    compute it with the `abtem_diffraction` module on the **same sample's atoms**, off-thread:
    ```python
    from abtem_diffraction import AbtemDiffraction
    eng = AbtemDiffraction(energy_kev=voltage_kV)        # reuse one instance
    import samples
    s = samples.get_sample(current_sample_name)          # same sample as loaded
    atoms = eng.atoms_from_twin_sample(s, half_width_um=0.02, depth_nm=10,
                                       max_lateral_A=50, max_thickness_A=80)
    # apply the current stage tilt to the atoms (abTEM path is decoupled from the server):
    x,y,z,a,b = control.get_stage()
    atoms = AbtemDiffraction.build_crystal_tilted(...)   # for simple crystals, OR
    # AbtemDiffraction.tilted_atoms(atoms, tilt_deg_x=a, tilt_deg_y=b) for arbitrary samples
    dp = eng.saed(atoms, num_frozen_phonons=0)
    # render with the beam-stop-aware display so spots are visible:
    # (AbtemDiffraction.show clips the direct beam)
    ```
  - **UX for the toggle:** because abTEM takes seconds to tens of seconds, show a clear "computing
    (abTEM)…" state and consider a separate **"Compute dynamical pattern"** button rather than
    auto-refresh, so it isn't triggered on every little change. Add a small **"frozen phonons"**
    spinbox (0–16; >0 adds thermal-diffuse background, slower) for the abTEM path only.
  - **Important behavioral note to surface in a tooltip:** the abTEM path is *decoupled* from the
    server, so **stage α/β do not affect the abTEM pattern automatically** — the GUI must read
    the stage and rotate the atoms (as above). The kinematical path applies α/β on the server
    side automatically.
  - **Dependency note:** abTEM must be installed (`pip install abtem ase`), compatible with the
    twin's NumPy 2.x. If the import fails, grey out the toggle with a tooltip.

### 2.8 Autofocus (optional but nice)

A button → `control.autofocus("haadf", z_range_um=2.0, z_steps=9)`. Its success/failure depends
on the environment (it can diverge under `low_dose`/`beam_sensitive`), which makes a good demo of
the environment settings from Window 1. Show the returned best-z and score.

### 2.9 EELS controls (DIFF-sibling; show in EELS mode)

- Energy range `ev_min`, `ev_max` (defaults 0–1000 eV), `n_channels` (default 1024).
- Acquire → line plot; mark returned `edges` (label + onset_eV). The probe sits at one point
  (same geometry as one 4D-STEM position); the spectrum is a structured dummy — say so in a note.

---

## 3. Cross-cutting behaviours

### 3.1 Reproducibility panel (make seeds first-class)

Because the whole point is *explore-but-reproduce*, add a small always-visible **"Session seeds"**
read-out that shows, at a glance: structure seed, thickness seed, and (if used) environment name
+ any custom drift/damage/contamination values. Add **Copy** (dumps them as a small JSON blob)
and **Load** (re-applies a pasted blob) so an exact state can be shared or revisited. Everything
needed is already returned by `get_thickness()`, `get_drift()`, `get_specimen()`,
`get_environment()`, and the sample params.

### 3.2 Status / log strip

Mirror `sim.get_command_log(last_n=…)` in a collapsible panel so users can see the exact RPC
calls their clicks produced (great for turning a GUI session into a script later).

### 3.3 Threading & safety recap

- All `acquire_*`, `load_sample`, `set_resolution(2048)`, and abTEM calls → worker thread + busy
  state. Debounce sliders (apply on release, not on every tick).
- Respect and surface the stage safety raises; never let the UI think a rejected move succeeded
  — always reconcile against `get_stage()` after a move.
- Reuse one `AbtemDiffraction` instance; don't rebuild it per frame.

### 3.4 Suggested layout

- **Window 1 (Sample Registration):** left column = sample dropdown + dynamic param controls +
  seeds + thickness; right column = environment (preset picker on top, custom drift/damage/
  contamination expanders below); bottom = big **Register/Load** button + status.
- **Window 2 (Control & Viewer):** centre = viewer canvas + Acquire/Live; left rail = mode,
  stage (x/y/z/α/β with nudges), autofocus; right rail = FOV/mag, resolution, beam
  (current/voltage), and (in DIFF) diffraction settings + the Kinematical⇄abTEM toggle.

---

## 4. Minimal call map (quick reference)

```
Window 1 (SimulationHarness):
  load_sample(name, params, D,H,W, thickness_nm, thickness_seed)
  set_environment(name)                         # pristine|beam_sensitive|contaminating|thick_drifting|low_dose
  set_drift(enabled, vx_px_per_s, vy_px_per_s, line_jitter_px, reset_accum)
  set_specimen(beam_damage_enabled, damage_dose_threshold, damage_rate,
               contamination_enabled, contamination_rate)
  set_thickness(thickness_nm, thickness_seed) ; get_thickness()
  reset_specimen() ; get_drift() ; get_specimen() ; get_environment()

Window 2 (MicroscopeControlClient):
  set_mode("IMG"|"DIFF"|"EELS") ; get_mode()
  set_stage({x,y,z,a,b}, relative) ; get_stage()        # x/y/z metres, a/b degrees; limits ±1.5mm/±1.5mm/±1mm/±30°/±30°
  set_beam({current_pA, voltage_kV}, relative) ; get_beam()
  set_magnification(mag) ; get_magnification()          # MAG_K=0.0944177811456 ; mag=MAG_K/fov_m
  set_resolution(512|1024|2048) ; get_resolution()
  set_diffraction_settings(aperture_um, depth_nm, camera_length_mm, beamstop_radius_px)
  device_settings("haadf", size=, field_of_view_um=, dwell_us=, dqe=, readout_e=)
  acquire_image("haadf")                                # IMG or DIFF (kinematical)
  acquire_spectrum(ev_min, ev_max, n_channels)          # EELS
  autofocus("haadf", z_range_um, z_steps)

abTEM path (only when the DIFF engine toggle = abTEM):
  AbtemDiffraction(energy_kev).atoms_from_twin_sample(sample, ...) -> saed(...)
  # rotate atoms by current stage a,b (build_crystal_tilted / tilted_atoms) — server tilt does NOT apply here
