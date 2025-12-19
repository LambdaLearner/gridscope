"""Health check endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy", "service": "gridscope-backend"}


@router.get("/ready")
async def readiness_check():
    """Readiness check for the service."""
    return {"status": "ready"}

