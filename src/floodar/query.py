"""Point, profile, and AOI queries against elevation rasters."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform as warp_transform


def _to_raster_crs(ds, xs, ys, src_epsg: int | None):
    """Reproject input coords into the raster CRS if a source EPSG is given."""
    if src_epsg is None or ds.crs is None or ds.crs.to_epsg() == src_epsg:
        return xs, ys
    xs2, ys2 = warp_transform(f"EPSG:{src_epsg}", ds.crs, xs, ys)
    return xs2, ys2


def sample_points(
    path: str | Path,
    coords: list[tuple[float, float]],
    *,
    src_epsg: int | None = None,
    band: int = 1,
) -> list[float | None]:
    """Sample elevation at (x, y) coordinates.

    ``src_epsg`` lets you pass e.g. WGS84 lon/lat (4326) and have them reprojected
    into the raster CRS (2263 for NYC). Coords are (x, y) == (lon, lat) order.
    Returns elevation per point, or None where outside extent / nodata.
    """
    with rasterio.open(path) as ds:
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        xs, ys = _to_raster_crs(ds, xs, ys, src_epsg)
        out: list[float | None] = []
        nodata = ds.nodata
        for val in ds.sample(list(zip(xs, ys)), indexes=band):
            v = float(val[0])
            if (nodata is not None and v == nodata) or v <= io_fallback():
                out.append(None)
            else:
                out.append(v)
        return out


def io_fallback() -> float:
    from .io import FALLBACK_NODATA_BELOW
    return FALLBACK_NODATA_BELOW


def profile(
    path: str | Path,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    n: int = 200,
    src_epsg: int | None = None,
    band: int = 1,
):
    """Elevation profile along the straight line from ``start`` to ``end``.

    Returns (distances, elevations) where distances are along-line in raster-CRS
    units (feet for NYC). Handy for cross-sections through a flood path.
    """
    xs = np.linspace(start[0], end[0], n)
    ys = np.linspace(start[1], end[1], n)
    coords = list(zip(xs.tolist(), ys.tolist()))
    elevs = sample_points(path, coords, src_epsg=src_epsg, band=band)
    with rasterio.open(path) as ds:
        rx, ry = _to_raster_crs(ds, xs.tolist(), ys.tolist(), src_epsg)
    rx = np.asarray(rx)
    ry = np.asarray(ry)
    dists = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(rx), np.diff(ry)))])
    return dists, np.array([np.nan if e is None else e for e in elevs])
