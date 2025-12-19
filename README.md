# GridScope

**AI-Powered STEM Digital Twin for Automated Microscopy**
---

## Overview

GridScope is an AI-powered automation platform for Scanning Transmission Electron Microscopy (STEM) that bridges the gap between experimental design and instrument execution. Researchers describe imaging objectives in natural language—such as *"acquire a 5×5 grid at 3 µm spacing"* or *"explore tilt angles from 0° to 60°"*—and receive executable Python scripts validated against a physics-based Digital Twin.

### Key Features

| Feature | Description |
|---------|-------------|
| **Natural Language Interface** | Describe experiments in plain English, get executable code |
| **STEM Digital Twin** | Physics-based simulator with 3D samples, tilt, and diffraction |
| **Multiple Samples** | Gold nanoparticles and FCC single crystal |
| **Imaging & Diffraction Modes** | Switch between real-space imaging and FFT-based diffraction |
| **Tilt Series** | α/β stage tilt from -60° to +60° for 3D exploration |
| **Live Execution** | Run generated scripts directly on the Digital Twin |

---

## Quick Start

### Prerequisites

- Node.js ≥ 18.x
- Python ≥ 3.10
- OpenAI API Key

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
| Frontend | React, TypeScript, Tailwind | Microscope UI, AI chat, execution panel |
| Backend | FastAPI, Python | API routing, LLM orchestration |
| Digital Twin | Twisted JSON-RPC | STEM physics simulation |
| AI Agent | OpenAI GPT-4 | Natural language to Python code |

---

## Usage

### 1. Microscope Control (Left Panel)

- **Mode Toggle**: Switch between Imaging and Diffraction
- **Sample Selection**: Au Nanoparticles or FCC Crystal
- **Stage Control**: X/Y movement with configurable step size
- **Tilt Control**: α/β angles for 3D projection
- **Beam Settings**: Voltage (60-300 kV) and Current (5-200 pA)

### 2. AI Assistant (Center Panel)

Enter natural language prompts:

```
"Take a 5x5 grid of images spaced 3 micrometers apart"
"Explore different a and b values from 0 to 60 with step 10"
"Acquire images in diffraction mode at various defocus levels"
```

### 3. Execution Output (Right Panel)

- View generated Python code
- Run scripts on the Digital Twin
- Monitor execution progress
- Browse acquired images with metadata

---

## Digital Twin Capabilities

### Samples

| Sample | Description |
|--------|-------------|
| **Au Nanoparticles** | 2048×2048×72 voxel volume, ~1200 random particles |
| **FCC Single Crystal** | 768×768×64 voxel periodic lattice (a=24 px) |

### Imaging Modes

| Mode | Output |
|------|--------|
| **Imaging (IMG)** | Real-space STEM projection with tilt |
| **Diffraction (DIFF)** | FFT-based diffraction pattern |

### Stage Parameters

| Parameter | Range | Units |
|-----------|-------|-------|
| X, Y position | ±100 | µm |
| Z (focus) | ±10 | µm |
| α (alpha tilt) | ±60 | degrees |
| β (beta tilt) | ±60 | degrees |


---

### REST Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/microscope/status` | GET | Connection status |
| `/api/microscope/acquire` | POST | Acquire image |
| `/api/microscope/stage` | POST | Set stage/tilt |
| `/api/execute/simple` | POST | Execute actions |
| `/api/chat` | POST | AI assistant |
| `/api/code/generate` | POST | Generate Python code |

---

