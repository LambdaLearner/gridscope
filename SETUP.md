# GridScope — Setup Guide (fresh machine)

Step-by-step instructions to get GridScope running from nothing. No prior
setup assumed. Takes ~10 minutes plus download time.

---

## 1. Prerequisites

Install these first if you don't have them:

| Tool | Version | Check with | Get it from |
|------|---------|------------|-------------|
| **Git** | any recent | `git --version` | https://git-scm.com |
| **Node.js** | ≥ 18 | `node --version` | https://nodejs.org (LTS is fine) |
| **Python** | 3.10 or newer | `python3 --version` (Windows: `python --version`) | https://python.org |

> **Note your Python version** — it matters for one optional dependency
> (abTEM) in step 4.

---

## 2. Clone the repository

```bash
git clone https://github.com/LambdaLearner/gridscope.git
cd gridscope
```

---

## 3. Backend setup (Python)

```bash
cd backend

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate          # macOS / Linux
# venv\Scripts\activate           # Windows (PowerShell or cmd)

# Install all required dependencies
pip install -r requirements.txt
```

This installs FastAPI, Twisted (the digital-twin server), numpy/scipy, ASE,
Pillow, tifffile (TIFF export), pytest, and the OpenAI client.

---

## 4. Optional: abTEM (dynamical diffraction)

The app works fully without this — the Kinematical⇄abTEM toggle in the
Diffraction panel is simply greyed out. To enable dynamical (multislice)
diffraction patterns, the version depends on your Python:

```bash
# Python 3.10:
pip install abtem==1.0.6

# Python 3.11 or newer:
pip install abtem
```

> Why the pin: abtem 1.0.8+ requires Python ≥ 3.11, and abtem ≤ 1.0.5
> breaks on NumPy 2. If you hit a numpy-related import error after
> installing abtem, run `pip install "numpy<2"`.

---

## 5. Optional: OpenAI API key (AI assistant)

The AI chat assistant needs an OpenAI key. Everything else (manual
microscope control, samples, environments, script execution) works without
one.

```bash
# still inside backend/
cp env.example .env
# then edit .env and set:  OPENAI_API_KEY=sk-...
```

---

## 6. Frontend setup (Node)

```bash
cd ..            # back to the repo root
npm install
```

---

## 7. Run it — three terminals

All three processes must run at the same time. Open three terminals in the
repo root.

**Terminal 1 — Digital Twin server** (the simulated microscope, port 9094):

```bash
cd backend
source venv/bin/activate          # Windows: venv\Scripts\activate
python run_digital_twin.py
```

Wait until you see: `[DT] Server ready (no sample registered).`

**Terminal 2 — Backend API** (FastAPI, port 8000):

```bash
cd backend
source venv/bin/activate          # Windows: venv\Scripts\activate
python run.py
```

**Terminal 3 — Frontend** (Vite dev server, port 5173):

```bash
npm run dev
```

Then open **http://localhost:5173** in your browser.

---

## 8. First steps in the app

The microscope is disabled until a specimen is registered (like a real
instrument with no holder inserted):

1. Go to the **Sample & Environment** tab.
2. Pick a sample (e.g. *Fe (FCC, gamma-austenite)* or *Au Nanoparticles*),
   adjust its parameters/seeds/working thickness if you like.
3. Choose a simulation environment (start with `pristine`).
4. Click **Register / Load sample** (takes a few seconds — it builds the
   specimen volume).
5. Switch to the **Microscope** tab and click **Acquire**.

Things worth trying:

- **Live mode** with the `thick_drifting` environment — watch the field
  drift in real time.
- **Zoom in** (raise magnification / shrink FOV below ~50 nm) on a crystal
  to resolve atomic columns; raise **Resolution** to 1024/2048 px.
- **Diffraction mode**, then tilt α/β to navigate zone axes. If abTEM is
  installed, toggle the engine and hit **Compute dynamical pattern**.
- **EELS mode** — the core-loss edges match the elements under the probe.
- **beam_sensitive** environment at small FOV — watch the **dose meter**
  climb and the image fade past the critical dose.
- **TIFF** button — downloads the current frame as a quantitative 32-bit
  TIFF with the acquisition context embedded (opens in ImageJ/Fiji).

---

## 9. Verify the install (optional)

```bash
# Backend tests (~2 min; the 2 abTEM tests auto-skip if abtem isn't installed)
cd backend && venv/bin/python -m pytest        # Windows: venv\Scripts\python -m pytest

# Frontend tests (~5 s)
npx vitest run
```

Everything should pass on a clean checkout.

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| Twin fails with `Address already in use` (port 9094) | An old twin is still running: `lsof -ti :9094 \| xargs kill` (macOS/Linux) or find and kill the python process (Windows), then restart. **A stale twin serves stale code** — always restart it after pulling changes. |
| Frontend shows **Disconnected** | Make sure Terminals 1 AND 2 are both running; the UI talks to the API on `localhost:8000`, which talks to the twin on `9094`. |
| `ModuleNotFoundError` in the backend | The venv isn't activated, or you're using a different Python. Re-run the activate command; check `which python` points into `backend/venv`. |
| abTEM toggle greyed out | Expected when `abtem` isn't installed — see step 4. The tooltip says the same. |
| abTEM import error mentioning `typing.Self` | Your Python is 3.10 but you installed a too-new abtem: `pip install abtem==1.0.6`. |
| abTEM import error mentioning `itemset` | numpy 2 with an old abtem: `pip install "numpy<2"`. |
| AI assistant returns an error | No `OPENAI_API_KEY` in `backend/.env` (step 5). Everything else still works. |
| `npm run dev` port conflict | Vite will offer another port; accept it, or free 5173. |

---

## Ports used

| Port | Process |
|------|---------|
| 9094 | Digital Twin (Twisted JSON-RPC) |
| 8000 | Backend API (FastAPI) |
| 5173 | Frontend dev server (Vite) |
