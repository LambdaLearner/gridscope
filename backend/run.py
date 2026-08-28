#!/usr/bin/env python3
"""
Run the GridScope Backend server.

Usage:
    python run.py

Or with uvicorn directly:
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

The server binds to loopback (127.0.0.1) by default, so it is unreachable
from the network. To expose it deliberately, set HOST=0.0.0.0 — and pair it
with GRIDSCOPE_API_TOKEN so every endpoint requires bearer-token auth
(see app/auth.py).
"""

import os
import uvicorn
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def resolve_host_port():
    """Bind address from the environment; loopback-only unless overridden."""
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    return host, port


def main():
    """Run the FastAPI server."""
    host, port = resolve_host_port()

    print(f"""
╔══════════════════════════════════════════════════════════╗
║                  GridScope Backend                        ║
║           Microscopy LLM Assistant API                    ║
╠══════════════════════════════════════════════════════════╣
║  Server: http://{host}:{port}
║  Docs:   http://{host}:{port}/docs
║  ReDoc:  http://{host}:{port}/redoc
╚══════════════════════════════════════════════════════════╝
    """)

    if host not in LOOPBACK_HOSTS and not os.getenv("GRIDSCOPE_API_TOKEN"):
        print(
            "⚠️  WARNING: binding to a non-loopback interface without "
            "GRIDSCOPE_API_TOKEN set.\n"
            "   Anyone on the network can control the microscope twin, "
            "execute scripts, and spend OpenAI credit.\n"
            "   Set GRIDSCOPE_API_TOKEN to require bearer-token auth on "
            "every endpoint.\n"
        )

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
