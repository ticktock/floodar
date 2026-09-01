"""floodar command-line interface.

    floodar info    TILE.tif                 # georeferencing metadata
    floodar stats   TILE.tif                 # summary statistics + histogram
    floodar render  TILE.tif -o out.png      # shaded-relief PNG
    floodar ndsm    DSM.tif DEM.tif -o n.tif # above-ground heights
    floodar sample  TILE.tif -- -73.99 40.72 # elevation at lon/lat (EPSG:4326)
    floodar flood   DEM.tif --level 11       # bathtub inundation at 11 ft NAVD88
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import flood as flood_mod
from . import inspect as inspect_mod
from . import io, ndsm, query, viz

app = typer.Typer(add_completion=False, help=__doc__, no_args_is_help=True)
console = Console()


@app.command()
def info(path: Path):
    """Print CRS, resolution, extent, and nodata for a raster."""
    ri = io.describe(path)
    t = Table(show_header=False, title=str(path))
    t.add_row("driver", ri.driver)
    t.add_row("CRS", f"{ri.crs}  (EPSG:{ri.epsg})")
    t.add_row("size", f"{ri.width} x {ri.height}  ({ri.megapixels:.1f} Mpx)")
    t.add_row("resolution", f"{ri.res[0]} x {ri.res[1]} {ri.units or ''}")
    t.add_row("dtype", ri.dtype)
    t.add_row("nodata", str(ri.nodata))
    t.add_row("bounds", f"{tuple(round(b, 2) for b in ri.bounds)}")
    console.print(t)


@app.command()
def stats(
    path: Path,
    max_size: int = typer.Option(2048, help="Downsample longest side to N px on read."),
    mask_value: Optional[float] = typer.Option(
        None, help="Mask this pixel value (use 0 on NYC int DEM to exclude water)."),
):
    """Summary statistics over valid cells."""
    arr, _ = io.read(path, max_size=max_size, mask_values=mask_value)
    s = inspect_mod.stats(arr)
    t = Table(title=f"stats: {path}")
    t.add_column("metric")
    t.add_column("value", justify="right")
    for k, v in s.as_dict().items():
        t.add_row(k, f"{v:,.3f}" if isinstance(v, float) else str(v))
    console.print(t)


@app.command()
def render(
    path: Path,
    out: Path = typer.Option(..., "-o", "--out", help="Output PNG path."),
    cmap: str = typer.Option("terrain", help="Matplotlib colormap."),
    max_size: int = typer.Option(2048, help="Downsample longest side to N px."),
    no_hillshade: bool = typer.Option(False, help="Disable shaded-relief blend."),
    mask_value: Optional[float] = typer.Option(
        None, help="Mask this pixel value (use 0 on NYC int DEM to hide water)."),
):
    """Render a shaded-relief elevation PNG."""
    arr, transform = io.read(path, max_size=max_size, mask_values=mask_value)
    viz.save_png(arr, out, cmap=cmap, hillshade_blend=not no_hillshade,
                 cellsize=abs(transform.a), title=str(path.name))
    console.print(f"[green]wrote[/green] {out}")


@app.command(name="ndsm")
def ndsm_cmd(
    dsm: Path = typer.Argument(..., help="DSM (surface) tile."),
    dem: Path = typer.Argument(..., help="DEM (bare-earth) tile."),
    out: Optional[Path] = typer.Option(None, "-o", "--out", help="Output GeoTIFF."),
    max_size: int = typer.Option(2048, help="Downsample longest side to N px."),
):
    """Compute nDSM (above-ground heights) = DSM - DEM."""
    result, transform = ndsm.from_files(dsm, dem, max_size=max_size)
    s = inspect_mod.stats(result)
    console.print(f"nDSM height (ft): min={s.min:.1f} mean={s.mean:.1f} max={s.max:.1f}")
    if out:
        _write_geotiff(out, result, transform, dsm)
        console.print(f"[green]wrote[/green] {out}")


@app.command()
def sample(
    path: Path,
    coords: list[float] = typer.Argument(..., help="Flat lon lat lon lat ... list."),
    epsg: int = typer.Option(4326, help="EPSG of input coords (4326 = lon/lat)."),
):
    """Sample elevation at one or more coordinates."""
    pts = list(zip(coords[0::2], coords[1::2]))
    vals = query.sample_points(path, pts, src_epsg=epsg)
    for (x, y), v in zip(pts, vals):
        console.print(f"({x}, {y}) -> {'nodata' if v is None else f'{v:.2f} ft'}")


@app.command()
def flood(
    dem: Path,
    level: list[float] = typer.Option(..., "--level", "-l", help="Water level(s), ft NAVD88."),
    connected: bool = typer.Option(True, help="Only flood cells connected to a water source."),
    baseline: float = typer.Option(0.0, help="Existing waterline elev; cells <= it are water (0 for NYC int DEM)."),
    bounds: Optional[str] = typer.Option(None, help="AOI 'left,bottom,right,top' in the raster CRS."),
    aoi_epsg: Optional[int] = typer.Option(None, help="EPSG of --bounds if not the raster CRS (e.g. 4326)."),
    max_size: int = typer.Option(2048, help="Downsample longest side to N px."),
    out: Optional[Path] = typer.Option(None, "-o", "--out", help="Write flood-depth GeoTIFF (first level)."),
):
    """Bathtub flood inundation at one or more water levels.

    Reports total inundation (incl. standing water) and dry-land flooded (the
    incremental impact). On the NYC integer DEM keep baseline=0 (water is stored as 0).
    """
    box = _parse_bounds(dem, bounds, aoi_epsg)
    arr, transform = io.read(dem, bounds=box, max_size=max_size)
    cell = abs(transform.a)
    results = flood_mod.scenarios(arr, level, cell_size=cell, connected=connected,
                                  baseline=baseline)
    t = Table(title=f"flood scenarios: {dem.name}  (cell={cell:.2f} ft)")
    for col in ["level_ft", "total_acres", "land_acres", "mean_depth_ft", "max_depth_ft"]:
        t.add_column(col, justify="right")
    for r in results:
        s = r.summary()
        t.add_row(f"{s['water_level']:.1f}", f"{s['flooded_area_acres']:,.1f}",
                  f"{s['land_flooded_acres']:,.1f}", f"{s['mean_depth']:.2f}",
                  f"{s['max_depth']:.2f}")
    console.print(t)
    if out and results:
        _write_geotiff(out, results[0].depth, transform, dem)
        console.print(f"[green]wrote[/green] {out} (depth at {level[0]} ft)")


def _parse_bounds(path: Path, bounds: Optional[str], aoi_epsg: Optional[int]):
    """Parse 'l,b,r,t', reprojecting from aoi_epsg into the raster CRS if given."""
    if not bounds:
        return None
    l, b, r, t = (float(x) for x in bounds.split(","))
    if aoi_epsg is not None:
        import rasterio
        from rasterio.warp import transform as warp
        with rasterio.open(path) as ds:
            dst = ds.crs
        xs, ys = warp(f"EPSG:{aoi_epsg}", dst, [l, r], [b, t])
        l, r = min(xs), max(xs)
        b, t = min(ys), max(ys)
    return (l, b, r, t)


@app.command()
def cog(
    src: Path,
    out: Path = typer.Option(..., "-o", "--out", help="Output COG path."),
    blocksize: int = typer.Option(512, help="Internal tile size (px)."),
    compress: str = typer.Option("DEFLATE", help="DEFLATE, LZW, or ZSTD."),
    resampling: str = typer.Option("AVERAGE", help="Overview resampling (AVERAGE/NEAREST/BILINEAR)."),
):
    """Rewrite a raster as a tiled, overview-pyramided Cloud-Optimized GeoTIFF.

    The NYC whole-city DEM ships LZW-*striped* (full-width rows), which is pessimal
    for AOI windowing — every small read decompresses full-width strips. Converting
    to a tiled COG with overviews makes windowed reads and zoomed-out viz fast.
    """
    console.print(f"converting [cyan]{src.name}[/cyan] -> tiled COG (this reads the whole raster)…")
    io.to_cog(src, out, blocksize=blocksize, compress=compress, resampling=resampling)
    console.print(f"[green]wrote[/green] {out}")


def _write_geotiff(out: Path, arr, transform, template_path: Path):
    """Write a float32 GeoTIFF borrowing CRS from a template raster."""
    import numpy as np
    import rasterio
    with rasterio.open(template_path) as src:
        crs = src.crs
    data = np.ma.filled(arr, np.nan).astype("float32")
    with rasterio.open(
        out, "w", driver="GTiff", height=data.shape[0], width=data.shape[1],
        count=1, dtype="float32", crs=crs, transform=transform,
        nodata=float("nan"), compress="deflate",
    ) as dst:
        dst.write(data, 1)


if __name__ == "__main__":
    app()
