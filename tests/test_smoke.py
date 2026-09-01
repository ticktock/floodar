"""Smoke tests on a synthetic DEM — no real NYC download required.

The synthetic tile mimics NYC 2263: EPSG:2263, 1-foot cells, elevations in feet,
a coastal low-lying strip that should flood and an interior hill that shouldn't.
"""

from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from floodar import flood, inspect, io, ndsm, viz


@pytest.fixture
def dem_path(tmp_path):
    """A 200x200 ft synthetic DEM: coastal ramp on the left, hill on the right,
    plus a walled interior depression at 2 ft — dry land (above the 0-ft waterline)
    that sits below a 5 ft flood but is not connected to the coast, so it must
    stay dry under a connected bathtub model."""
    h = np.zeros((200, 200), dtype="float32")
    xs = np.arange(200)
    h += (xs / 200.0 * 40.0)[None, :]          # 0 ft at west edge -> 40 ft at east
    h[90:110, 150:170] = 2.0                   # interior depression (dry land), walled off
    path = tmp_path / "dem.tif"
    transform = from_origin(980000, 200000, 1.0, 1.0)  # arbitrary 2263-ish origin
    with rasterio.open(
        path, "w", driver="GTiff", height=200, width=200, count=1,
        dtype="float32", crs="EPSG:2263", transform=transform, nodata=-9999.0,
    ) as dst:
        dst.write(h, 1)
    return path


def test_describe(dem_path):
    ri = io.describe(dem_path)
    assert ri.epsg == 2263
    assert ri.res == (1.0, 1.0)
    assert ri.width == 200 and ri.height == 200


def test_read_and_stats(dem_path):
    arr, transform = io.read(dem_path, max_size=None)
    assert arr.shape == (200, 200)
    s = inspect.stats(arr)
    assert s.min == pytest.approx(0.0, abs=1e-3)
    assert s.max == pytest.approx(39.8, abs=0.5)


def test_flood_connectivity(dem_path):
    """At 5 ft, the coastal strip floods but the walled interior pit must NOT."""
    arr, transform = io.read(dem_path, max_size=None)
    r = flood.bathtub(arr, water_level=5.0, cell_size=abs(transform.a), connected=True)
    # Interior pit (rows 90-110, cols 150-170) is surrounded by ~30 ft terrain.
    assert not r.flooded[100, 160], "walled interior pit should stay dry"
    # West edge is at/below 5 ft and connected to the boundary water source.
    assert r.flooded[100, 5], "coastal low ground should flood"
    assert r.flooded_area > 0


def test_flood_disconnected_fills_pit(dem_path):
    """With connectivity off, the pit floods too (dumb bathtub)."""
    arr, transform = io.read(dem_path, max_size=None)
    r = flood.bathtub(arr, water_level=5.0, cell_size=abs(transform.a), connected=False)
    assert r.flooded[100, 160], "dumb bathtub floods the pit"


def test_flood_depth(dem_path):
    arr, transform = io.read(dem_path, max_size=None)
    r = flood.bathtub(arr, water_level=10.0, cell_size=1.0)
    d = np.ma.filled(r.depth, 0.0)
    assert d.max() <= 10.0 + 5.0 + 1e-3   # deepest = level - lowest ground
    assert d.min() >= 0.0


def test_land_vs_total_flood(dem_path):
    """Total inundation includes the standing-water baseline; land-flooded excludes it."""
    arr, transform = io.read(dem_path, max_size=None)
    # add a strip of standing water (elev 0) that is already 'wet' at baseline
    a = np.ma.filled(arr, 0.0).copy()
    a[:, :3] = 0.0
    r = flood.bathtub(a, water_level=5.0, cell_size=1.0, baseline=0.0)
    assert r.flooded_area_acres >= r.land_flooded_area_acres
    # newly-flooded cells must all be above the baseline waterline
    assert (a[r.newly_flooded] > 0.0).all()


def test_mask_values(dem_path):
    """mask_values=0 hides the 0-ft cells (NYC water) from stats."""
    arr, _ = io.read(dem_path, max_size=None, mask_values=0)
    assert (np.ma.filled(arr, 1.0) != 0.0).all()


def test_clip_polygon(dem_path):
    """clip= restricts the read to a polygon; cells outside are masked."""
    ri = io.describe(dem_path)
    l, b, r, t = ri.bounds
    # a small box covering the western quarter of the raster, in the raster CRS
    poly = {"type": "Polygon", "coordinates": [[
        [l, b], [l + (r - l) * 0.25, b], [l + (r - l) * 0.25, t], [l, t], [l, b]]]}
    arr, _ = io.read(dem_path, max_size=None, clip=poly)
    valid_cols = (~np.ma.getmaskarray(arr)).any(axis=0)
    assert valid_cols[:50].any(), "western cells should survive the clip"
    assert not valid_cols[150:].any(), "eastern cells should be clipped out"


def test_ndsm(dem_path, tmp_path):
    """nDSM of a surface 12 ft above the DEM should be ~12 everywhere."""
    with rasterio.open(dem_path) as src:
        dem = src.read(1)
        prof = src.profile
    dsm_path = tmp_path / "dsm.tif"
    with rasterio.open(dsm_path, "w", **prof) as dst:
        dst.write(dem + 12.0, 1)
    n, _ = ndsm.from_files(dsm_path, dem_path, max_size=None)
    assert float(np.ma.median(n)) == pytest.approx(12.0, abs=1e-3)


def test_to_cog(dem_path, tmp_path):
    """to_cog produces a tiled GeoTIFF with overviews."""
    out = tmp_path / "cog.tif"
    io.to_cog(dem_path, out, blocksize=64)  # small block so the 200px synthetic gets overviews
    with rasterio.open(out) as ds:
        assert ds.is_tiled
        assert ds.overviews(1), "COG should have overview levels"


def test_hillshade(dem_path):
    arr, _ = io.read(dem_path, max_size=None)
    hs = viz.hillshade(arr, cellsize=1.0)
    assert hs.shape == arr.shape
    assert hs.dtype == np.uint8
