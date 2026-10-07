"""Generate small sample files in ./samples (run: python scripts/make_samples.py)."""
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point, box

out = Path(__file__).resolve().parent.parent / "samples"
out.mkdir(exist_ok=True)

# KML in lat/lon (EPSG:4326), near Bengaluru: a ~1 km square plot, a ~1.1 km road, a tree.
gpd.GeoDataFrame(
    {"Name": ["Plot A", "Road B", "Tree C"]},
    geometry=[
        box(77.5900, 12.9700, 77.5900 + 0.009194, 12.9700 + 0.009043),
        LineString([(77.59, 12.97), (77.59, 12.98)]),
        Point(77.59, 12.97),
    ],
    crs="EPSG:4326",
).to_file(out / "survey.kml", driver="KML")

# Shapefile in a projected CRS (UTM 43N), zipped.
shp_dir = out / "_shp"
shp_dir.mkdir(exist_ok=True)
gdf = gpd.GeoDataFrame(
    {"owner": ["Asha", "Ravi"], "parcel_id": [101, 102]},
    geometry=[box(780000, 1434000, 780500, 1434400), box(781000, 1434000, 781200, 1434200)],
    crs="EPSG:32643",
)
gdf.to_file(shp_dir / "parcels.shp")
with zipfile.ZipFile(out / "parcels_shapefile.zip", "w") as zf:
    for f in sorted(shp_dir.iterdir()):
        zf.write(f, f.name)
for f in shp_dir.iterdir():
    f.unlink()
shp_dir.rmdir()
print("Samples written to", out)
