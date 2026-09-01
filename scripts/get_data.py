#!/usr/bin/env python
"""Download the NYC 1-foot integer DEM and build the COG the notebooks expect.

Populates ``data/nyc_dem_1ft_int_cog.tif`` (a tiled Cloud-Optimized GeoTIFF) from
NYC's published integer raster, so a fresh checkout can run the notebooks.

Steps (each skipped if its output already exists):
  1. download  NYC_DEM_1ft_Int.zip           (~3.2 GB)
  2. extract   ...NYC_int.tif                 (~3.4 GB, LZW-striped)
  3. convert   -> nyc_dem_1ft_int_cog.tif     (~1.2 GB, tiled + overviews)
  4. cleanup   remove the zip + striped tif   (unless --keep-intermediate)

Run from anywhere:  ``uv run python scripts/get_data.py``

The integer raster (whole feet, uint16) is the default because the float raster is a
99 GB ERDAS IMAGINE dataset that needs ~200 GB of disk. See ``data/README.md``.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
COG = DATA_DIR / "nyc_dem_1ft_int_cog.tif"
STRIPED = DATA_DIR / "nyc_dem_1ft_int.tif"
ZIP = DATA_DIR / "NYC_DEM_1ft_Int.zip"
DEFAULT_URL = (
    "https://sa-static-customer-assets-us-east-1-fedramp-prod.s3.amazonaws.com/"
    "data.cityofnewyork.us/NYC_DEM_1ft_Int.zip"
)
MEMBER_TIF = "DEM_LiDAR_1ft_2010_Improved_NYC_int.tif"


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024


def free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1e9


def download(url: str, dst: Path) -> None:
    """Stream ``url`` to ``dst`` (via a .part file) with a simple progress line."""
    part = dst.with_suffix(dst.suffix + ".part")
    with urllib.request.urlopen(url) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        with open(part, "wb") as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)
                done += len(chunk)
                pct = f"{done / total * 100:5.1f}%" if total else "  ? "
                print(f"\r  downloading {pct}  {_human(done)}", end="", flush=True)
    print()
    part.rename(dst)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=DEFAULT_URL, help="source zip URL")
    ap.add_argument("--keep-intermediate", action="store_true",
                    help="keep the downloaded zip and striped tif after building the COG")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even if the COG already exists")
    args = ap.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    if COG.exists() and not args.force:
        print(f"✓ already present: {COG}  ({_human(COG.stat().st_size)})")
        print("  (use --force to rebuild)")
        return 0

    # 1 + 2: obtain the striped GeoTIFF (download + extract) unless it's already here.
    if not STRIPED.exists():
        if free_gb(DATA_DIR) < 8:
            print(f"! only {free_gb(DATA_DIR):.1f} GB free in {DATA_DIR}; need ~8 GB "
                  "(3.2 GB zip + 3.4 GB tif). Free space or pass a bigger disk.",
                  file=sys.stderr)
            return 1
        if not ZIP.exists():
            print(f"downloading {args.url}")
            download(args.url, ZIP)
        print(f"extracting {MEMBER_TIF}")
        with zipfile.ZipFile(ZIP) as z:
            with z.open(MEMBER_TIF) as src, open(STRIPED, "wb") as out:
                shutil.copyfileobj(src, out, length=1 << 20)

    # 3: convert to a tiled COG with overviews.
    print(f"building COG -> {COG.name}  (reads the whole raster; a few minutes)…")
    from floodar import io
    io.to_cog(STRIPED, COG)
    print(f"✓ built {COG}  ({_human(COG.stat().st_size)})")

    # 4: reclaim space.
    if not args.keep_intermediate:
        for p in (ZIP, STRIPED):
            if p.exists():
                p.unlink()
                print(f"  removed intermediate {p.name}")

    print(f"\nDone. Notebooks can now read {COG.relative_to(DATA_DIR.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
