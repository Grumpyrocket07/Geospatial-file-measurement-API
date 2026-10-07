import zipfile

import pytest
from pyproj import Geod
from shapely.geometry import GeometryCollection, LineString, Point, box

from app.errors import InvalidArchiveError, MissingCRSError, UnsupportedFileTypeError
from app.services.measurements import measure_geometry, utm_epsg_for
from app.services.parser import parse_geofile


def test_utm_zone_selection():
    assert utm_epsg_for(77.59, 12.97) == "EPSG:32643"   # Bengaluru, north
    assert utm_epsg_for(-58.4, -34.6) == "EPSG:32721"   # Buenos Aires, south
    assert utm_epsg_for(0, 89) == "EPSG:32661"          # near the North Pole


def test_kml_parsed(kml_file):
    parsed = parse_geofile(kml_file)
    assert parsed.crs == "EPSG:4326"
    assert [f.geometry_type for f in parsed.features] == ["Polygon", "LineString", "Point"]
    assert parsed.features[0].properties["Name"] == "plot"


def test_polygon_area_close_to_one_square_km(kml_file):
    feat = parse_geofile(kml_file).features[0]
    m = measure_geometry(feat.geometry, "EPSG:4326")
    assert m.status == "ok" and m.projected_crs == "EPSG:32643"
    assert m.area_m2 == pytest.approx(1_000_000, rel=0.01)


def test_matches_independent_geodesic_calculation(kml_file):
    # UTM distorts area slightly away from its centre line (up to ~0.2%), so we
    # compare against a globe-exact (geodesic) answer with that tolerance.
    feat = parse_geofile(kml_file).features[0]
    projected = measure_geometry(feat.geometry, "EPSG:4326").area_m2
    geodesic = abs(Geod(ellps="WGS84").geometry_area_perimeter(feat.geometry)[0])
    assert projected == pytest.approx(geodesic, rel=0.002)


def test_line_length(kml_file):
    feat = parse_geofile(kml_file).features[1]
    m = measure_geometry(feat.geometry, "EPSG:4326")
    assert m.length_m == pytest.approx(1105, rel=0.01)  # 0.01 deg lat ~ 1.105 km


def test_degrees_are_not_used_directly():
    sq = box(77.59, 12.97, 77.60, 12.98)
    assert sq.area < 0.001  # raw "degrees squared" is a meaningless tiny number
    assert measure_geometry(sq, "EPSG:4326").area_m2 > 1_000_000


def test_point_and_unsupported_handled_gracefully():
    assert measure_geometry(Point(77, 12), "EPSG:4326").status == "not_applicable"
    gc = GeometryCollection([Point(77, 12), LineString([(77, 12), (77.1, 12.1)])])
    assert measure_geometry(gc, "EPSG:4326").status == "unsupported"
    assert measure_geometry(None, "EPSG:4326").status == "no_geometry"


def test_projected_shapefile(shp_zip):
    parsed = parse_geofile(shp_zip)
    assert parsed.crs == "EPSG:32643"
    assert parsed.features[0].properties == {"owner": "A", "acres": None}
    m = measure_geometry(parsed.features[0].geometry, parsed.crs)
    assert m.area_m2 == pytest.approx(1_000_000, rel=0.002)


def test_rejects_bad_inputs(tmp_path):
    txt = tmp_path / "a.txt"
    txt.write_text("hi")
    with pytest.raises(UnsupportedFileTypeError):
        parse_geofile(txt)

    fake = tmp_path / "fake.zip"
    fake.write_text("not a zip")
    with pytest.raises(InvalidArchiveError):
        parse_geofile(fake)

    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("readme.txt", "no shapefile here")
    with pytest.raises(InvalidArchiveError):
        parse_geofile(empty)


def test_missing_prj_is_reported(shp_zip, tmp_path):
    stripped = tmp_path / "noprj.zip"
    with zipfile.ZipFile(shp_zip) as src, zipfile.ZipFile(stripped, "w") as dst:
        for n in src.namelist():
            if not n.endswith(".prj"):
                dst.writestr(n, src.read(n))
    with pytest.raises(MissingCRSError):
        parse_geofile(stripped)
