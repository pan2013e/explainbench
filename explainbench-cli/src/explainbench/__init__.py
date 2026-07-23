"""Public package for the ExplainBench benchmark."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("explainbench")
except PackageNotFoundError:  # Running directly from a source checkout.
    __version__ = "0.1.0"

__all__ = ["__version__"]
