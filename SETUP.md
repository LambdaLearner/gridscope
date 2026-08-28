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


### Python too old? (macOS ships 3.9.6)

Don't try to update the system Python — install a newer one alongside it:

- **macOS with Homebrew:** `brew install python@3.12`
- **macOS/Windows without Homebrew:** install 3.11 or 3.12 from
  https://www.python.org/downloads/ (on Windows, tick *"Add python.exe to
  PATH"*).

Then in step 3 create the venv with the new interpreter **explicitly**
(plain `python3` may still point at the old one):

```bash
python3.12 -m venv venv      # Windows: py -3.12 -m venv venv
```

Once the venv is created, activating it always gives you the right Python.

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

## 4. Optional: OpenAI API key (AI assistant)

The AI chat assistant needs an OpenAI key. Everything else (manual
microscope control, samples, environments, script execution) works without
one.

```bash
# still inside backend/
cp env.example .env
# then edit .env and set:  OPENAI_API_KEY=sk-...
```

---

## 5. Frontend setup (Node)

```bash
cd ..            # back to the repo root
npm install
```

---

## 6. Run it — three terminals

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

## 7. First steps in the app

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

- **Live mode** with drift enabled (Acquisition conditions → Mechanical
  drift, e.g. 2 nm/s at a ≤1 µm FOV) — watch the field drift in real time.
- **Zoom in** (raise magnification / shrink FOV below ~50 nm) on a crystal
  to resolve atomic columns; raise **Resolution** to 1024/2048 px.
- **Diffraction mode**, then tilt α/β to navigate zone axes.
- **Contamination** on (Acquisition conditions) at a small FOV — watch the
  **contamination meter** climb and a bright scan-box footprint form where
  the beam dwells.
- **TIFF** button — downloads the current frame as a quantitative 32-bit
  TIFF with the acquisition context embedded (opens in ImageJ/Fiji).

---

## 8. Verify the install (optional)

```bash
# Backend tests (~2 min)
cd backend && venv/bin/python -m pytest        # Windows: venv\Scripts\python -m pytest

# Frontend tests (~5 s)
npx vitest run
```

Everything should pass on a clean checkout.

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| Twin fails with `Address already in use` (port 9094) | An old twin is still running: `lsof -ti :9094 \| xargs kill` (macOS/Linux) or find and kill the python process (Windows), then restart. **A stale twin serves stale code** — always restart it after pulling changes. |
| Frontend shows **Disconnected** | Make sure Terminals 1 AND 2 are both running; the UI talks to the API on `localhost:8000`, which talks to the twin on `9094`. |
| `ModuleNotFoundError` in the backend | The venv isn't activated, or you're using a different Python. Re-run the activate command; check `which python` points into `backend/venv`. |
| AI assistant returns an error | No `OPENAI_API_KEY` in `backend/.env` (step 4). Everything else still works. |
| `npm run dev` port conflict | Vite will offer another port; accept it, or free 5173. |

---

## Ports used

| Port | Process |
|------|---------|
| 9094 | Digital Twin (Twisted JSON-RPC) |
| 8000 | Backend API (FastAPI) |
| 5173 | Frontend dev server (Vite) |

---

## Security & network exposure

GridScope is a single-user research tool. By default the backend binds to
**loopback only** (`127.0.0.1`), so nothing on your network can reach it —
this is the configuration every step above assumes, and it needs no further
setup.

Exposing the backend on a network interface is an explicit opt-in and
should always be paired with an access token, because the API includes
endpoints that move the (simulated) stage, execute Python scripts
server-side, and spend OpenAI credit:

```bash
# backend/.env
HOST=0.0.0.0                       # deliberate exposure — off by default
GRIDSCOPE_API_TOKEN=<random-token> # required auth on every endpoint

# frontend (.env.local in the repo root)
VITE_GRIDSCOPE_API_TOKEN=<same-token>
```

Generate a token with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`. When the
token is set, every request (including `/docs` and the script-run stream)
must send `Authorization: Bearer <token>`; the frontend does this
automatically when `VITE_GRIDSCOPE_API_TOKEN` is set. `run.py` prints a
warning if you bind a non-loopback interface without a token.

The server speaks plain HTTP. If you ever run it across a shared network,
terminate TLS in front of it with a standard reverse proxy (nginx, caddy);
certificate handling is deliberately out of scope for this codebase.
