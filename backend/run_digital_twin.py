#!/usr/bin/env python3
"""
Run the STEM Digital Twin server (v6) separately.

Starts the Twisted-based digital twin. The server boots with NO sample
registered: register one via the GridScope Sample Settings window (or a
SimulationHarness client) before imaging.

Usage:
    python run_digital_twin.py

The server listens on port 9094 (JSON-RPC over netstrings).
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.digital_twin.server import main

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════╗
║          STEM Digital Twin Server (v6)                    ║
║      Simulated Microscope for GridScope                   ║
╠══════════════════════════════════════════════════════════╣
║  • 13-sample registry (crystals, polycrystal, amorphous,  ║
║    dislocations, Au nanoparticles, core-shell, ...)       ║
║  • Unified diffraction from atomic positions              ║
║  • Simulation environments (drift, damage, contamination) ║
║  • Stage safety limits (soft interlock)                   ║
║  • JSON-RPC over netstring protocol                       ║
╚══════════════════════════════════════════════════════════╝
    """)

    main(host="127.0.0.1", port=9094)
