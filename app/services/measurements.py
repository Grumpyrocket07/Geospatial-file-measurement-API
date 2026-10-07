"""Measure polygons (area) and lines (length) in metres, never in degrees.

Flow for one feature:
  1. Find the feature's centre point in longitude/latitude.
  2. Pick the UTM zone that centre falls in (a flat, metre-based map accurate for that area).
  3. Re-project the shape into that zone.
  4. Ask shapely for area / length, which are now in square metres / metres.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

AREA_TYPES = {"Polygon", "MultiPolygon"}
LENGTH_TYPES = {"LineString", "MultiLineString", "LinearRing"}
NO_MEASURE_TYPES = {"Point", "MultiPoint"}

WGS84 = "EPSG:4326"


@dataclass
class Measurement:
    status: str  # "ok" | "not_applicable" | "unsupported" | "no_geometry" | "error"
    projected_crs: str | None = None
    area_m2: float | None = None
    length_m: float | None = None
    message: str | None = None


def utm_epsg_for(lon: float, lat: float) -> str:
    """Choose the projected CRS for a location.

    Normal latitudes use UTM (6-degree-wide zones). Near the poles UTM breaks down,
    so we switch to Universal Polar Stereographic.
    """
    if lat >= 84:
        return "EPSG:32661"  # UPS North
    if lat < -80:
        return "EPSG:32761"  # UPS South
    zone = int((lon + 180) // 6) % 60 + 1
    base = 32600 if lat >= 0 else 32700
    return f"EPSG:{base + zone}"


@lru_cache(maxsize=256)
def _transformer(src: str, dst: str) -> Transformer:
    # always_xy keeps the (x=lon, y=lat) order that shapely and GeoJSON use.
    return Transformer.from_crs(CRS.from_user_input(src), CRS.from_user_input(dst), always_xy=True)


def measure_geometry(geom: BaseGeometry | None, source_crs: str) -> Measurement:
    if geom is None or geom.is_empty:
        return Measurement(status="no_geometry", message="Feature has no geometry.")

    gtype = geom.geom_type
    if gtype in NO_MEASURE_TYPES:
        return Measurement(status="not_applicable", message="Points have no area or length.")
    if gtype not in AREA_TYPES | LENGTH_TYPES:
        return Measurement(
            status="unsupported",
            message=f"Measurement is not supported for geometry type '{gtype}'.",
        )

    try:
        # Step 1: centre in lon/lat (needed even if the file is already projected).
        to_wgs84 = _transformer(source_crs, WGS84)
        centre = transform(to_wgs84.transform, geom).centroid
        if not (-180 <= centre.x <= 180 and -90 <= centre.y <= 90):
            return Measurement(status="error", message="Coordinates fall outside valid lon/lat range.")

        # Steps 2-3: pick UTM zone and project into it.
        target = utm_epsg_for(centre.x, centre.y)
        projected = transform(_transformer(source_crs, target).transform, geom)

        # Step 4: measure in metres.
        if gtype in AREA_TYPES:
            return Measurement(status="ok", projected_crs=target, area_m2=projected.area)
        return Measurement(status="ok", projected_crs=target, length_m=projected.length)
    except Exception as exc:  # one bad feature must not sink the whole file
        return Measurement(status="error", message=f"Could not measure feature: {exc}")
