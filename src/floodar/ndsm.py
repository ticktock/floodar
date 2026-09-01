"""nDSM — normalized Digital Surface Model = DSM - DEM = above-ground height.

Subtracting bare-earth (DEM) from the first-return surface (DSM) yields the height
of everything on the ground: buildings, tree canopy, infrastructure. NYC publishes
DSM and DEM as separate 1-foot products; both must be on the same grid.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from . import io


def compute(dsm_arr, dem_arr, *, clip_negative: bool = True):
    """nDSM from two aligned arrays. ``clip_negative`` floors below-ground noise
    (interpolation artifacts, water) to 0."""
    dsm = np.ma.masked_invalid(dsm_arr).astype("float64")
    dem = np.ma.masked_invalid(dem_arr).astype("float64")
    ndsm = dsm - dem
    if clip_negative:
        ndsm = np.ma.where(ndsm < 0, 0.0, ndsm)
    return ndsm


def from_files(
    dsm_path: str | Path,
    dem_path: str | Path,
    *,
    bounds: tuple[float, float, float, float] | None = None,
    max_size: int | None = 2048,
    clip_negative: bool = True,
):
    """Load DSM and DEM over the same window and return (nDSM, transform).

    Raises if the two rasters are not on the same grid — reproject/resample first.
    """
    aligned, reasons = io.check_aligned(dsm_path, dem_path)
    if not aligned:
        raise ValueError(
            "DSM and DEM are not grid-aligned; cannot subtract directly:\n  - "
            + "\n  - ".join(reasons)
        )
    dsm, transform = io.read(dsm_path, bounds=bounds, max_size=max_size)
    dem, _ = io.read(dem_path, bounds=bounds, max_size=max_size)
    return compute(dsm, dem, clip_negative=clip_negative), transform
