#!/usr/bin/env python3
"""
Run the TEM Digital Twin Server separately.

This starts the Twisted-based TEM Digital Twin server that simulates
a real microscope with a gold nanoparticle sample.

Usage:
    python run_digital_twin.py

The server will be available on port 9094.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.digital_twin.tem_server import main

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════╗
║          TEM Digital Twin Server                          ║
║      Simulated Microscope for GridScope                   ║
╠══════════════════════════════════════════════════════════╣
║  Features:                                                ║
║  • 10,000×10,000 synthetic gold nanoparticle sample      ║
║  • Subpixel bilinear sampling for smooth motion          ║
║  • FOV zoom control                                       ║
║  • Defocus blur + autofocus                              ║
║  • JSON-RPC over netstring protocol                      ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    main(host="127.0.0.1", port=9094)

