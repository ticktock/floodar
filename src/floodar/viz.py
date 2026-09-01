"""Visualization — hillshade, slope/aspect, and color-ramped elevation to PNG."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def _gradients(arr, cellsize: float) -> tuple[np.ndarray, np.ndarray]:
    """Partial derivatives dz/dx, dz/dy in elevation-per-cell units.

    ``arr`` may be a masked array; masked cells are filled with the local mean so
    edges near nodata don't blow up. Returns plain ndarrays.
    """
    filled = np.ma.filled(np.ma.masked_invalid(arr).astype("float64"),
                          fill_value=np.nan)
    # np.gradient handles NaN poorly, so interpolate-fill via nan-aware mean pass.
    if np.isnan(filled).any():
        mean = np.nanmean(filled)
        filled = np.where(np.isnan(filled), mean, filled)
    dy, dx = np.gradient(filled, cellsize)
    return dx, dy


def hillshade(arr, cellsize: float = 1.0, azimuth: float = 315.0,
              altitude: float = 45.0, z_factor: float = 1.0) -> np.ndarray:
    """Classic Horn hillshade, 0..255. Default sun from the NW at 45° elevation.

    ``cellsize`` and elevation must share units (feet for NYC 2263 data). Bump
    ``z_factor`` to exaggerate relief in flat terrain like much of NYC.
    """
    dx, dy = _gradients(arr, cellsize)
    dx *= z_factor
    dy *= z_factor
    slope = np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dy, dx)
    az = np.radians(360.0 - azimuth + 90.0)
    alt = np.radians(altitude)
    shaded = (np.sin(alt) * np.cos(slope)
              + np.cos(alt) * np.sin(slope) * np.cos(az - aspect))
    return np.clip(shaded * 255.0, 0, 255).astype("uint8")


def slope(arr, cellsize: float = 1.0, degrees: bool = True) -> np.ndarray:
    """Slope magnitude per cell (degrees by default)."""
    dx, dy = _gradients(arr, cellsize)
    s = np.arctan(np.hypot(dx, dy))
    return np.degrees(s) if degrees else s


def aspect(arr, cellsize: float = 1.0) -> np.ndarray:
    """Aspect (compass degrees, 0=N, clockwise)."""
    dx, dy = _gradients(arr, cellsize)
    a = np.degrees(np.arctan2(-dy, dx))
    return (90.0 - a) % 360.0


def save_png(
    arr,
    out_path: str | Path,
    *,
    cmap: str = "terrain",
    hillshade_blend: bool = True,
    cellsize: float = 1.0,
    vmin: float | None = None,
    vmax: float | None = None,
    title: str | None = None,
    dpi: int = 150,
) -> Path:
    """Render an elevation array to a PNG with a colorbar, optionally blended with
    hillshade for a shaded-relief look. Returns the output path."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = np.ma.masked_invalid(arr)
    fig, ax = plt.subplots(figsize=(10, 10))
    im = ax.imshow(data, cmap=cmap, vmin=vmin, vmax=vmax)
    if hillshade_blend:
        hs = hillshade(arr, cellsize=cellsize)
        ax.imshow(hs, cmap="gray", alpha=0.35)
    ax.set_axis_off()
    if title:
        ax.set_title(title)
    fig.colorbar(im, ax=ax, shrink=0.7, label="elevation")
    out_path = Path(out_path)
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    return out_path
