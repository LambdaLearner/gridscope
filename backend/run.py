#!/usr/bin/env python3
"""
Run the GridScope Backend server.

Usage:
    python run.py
    
Or with uvicorn directly:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

import os
import uvicorn
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def main():
    """Run the FastAPI server."""
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    
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
    
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()

