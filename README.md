# GridScope

**AI-Powered STEM Digital Twin for Automated Microscopy**

---

## Overview

GridScope is an AI-powered automation platform for Scanning Transmission Electron Microscopy (STEM) that bridges the gap between experimental design and instrument execution. Researchers describe imaging objectives in natural language—such as *"acquire a 5×5 grid at 3 µm spacing"* or *"explore tilt angles from 0° to 30°"*—and receive executable Python scripts validated against a physics-based Digital Twin (v5 kinematical core, ported from `Digital_twin_revised_v6/STEM_Digital_Twin_Kinematical_v5.ipynb`; see `Digital_twin_revised_v6/STEM_Digital_Twin_and_GridScope_CHANGELOG.md` for the physics and API record).

### The control / simulation split

The system keeps two surfaces strictly apart, so what you test here deploys there:

- **Microscope control** (`/api/microscope`, `MicroscopeControlClient`) — every
  operation has a real-instrument counterpart: stage (with soft safety limits),
  beam, IMG/DIFF modes, magnification↔FOV, discrete resolution windows
  (1024/2048/4096 px), detectors, image acquisition, autofocus (with a
  settable acceptance threshold). Generated scripts use **only** this surface.
- **Simulation** (`/api/simulation`, `SimulationHarness`) — twin-only test
  scaffolding with no real-HW equivalent: the sample registry and registration,
  acquisition conditions set as explicit numbers (drift in nm/s, contamination
  as % of nominal, detector noise/dose), and specimen working-thickness
  selection. There are no named environment presets.

### Key Features

| Feature | Description |
|---------|-------------|
| **Natural Language Interface** | Describe experiments in plain English, get executable code |
| **STEM Digital Twin (v6+)** | Unified diffraction from atomic positions; specimen realism; thickness workflow |
| **13-Sample Registry** | Fe FCC/BCC and Mg HCP crystals, polycrystals, dislocation fields, amorphous films, Au nanoparticle variants, core-shell, shape assemblies — all with schema-driven parameters and reproducibility seeds |
| **Sample Registration** | Register a sample before imaging — like inserting a holder |
| **Thickness Workflow** | Choose a working slab (1–100 nm) and a thickness seed deciding where in the specimen it sits |
| **Explicit Acquisition Conditions** | No presets: drift (nm/s + idle-time cap), contamination (% of nominal), detector noise (dwell/DQE/readout/dose model), autofocus threshold — every value user-set, bounded by a server-published limits endpoint |
| **Realistic Physics Units** | Drift in physical nm/s (wall-clock time, settable idle-jump guard); contamination driven by real electron dose (e⁻/Å², depends on FOV × resolution × current × dwell) with a saturating-exponential footprint |
| **Live Mode + Contamination Meter** | Continuous adaptive acquisition (the way to watch drift) and an accumulated-exposure read-out with saturation fraction |
| **32-bit TIFF Export** | One-click download of the most-recent frame as quantitative float TIFF with embedded ImageJ-readable metadata |
| **v5 Physics** | Rigid-rotation stage tilt with cos-law foreshortening, depth-resolved depth of field inside the projection, universal roaming (periodic wrap or hash-generated world) |
| **Stage Safety Limits** | ±1.5 mm (x/y), ±1 mm (z), ±30° (tilt); out-of-range moves rejected |
| **Session Seeds** | Copy/Load the exact state (sample, params, seeds, thickness, acquisition conditions) as JSON |
| **Sandboxed Execution** | Generated scripts run server-side in a subprocess — the exact code you would deploy |

---

## Quick Start

> **First time on a new machine?** Follow the step-by-step guide in
> **[SETUP.md](SETUP.md)** — it covers prerequisites and troubleshooting.

### Prerequisites

- Node.js ≥ 18.x
- Python ≥ 3.10
- OpenAI API Key (optional — template generation works without it)

### Installation

```bash
# Clone and install frontend
git clone <repository-url>
cd Gridscope
npm install

# Install backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure environment
cp env.example .env
# Add your OPENAI_API_KEY to .env
```

### Running

Open three terminals:

```bash
# Terminal 1: Digital Twin Server
cd backend && python run_digital_twin.py

# Terminal 2: Backend API
cd backend && python run.py

# Terminal 3: Frontend
npm run dev
```

Access the application at `http://localhost:5173`

---

### Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| Frontend | React, TypeScript, Tailwind | Sample settings, microscope controls, AI chat, execution panel |
| Backend | FastAPI, Python | Control/simulation routing, sandboxed script runner, LLM orchestration |
| Digital Twin | Twisted JSON-RPC (`backend/app/digital_twin/`) | STEM physics simulation (v6) |
| AI Agent | OpenAI GPT-4 | Natural language to portable Python code |

---

## Usage

### 1. Sample & Conditions (first tab)

Simulation-only configuration — nothing here exists on a real instrument:

- **Sample registry**: pick one of 13 samples; parameter controls are built
  from each sample's `param_schema` (n_grains, n_dislocations, n_particles,
  lattice constants, …) and pre-filled with its defaults
- **Seeds**: structure/dislocation seeds with 🎲 randomize — the value stays
  visible, and same seed + same params reproduces the sample bit-identically
- **Thickness**: working-slab slider (1–100 nm) + thickness seed, with a
  read-out of where the slab sits in the specimen
