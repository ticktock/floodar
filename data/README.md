# data/ (git-ignored)

NYC LiDAR elevation rasters live here. Downloaded from NYC OpenData:
https://data.cityofnewyork.us/City-Government/1-foot-Digital-Elevation-Model-DEM-/dpc8-z3jc

- `nyc_dem_1ft_int_cog.tif` — **the working file**: 1-ft integer DEM, whole city,
  tiled Cloud-Optimized GeoTIFF with overviews (EPSG:2263, uint16, feet NAVD88).
  `0` = water / outside-city / 0-ft ground (no nodata tag).

## Reproducing the download

```bash
curl -o NYC_DEM_1ft_Int.zip \
  https://sa-static-customer-assets-us-east-1-fedramp-prod.s3.amazonaws.com/data.cityofnewyork.us/NYC_DEM_1ft_Int.zip
python -c "import zipfile; zipfile.ZipFile('NYC_DEM_1ft_Int.zip').extractall('.')"
uv run floodar cog DEM_LiDAR_1ft_2010_Improved_NYC_int.tif -o nyc_dem_1ft_int_cog.tif
```

Integer raster: 3.2 GB zip → 3.4 GB striped tif → 1.2 GB tiled COG. The float raster is
26 GB zip → 99 GB ERDAS IMAGINE and needs ~200 GB disk; only grab it if you need
sub-foot vertical precision.
