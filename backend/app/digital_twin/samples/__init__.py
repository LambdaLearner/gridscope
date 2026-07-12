import importlib
import pkgutil
from typing import Dict, Type
from .base import Sample, SampleMetadata

_REGISTRY: Dict[str, Type[Sample]] = {}


def register(cls: Type[Sample]) -> Type[Sample]:
    """Decorator: registers a Sample subclass by its meta.name."""
    if cls.meta is None:
        raise ValueError(f"{cls.__name__} must define a `meta` SampleMetadata")
    _REGISTRY[cls.meta.name] = cls
    return cls


def discover(force_reload: bool = False):
    """
    Rescan the samples/ directory and import any sample modules not yet loaded.

    Safe to call repeatedly. If `force_reload=True`, already-imported sample
    modules are reloaded so their @register decorators run again.
    """
    import sys as _sys
    importlib.invalidate_caches()
    for _, modname, _ in pkgutil.iter_modules(__path__):
        if modname in ("base", "__init__"):
            continue
        full = f"{__name__}.{modname}"
        if force_reload and full in _sys.modules:
            importlib.reload(_sys.modules[full])
        else:
            importlib.import_module(full)


def list_samples():
    discover()  # ensure fresh scan before every call
    return [
        {
            "name": cls.meta.name,
            "display_name": cls.meta.display_name,
            "description": cls.meta.description,
            "default_params": cls.meta.default_params,
            "param_schema": cls.meta.param_schema,
        }
        for cls in _REGISTRY.values()
    ]


def get_sample(name: str, **params) -> Sample:
    discover()  # ensure fresh scan before every call
    if name not in _REGISTRY:
        raise KeyError(
            f"Unknown sample '{name}'. Available: {list(_REGISTRY.keys())}"
        )
    return _REGISTRY[name](**params)


# Initial discovery at import time
discover()