- **Register / Load**: builds the specimen volume and resets degradation
  history. The microscope is disabled until a sample is registered.
- **Acquisition conditions**: explicit, always-visible controls — drift
  (enabled, vx/vy nm/s, jitter, idle-time cap), contamination (enabled,
  rate as % of nominal), detector noise (dwell, DQE, readout, dose model),
  autofocus min-contrast. What you set is exactly what the twin runs with;
  bounds come from `GET /api/simulation/limits`.
- **Fresh specimen**: clear accumulated contamination

### 2. Microscope (second tab)

The portable control surface — every action maps to a real instrument:

- **Mode Toggle**: Imaging ↔ Diffraction (diffraction computed from
  atoms, 1–5 s/frame)
- **Live Mode**: continuous adaptive acquisition (~300 ms cadence, never
  overlapping) — drift advances with real wall-clock time, so this is how
  you watch it; contamination accumulates per frame
- **Resolution**: 1024 / 2048 / 4096 px windows (higher = finer detail, slower; 4096 is offline-capture only)
- **Stage Control**: X/Y moves; rejected moves show the twin's safety-limit message
- **Focus (z)**: live read-out with fine (±0.25 µm) and coarse (±25 µm) steps —
  fine steps visibly change sharpness (manual companion to Autofocus)
- **Tilt Control**: α/β within ±30°
- **Save TIFF**: downloads the most-recent frame as 32-bit float TIFF with the
  acquisition context embedded (mode, sample, mag, resolution, thickness, tilt)
- **Contamination meter**: accumulated e⁻/Å² under the beam and % saturated
- **Field of View / Magnification**: linked field pair (mag = k / FOV)
- **Diffraction**: aperture / depth / camera length / beamstop settings
- **Beam Settings**: Voltage (60–300 kV) and Current (5–200 pA)
- **Autofocus**: can legitimately fail to converge — the UI reports why

### 3. AI Assistant + Execution Output

Enter natural language prompts:

```
"Take a 5x5 grid of images spaced 3 micrometers apart"
"Tilt from 0 to 20 degrees in steps of 5 and acquire at each angle"
"Switch to diffraction mode and acquire a pattern"
```

Generated scripts embed only `MicroscopeControlClient` and run **server-side
in a sandboxed subprocess** — logs and acquired frames stream live into the
execution panel. One run at a time: UI controls are read-only while a script
owns the instrument.

---

## Digital Twin Capabilities (v6)

- Diffraction computed directly from atomic positions in the illuminated
  region (crystals → spots, polycrystals → rings, amorphous → diffuse halos)
- Poisson-dose noise model, probe PSF with defocus and aberrations
- Mechanical drift (between- and intra-frame) and geometric contamination
- Rigid-rotation stage tilt (cos-law foreshortening) with depth-resolved
  depth of field applied per depth slice inside the projection
- Universal roaming: the stage can drive indefinitely — twelve samples wrap
  periodically, `shape_assembly` generates a deterministic unbounded world
- Inherent length scales: raise magnification to resolve each sample's features
- Stage soft limits enforced server-side; a rejected move does not move the stage

### Stage Parameters

| Parameter | Range | Units |
|-----------|-------|-------|
| X, Y position | ±1.5 | mm |
| Z (focus) | ±1.0 | mm |
| α, β (tilt) | ±30 | degrees |

---

### REST Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/microscope/session` | GET | Polled snapshot: state + sample + run + log |
| `/api/microscope/limits` | GET | Stage soft limits |
| `/api/microscope/stage` | GET/POST | Stage position (400 on limit rejection) |
| `/api/microscope/acquire` | POST | Acquire frame (IMG/DIFF, PNG payload) |
| `/api/microscope/resolution` | GET/POST | Discrete acquisition windows (1024/2048/4096) |
| `/api/microscope/diffraction` | GET/POST | Kinematical diffraction settings |
| `/api/microscope/capture.tiff` | GET | Download the most-recent frame as 32-bit TIFF (404 before first acquire) |
| `/api/microscope/autofocus` | POST | Autofocus (reports `converged`) |
| `/api/simulation/samples` | GET | Sample registry (incl. `param_schema` + defaults) |
| `/api/simulation/sample/register` | POST | Register the active sample (params, volume, thickness) |
| `/api/simulation/thickness` | GET/POST | Working-thickness selection (409 without a sample) |
| `/api/simulation/limits` | GET | Bounds for every free-form condition field |
| `/api/simulation/drift` | GET/POST | Drift (nm/s, jitter, idle-time cap) |
| `/api/simulation/contamination` | POST | Contamination (enabled, % of nominal) |
| `/api/simulation/noise` | POST | Detector noise / dose parameters |
| `/api/simulation/autofocus-limits` | POST | Autofocus acceptance threshold |
| `/api/execute/run` | POST | Run a script sandboxed (SSE stream) |
| `/api/chat` | POST | AI assistant |
| `/api/code/generate` | POST | Generate portable Python code |

---

## Tests

```bash
# Backend (twin physics, routes, sandbox runner, spec-drift guards)
cd backend && venv/bin/python -m pytest

# Frontend (API error parsing, both windows, SSE client)
npm test -- --run

# Types
npm run typecheck
```
