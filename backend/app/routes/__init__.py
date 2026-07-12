from .chat import router as chat_router
from .code import router as code_router
from .health import router as health_router
from .microscope import router as microscope_router
from .simulation import router as simulation_router
from .execute import router as execute_router

__all__ = [
    "chat_router",
    "code_router",
    "health_router",
    "microscope_router",
    "simulation_router",
    "execute_router",
]
