import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, Polygon, box


@pytest.fixture
def kml_file(tmp_path: Path) -> Path:
    # ~1 km x 1 km square near Bengaluru, a line, and a point.
    gdf = gpd.GeoDataFrame(
        {"Name": ["plot", "road", "tree"]},
        geometry=[
            box(77.5900, 12.9700, 77.5900 + 0.009194, 12.9700 + 0.009043),
            LineString([(77.59, 12.97), (77.59, 12.98)]),
            Point(77.59, 12.97),
        ],
        crs="EPSG:4326",
    )
    path = tmp_path / "survey.kml"
    gdf.to_file(path, driver="KML")
    return path


@pytest.fixture
def shp_zip(tmp_path: Path) -> Path:
    # Same square, stored in a projected CRS (UTM 43N) to prove non-lat/lon input works.
    sq = Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    gdf = gpd.GeoDataFrame({"owner": ["A"], "acres": [None]}, geometry=[sq], crs="EPSG:32643")
    gdf.geometry = gdf.geometry.translate(xoff=780000, yoff=1434000)
    folder = tmp_path / "shp"
    folder.mkdir()
    gdf.to_file(folder / "parcels.shp")
    zpath = tmp_path / "parcels.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for f in folder.iterdir():
            zf.write(f, f.name)
    return zpath
