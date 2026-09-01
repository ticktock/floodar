"""floodar — interpret and explore DSM/DEM lidar rasters, with a focus on flood risk.

Built around NYC 1-foot DEM/DSM data (EPSG:2263, NAD83 NY State Plane Long Island
East, US feet horizontal and vertical, NAVD88 vertical datum) but works with any
single-band elevation GeoTIFF.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("floodar")
except PackageNotFoundError:  # pragma: no cover - not installed
    __version__ = "0.0.0+dev"

from . import flood, inspect, io, ndsm, query, viz

__all__ = ["flood", "inspect", "io", "ndsm", "query", "viz", "__version__"]
