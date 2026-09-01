"""Reading elevation rasters — windowed and downsampled, so 1-foot tiles stay tractable.

At 1-foot resolution a single NYC tile can be tens of thousands of pixels on a side.
Almost nothing here reads a whole band into memory by default; instead we read a
*window* (a geographic sub-box) and/or *decimate* (downsample on read) so exploration
stays interactive.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window, from_bounds

# NYC 1-foot DEM/DSM ships as EPSG:2263 with, in practice, an undocumented nodata.
# Cells with no LiDAR return are commonly filled with a large sentinel; we treat any
# value at or below this (in feet) as nodata when the file itself declares none.
FALLBACK_NODATA_BELOW = -1e5


@dataclass
class RasterInfo:
    """Lightweight, JSON-friendly summary of a raster's georeferencing."""

    path: str
    driver: str
    crs: str | None
    epsg: int | None
    width: int
    height: int
    count: int
    dtype: str
    nodata: float | None
    res: tuple[float, float]
    bounds: tuple[float, float, float, float]  # left, bottom, right, top
    units: str | None

    @property
    def megapixels(self) -> float:
        return self.width * self.height / 1e6


def describe(path: str | Path) -> RasterInfo:
    """Read georeferencing metadata without loading pixel data."""
    with rasterio.open(path) as ds:
        crs = ds.crs
        epsg = crs.to_epsg() if crs else None
        # Linear unit if the CRS exposes one (NYC 2263 -> "US survey foot").
        units = None
        if crs and crs.is_projected:
            try:
                units = crs.linear_units
            except Exception:
                units = None
        return RasterInfo(
            path=str(path),
            driver=ds.driver,
            crs=str(crs) if crs else None,
            epsg=epsg,
            width=ds.width,
            height=ds.height,
            count=ds.count,
            dtype=ds.dtypes[0],
            nodata=ds.nodata,
            res=(abs(ds.transform.a), abs(ds.transform.e)),
            bounds=tuple(ds.bounds),
            units=units,
        )


def _effective_nodata(ds) -> float | None:
    """Declared nodata if present, else the fallback sentinel used by NYC tiles."""
    return ds.nodata if ds.nodata is not None else None


def read(
    path: str | Path,
    *,
    band: int = 1,
    bounds: tuple[float, float, float, float] | None = None,
    max_size: int | None = 2048,
    masked: bool = True,
    mask_values: float | list[float] | None = None,
    clip=None,
    clip_epsg: int | None = None,
):
    """Read a (possibly downsampled) band as a masked float32 array.

    Parameters
    ----------
    bounds : (left, bottom, right, top) in the raster CRS. If given, only that
        window is read. If None, the full extent is read (subject to ``max_size``).
    max_size : if the requested region is larger than this on its longest side, it
        is decimated on read to roughly this many pixels. Pass ``None`` to read at
        native resolution (careful: a full 1-ft tile can be many GB in memory).
    masked : return a ``numpy.ma.MaskedArray`` with nodata masked out.
    mask_values : additional pixel value(s) to mask out. Use ``mask_values=0`` on the
        NYC integer DEM to hide water / outside-city (both stored as 0) so land-relief
        stats and colour ramps aren't swamped. Do NOT use this for flood modeling —
        the 0 water cells are the source that inundation propagates from.
    clip : optional polygon to restrict to. Anything with a ``__geo_interface__``
        (a shapely geometry) or a GeoJSON geometry dict. Cells outside the polygon are
        masked, so stats/areas cover only that region (e.g. a neighborhood boundary).
    clip_epsg : EPSG of ``clip`` if it isn't already in the raster CRS (e.g. 4326 for
        lon/lat); the polygon is reprojected before masking.

    Returns
    -------
    (array, transform) where ``transform`` is the affine transform of the array
    actually returned (accounts for windowing and decimation).
    """
    with rasterio.open(path) as ds:
        if bounds is not None:
            window = from_bounds(*bounds, transform=ds.transform).round_offsets().round_lengths()
            window = window.intersection(Window(0, 0, ds.width, ds.height))
        else:
            window = Window(0, 0, ds.width, ds.height)

        win_w, win_h = int(window.width), int(window.height)
        if win_w <= 0 or win_h <= 0:
            raise ValueError("Requested bounds do not overlap the raster extent.")

        if max_size is not None and max(win_w, win_h) > max_size:
            scale = max_size / max(win_w, win_h)
            out_w = max(1, int(round(win_w * scale)))
            out_h = max(1, int(round(win_h * scale)))
        else:
            out_w, out_h = win_w, win_h

        arr = ds.read(
            band,
            window=window,
            out_shape=(out_h, out_w),
            resampling=Resampling.bilinear,
            masked=masked,
        ).astype("float32")

        transform = ds.window_transform(window)
        # Adjust transform for the decimation so pixel<->world stays correct.
        transform = transform @ transform.scale(win_w / out_w, win_h / out_h)

        if masked:
            nodata = _effective_nodata(ds)
            if nodata is not None:
                arr = np.ma.masked_equal(arr, np.float32(nodata))
            # Guard against undocumented sentinels in NYC tiles.
            arr = np.ma.masked_less_equal(arr, np.float32(FALLBACK_NODATA_BELOW))
            if mask_values is not None:
                vals = [mask_values] if np.isscalar(mask_values) else mask_values
                for v in vals:
                    arr = np.ma.masked_equal(arr, np.float32(v))

        if clip is not None:
            from rasterio.features import geometry_mask
            from rasterio.warp import transform_geom
            geom = getattr(clip, "__geo_interface__", clip)
            if clip_epsg is not None and ds.crs is not None and ds.crs.to_epsg() != clip_epsg:
                geom = transform_geom(f"EPSG:{clip_epsg}", ds.crs, geom)
            # geometry_mask returns True OUTSIDE the polygon (cells to hide).
            outside = geometry_mask([geom], out_shape=arr.shape, transform=transform)
            base = np.ma.getmaskarray(arr) if masked else np.zeros(arr.shape, bool)
            arr = np.ma.masked_array(np.ma.getdata(arr), mask=base | outside)

        return arr, transform


def check_aligned(path_a: str | Path, path_b: str | Path) -> tuple[bool, list[str]]:
    """Check whether two rasters share a grid (needed for nDSM = DSM - DEM).

    Returns (aligned, reasons). ``aligned`` is True only if CRS, resolution, shape,
    and origin all match closely enough to subtract cell-for-cell.
    """
    a, b = describe(path_a), describe(path_b)
    reasons: list[str] = []
    if a.epsg != b.epsg:
        reasons.append(f"CRS differs: {a.epsg} vs {b.epsg}")
    if not np.allclose(a.res, b.res, rtol=1e-6):
        reasons.append(f"resolution differs: {a.res} vs {b.res}")
    if (a.width, a.height) != (b.width, b.height):
        reasons.append(f"shape differs: {a.width}x{a.height} vs {b.width}x{b.height}")
    if not np.allclose(a.bounds, b.bounds, atol=max(a.res)):
        reasons.append(f"bounds differ: {a.bounds} vs {b.bounds}")
    return (len(reasons) == 0, reasons)
