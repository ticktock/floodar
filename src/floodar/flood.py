"""Flood-inundation modeling on a bare-earth DEM.

The workhorse is the *bathtub* (planar water-surface) model: pick a water level in
the DEM's vertical units (feet NAVD88 for NYC) and every ground cell below it floods.

Two refinements matter for realism:

* **Hydrologic connectivity** — a low spot in the middle of a city block should not
  flood unless water can actually reach it. With ``connected=True`` only cells that
  are below the water level *and* connected (4-neighbour) to a water source flood.
  The source defaults to the array edge (water encroaching from outside the tile);
  pass explicit ``seeds`` to inundate from a known shoreline/breach point instead.

* **Depth** — ``depth = water_level - ground`` on flooded cells, so you get a
  continuous flood-depth grid, not just a wet/dry mask.

This is a screening tool (first-order surge / sea-level-rise exposure), not a
hydrodynamic simulation — it ignores flow timing, drainage, and barriers below DEM
resolution.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage


@dataclass
class FloodResult:
    water_level: float
    depth: np.ndarray            # masked array, flood depth (0 where dry / nodata)
    flooded: np.ndarray          # bool mask of flooded cells (includes standing water)
    cell_area: float             # area per cell in CRS units^2 (ft^2 for NYC)
    flooded_cells: int
    land_mask: np.ndarray        # bool: cells that are dry land at baseline (not water)
    baseline: float              # water elevation treated as pre-existing water

    @property
    def flooded_area(self) -> float:
        """Total inundated area, incl. standing water, in CRS units^2 (ft^2 for NYC)."""
        return self.flooded_cells * self.cell_area

    @property
    def flooded_area_acres(self) -> float:
        return self.flooded_area / 43_560.0  # ft^2 -> acres

    @property
    def newly_flooded(self) -> np.ndarray:
        """Dry land (above ``baseline``) that is inundated — the incremental impact,
        excluding rivers/harbor already at/below the baseline waterline. This is the
        metric that matters when 0 = water (as in the NYC integer DEM)."""
        return self.flooded & self.land_mask

    @property
    def land_flooded_area(self) -> float:
        return int(self.newly_flooded.sum()) * self.cell_area

    @property
    def land_flooded_area_acres(self) -> float:
        return self.land_flooded_area / 43_560.0

    @property
    def water_volume(self) -> float:
        """Flood-water volume above ground on newly-flooded land, in CRS units^3."""
        d = np.ma.filled(self.depth, 0.0) * self.newly_flooded
        return float(d.sum()) * self.cell_area

    def summary(self) -> dict:
        d = np.ma.filled(self.depth, 0.0)
        wet = d[self.newly_flooded]
        return {
            "water_level": self.water_level,
            "flooded_area_acres": self.flooded_area_acres,          # incl. standing water
            "land_flooded_acres": self.land_flooded_area_acres,      # dry land only
            "mean_depth": float(wet.mean()) if wet.size else 0.0,
            "max_depth": float(wet.max()) if wet.size else 0.0,
            "water_volume_ft3": self.water_volume,
        }


def _edge_seed_mask(shape: tuple[int, int]) -> np.ndarray:
    m = np.zeros(shape, dtype=bool)
    m[0, :] = m[-1, :] = m[:, 0] = m[:, -1] = True
    return m


def bathtub(
    dem_arr,
    water_level: float,
    *,
    cell_size: float = 1.0,
    connected: bool = True,
    baseline: float = 0.0,
    seed_from_water: bool = True,
    seeds: np.ndarray | None = None,
) -> FloodResult:
    """Bathtub inundation for a single water level.

    Parameters
    ----------
    dem_arr : bare-earth elevation array (masked array ok). Units must match
        ``water_level`` (feet for NYC).
    water_level : planar water-surface elevation (e.g. 11.0 ft NAVD88 ~ Sandy peak
        surge at the Battery).
    cell_size : ground size of a pixel in CRS units (1.0 ft native; larger if you
        read decimated — use ``transform.a`` from :func:`floodar.io.read`).
    connected : restrict flooding to cells hydrologically connected to a water
        source (recommended). If False, every below-level cell floods ("dumb" bathtub).
    baseline : elevation of the existing waterline. Cells at or below it are treated
        as pre-existing water (rivers/harbor), so they seed flooding and are excluded
        from "dry land flooded" stats. For the NYC integer DEM, water is stored as 0,
        so the default ``baseline=0.0`` is correct.
    seed_from_water : also seed connectivity from pre-existing water cells (dem <=
        baseline), not just the array edge — so inundation spreads from the harbor/
        rivers inside the scene, which is the physically correct source for NYC.
    seeds : optional explicit boolean array of water-source cells (e.g. a known
        breach point). Overrides the default edge/water seeding when given.
    """
    dem = np.ma.masked_invalid(dem_arr)
    filled = np.ma.filled(dem, np.inf)          # nodata -> +inf so it never floods
    below = filled <= water_level
    land_mask = filled > baseline               # dry land at baseline (excludes water)

    if connected:
        if seeds is None:
            seeds = _edge_seed_mask(dem.shape)
            if seed_from_water:
                seeds = seeds | (filled <= baseline)
        # A cell floods if it is below the water level and reachable, through other
        # below-level cells, from a seed. Label connected components of `below`
        # (4-connectivity = water doesn't leak diagonally) and keep components that
        # touch a seed.
        structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])
        labels, _ = ndimage.label(below, structure=structure)
        seed_labels = np.unique(labels[seeds & below])
        seed_labels = seed_labels[seed_labels != 0]
        flooded = np.isin(labels, seed_labels)
    else:
        flooded = below

    depth = np.where(flooded, water_level - np.ma.filled(dem, water_level), 0.0)
    depth = np.clip(depth, 0.0, None)
    depth = np.ma.array(depth, mask=np.ma.getmaskarray(dem))

    return FloodResult(
        water_level=float(water_level),
        depth=depth,
        flooded=flooded,
        cell_area=float(cell_size) ** 2,
        flooded_cells=int(flooded.sum()),
        land_mask=land_mask,
        baseline=float(baseline),
    )


def scenarios(
    dem_arr,
    levels,
    *,
    cell_size: float = 1.0,
    connected: bool = True,
    baseline: float = 0.0,
    seed_from_water: bool = True,
    seeds: np.ndarray | None = None,
) -> list[FloodResult]:
    """Run several water levels (e.g. sea-level-rise steps or surge scenarios)."""
    return [
        bathtub(dem_arr, lvl, cell_size=cell_size, connected=connected,
                baseline=baseline, seed_from_water=seed_from_water, seeds=seeds)
        for lvl in levels
    ]
