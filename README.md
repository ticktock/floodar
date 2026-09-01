# floodar

Tooling to interpret and explore **DSM / DEM lidar rasters** (GeoTIFF), with a focus
on **flood-risk analysis**. Built around NYC's 1-foot LiDAR elevation products but
works with any single-band elevation GeoTIFF.

## The target data: NYC 1-foot DEM

- **Source:** [NYC OpenData — 1-foot DEM](https://data.cityofnewyork.us/City-Government/1-foot-Digital-Elevation-Model-DEM-/dpc8-z3jc/about_data)
  ([metadata](https://github.com/CityOfNewYork/nyc-geo-metadata/blob/main/Metadata/Metadata_DigitalElevationModel.md))
- **CRS:** EPSG:2263 — NAD83 / NY State Plane, Long Island East. Horizontal **and**
  vertical units are **US survey feet**.
- **Vertical datum:** NAVD88. So water levels (sea-level rise, storm surge) are
  expressed in **feet NAVD88** — e.g. Sandy's peak surge at the Battery was ~11 ft.
- **Resolution:** 1 foot. Tiles are large — everything reads *windowed / decimated*
  by default so exploration stays interactive.
- This product is **bare-earth DEM only** (ideal for flood modeling). NYC also
  publishes a separate 1-foot **DSM**; you need both for `ndsm` (above-ground heights).

## Install

```bash
uv sync                      # core library + CLI
uv sync --extra notebooks    # + JupyterLab / folium for the notebook
```

## Quickstart (fresh checkout)

```bash
uv sync --extra notebooks
uv run python scripts/get_data.py   # download NYC DEM + build the COG into data/ (~8 GB free needed)
uv run jupyter lab notebooks/        # then open 01_explore.ipynb or 02_redhook.ipynb
```

## CLI

```bash
uv run floodar info   TILE.tif                    # CRS, resolution, extent, nodata
uv run floodar stats  TILE.tif --mask-value 0     # min/max/mean/std + percentiles
uv run floodar render TILE.tif -o relief.png      # shaded-relief PNG
uv run floodar ndsm   DSM.tif DEM.tif -o ndsm.tif # above-ground heights (DSM - DEM)
uv run floodar sample TILE.tif -- -73.99 40.72    # elevation at lon/lat (WGS84)
uv run floodar cog    TILE.tif -o TILE_cog.tif    # -> tiled COG w/ overviews (fast reads)

# bathtub inundation over an AOI, several water levels; reports total vs dry-land acres
uv run floodar flood  DEM.tif -l 6 -l 11 -l 16 \
  --bounds "-74.020,40.700,-73.997,40.722" --aoi-epsg 4326
```

## Library

```python
from floodar import io, inspect, viz, flood

arr, transform = io.read("dem_tile.tif", max_size=2048)   # decimated read
print(inspect.stats(arr).as_dict())

result = flood.bathtub(arr, water_level=11.0, cell_size=abs(transform.a))
print(result.summary())     # flooded acres, mean/max depth, water volume
```

## Modules

| module | purpose |
|--------|---------|
| `floodar.io`      | windowed / decimated reads, metadata, grid-alignment, **polygon clip** |
| `floodar.inspect` | summary stats, histograms |
| `floodar.viz`     | hillshade, slope, aspect, color-ramped PNG export |
| `floodar.ndsm`    | normalized DSM (above-ground heights) = DSM − DEM |
| `floodar.query`   | point sampling, elevation profiles (reprojects lon/lat) |
| `floodar.flood`   | bathtub inundation with hydrologic connectivity + depth |

## Working with the real NYC integer DEM

The whole-city download comes in two forms. What actually matters for using them:

| | Integer raster | Floating-point raster |
|---|---|---|
| download | `NYC_DEM_1ft_Int.zip` — **3.2 GB** | `NYC_DEM_1ft_Float_2.zip` — 26 GB |
| unzips to | one **3.4 GB GeoTIFF** | one 99 GB ERDAS IMAGINE (`.img`/`.ige`) |
| dtype | `uint16`, whole feet | float feet |
| fits a 40 GB disk? | ✅ yes | ❌ no (needs ~200 GB) |

Start with the **integer raster** unless you need sub-foot vertical precision. Gotchas
learned from the real file (all handled by the tooling, but worth knowing):

- **158,100 × 156,100 px = 24.7 billion pixels** in one file. Always read windowed /
  decimated (`io.read(..., bounds=, max_size=)`); never the whole band.
- **`0` is overloaded**: it means open water, area outside the city footprint, *and*
  genuine 0-ft NAVD88 ground — ~65% of the grid. There is **no nodata tag**.
  - For **land** stats/relief, mask it: `stats --mask-value 0`, `render --mask-value 0`,
    or `io.read(..., mask_values=0)`.
  - For **flood** modeling, *keep* it — those water cells are the source inundation
    spreads from (`flood.bathtub(..., baseline=0.0)`, the default).
- **Elevations are whole feet, 0–411** (max = Todt Hill, SI). Below-datum ground is
  clamped to 0, so flood levels below ~1 ft aren't meaningful on this product.
- The GeoTIFF is LZW-**striped** (full-width rows), slow for AOI windowing. Run
  `floodar cog` once to get a tiled, overview-pyramided copy and everything gets fast.

### Flood metrics: total vs. dry-land

Because `0` = water, `flood` reports two areas: **total** inundation (includes the
existing harbor/rivers) and **dry-land flooded** (cells above the `baseline` waterline
— the incremental impact). The dry-land number is the one that answers "how much *new*
ground floods at +N ft?". Water levels are **feet NAVD88**; reference points: MHHW
~2.5 ft, Hurricane Sandy peak surge at the Battery ~11 ft.

### Clipping to a neighborhood

`io.read(..., clip=geom, clip_epsg=4326)` restricts a read to a polygon (a shapely
geometry or GeoJSON dict), so stats and areas cover just that area. See
`notebooks/02_redhook.ipynb`, which clips to an editable `redhook_boundary.geojson` to
report the Red Hook peninsula in isolation, and produces an **area-by-elevation table**
(hypsometric curve `A(h)`, density `dA/dh`, flood volume `V(h)`) exported to CSV — built
for related-rates / integral work.

Red Hook has **no standalone official NTA** (NYC's Neighborhood Tabulation Area BK33
bundles it with Carroll Gardens & Columbia St). The notebook ships alternative boundaries
dissolved from **official 2010 census tracts** — `redhook_tracts_core.geojson` (546 ac),
`redhook_tracts_peninsula.geojson` (591 ac), `redhook_nta_bk33.geojson` (full NTA,
1013 ac) — swap by changing one `BOUNDARY =` line.

**Flooding vs. clipping:** solve the flood on the *full* window (so water outside the
polygon still seeds connectivity), then restrict the reported area/volume to inside the
boundary — don't clip the DEM before flooding, or you cut off the water source.

## Flood model — what it is and isn't

`floodar.flood.bathtub` is a **planar water-surface ("bathtub") screening model**:
pick a water level, and ground cells below it flood. With `connected=True` (default)
only cells hydrologically connected (4-neighbour) to a water source flood, so isolated
low spots don't fill unless water can reach them. Output includes a continuous
flood-**depth** grid and exposure metrics (area, volume).

It is a first-order exposure screen, **not** a hydrodynamic simulation — it ignores
flow timing, drainage/sewers, and sub-cell barriers. Good for "what floods at +N ft?",
not for predicting flood arrival times.
