"""sitepix: website ready images from a local model on Apple Silicon."""

__version__ = "0.1.0"

from .core import Request, Result, SitepixError, generate  # noqa: E402,F401

__all__ = ["Request", "Result", "SitepixError", "generate", "__version__"]
