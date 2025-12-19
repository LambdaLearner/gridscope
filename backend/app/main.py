"""
GridScope Backend - Microscopy LLM Assistant API

FastAPI application providing:
- Chat interface for microscopy assistance
- Python code generation for automated experiments
- Integration with various microscopy software APIs
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from .routes import chat_router, code_router, health_router, microscope_router, execute_router


# Load environment variables
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    print("🔬 GridScope Backend starting...")
    
    # Check for API key
    if os.getenv("OPENAI_API_KEY"):
        print("✅ OpenAI API key configured")
    else:
        print("⚠️  OpenAI API key not found - LLM features will be limited")
    
    yield
    
    # Shutdown
    print("🔬 GridScope Backend shutting down...")


# Create FastAPI application
app = FastAPI(
    title="GridScope API",
    description="Microscopy LLM Assistant - Generate Python automation scripts for microscopy experiments",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health_router)
app.include_router(chat_router, prefix="/api")
app.include_router(code_router, prefix="/api")
app.include_router(microscope_router, prefix="/api")
app.include_router(execute_router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "GridScope API",
        "version": "1.0.0",
        "description": "Microscopy LLM Assistant with Digital Twin",
        "docs": "/docs",
        "endpoints": {
            "health": "/health",
            "chat": "/api/chat",
            "code_generation": "/api/code/generate",
            "templates": "/api/code/templates",
            "microscope_status": "/api/microscope/status",
            "microscope_stage": "/api/microscope/stage",
            "microscope_acquire": "/api/microscope/acquire",
        }
    }


@app.get("/api")
async def api_info():
    """API information endpoint."""
    return {
        "version": "1.0.0",
        "endpoints": [
            {"path": "/api/chat", "method": "POST", "description": "Chat with the microscopy assistant"},
            {"path": "/api/chat/analyze", "method": "POST", "description": "Analyze experimental objectives"},
            {"path": "/api/chat/quick-help", "method": "POST", "description": "Get quick help on topics"},
            {"path": "/api/code/generate", "method": "POST", "description": "Generate automation code"},
            {"path": "/api/code/templates", "method": "GET", "description": "List available templates"},
            {"path": "/api/code/apis", "method": "GET", "description": "List supported APIs"},
        ]
    }

