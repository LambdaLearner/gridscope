"""Shared test fixtures for the GridScope backend."""

import sys
from pathlib import Path

import pytest

# Ensure the backend app package is importable
backend_root = Path(__file__).resolve().parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))
