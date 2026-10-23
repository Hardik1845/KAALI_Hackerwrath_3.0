"""KAALI DeepDefend engine. Heavy ML dependencies are loaded on demand."""

__all__ = ["DeepfakeDetector", "DetectionResult"]


def __getattr__(name):
    if name in __all__:
        from .pipeline import DeepfakeDetector, DetectionResult
        return {"DeepfakeDetector": DeepfakeDetector, "DetectionResult": DetectionResult}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
