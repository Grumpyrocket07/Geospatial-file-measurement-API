"""Read a .kml or zipped Shapefile and turn it into plain Python feature objects.

This module only *reads*. It never measures anything, which keeps it easy to test.
"""
from __future__ import annotations

import json
import math
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely import force_2d
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from app.errors import (
    EmptyFileError,
    InvalidArchiveError,
    MissingCRSError,
    UnsupportedFileTypeError,
)

MAX_ZIP_MEMBERS = 500
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # guards against "zip bombs"


@dataclass
class ParsedFeature:
    index: int
    geometry_type: str
    geometry: BaseGeometry | None  # shapely object, in the file's own CRS
    properties: dict[str, Any] = field(default_factory=dict)

    def geometry_geojson(self) -> dict | None:
        return mapping(self.geometry) if self.geometry is not None else None


@dataclass
class ParsedFile:
    crs: str  # e.g. "EPSG:4326"
    features: list[ParsedFeature]


# ---------------------------------------------------------------- public API
def parse_geofile(path: Path) -> ParsedFile:
    """Dispatch on file extension and return features + CRS."""
    suffix = path.suffix.lower()
    if suffix == ".kml":
        return _parse_kml(path)
    if suffix == ".zip":
        return _parse_shapefile_zip(path)
    raise UnsupportedFileTypeError(
        f"Unsupported file type '{suffix}'. Upload a .kml or a .zip containing a Shapefile."
    )


# ------------------------------------------------------------------- KML
def _parse_kml(path: Path) -> ParsedFile:
    # A KML can hold several layers (folders). Read every one and stack them.
    try:
        layers = [name for name, _ in pyogrio.list_layers(path)]
        frames = [gpd.read_file(path, layer=name, engine="pyogrio") for name in layers]
    except Exception as exc:  # GDAL raises assorted errors for malformed XML
        raise InvalidArchiveError(f"Could not read KML: {exc}") from exc

    frames = [f for f in frames if len(f) > 0]
    if not frames:
        raise EmptyFileError("The KML contains no features.")
    gdf = pd.concat(frames, ignore_index=True)

    # KML is defined to be WGS84 longitude/latitude.
    return _to_parsed_file(gdf, crs="EPSG:4326")


# ------------------------------------------------------------- Shapefile
def _parse_shapefile_zip(path: Path) -> ParsedFile:
    # We read straight out of the zip with GDAL's zip support; nothing is extracted
    # to disk, which removes the whole "path traversal" class of attacks.
    _validate_zip(path)
    shp_name = _find_shp(path)
    try:
        gdf = gpd.read_file(f"zip://{path}!{shp_name}", engine="pyogrio")
    except Exception as exc:
        raise InvalidArchiveError(f"Could not read Shapefile: {exc}") from exc

    if gdf.crs is None:
        raise MissingCRSError(
            "The Shapefile has no .prj file, so its coordinate system is unknown. "
            "Add the .prj file and upload again."
        )
    if len(gdf) == 0:
        raise EmptyFileError("The Shapefile contains no features.")

    epsg = gdf.crs.to_epsg()
    return _to_parsed_file(gdf, crs=f"EPSG:{epsg}" if epsg else gdf.crs.to_string())


def _validate_zip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_MEMBERS:
                raise InvalidArchiveError("Zip contains too many files.")
            if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
                raise InvalidArchiveError("Zip is too large once uncompressed.")
            if zf.testzip() is not None:
                raise InvalidArchiveError("Zip is corrupt.")
    except zipfile.BadZipFile as exc:
        raise InvalidArchiveError("The file is not a valid zip archive.") from exc


def _find_shp(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
    shps = [n for n in names if n.lower().endswith(".shp") and "__MACOSX" not in n]
    if not shps:
        raise InvalidArchiveError("No .shp file found inside the zip.")
    if len(shps) > 1:
        raise InvalidArchiveError(
            f"Zip contains {len(shps)} Shapefiles; upload one Shapefile per zip."
        )
    stem = shps[0][:-4]
    lowered = {n.lower() for n in names}
    for required in (".shx", ".dbf"):
        if (stem + required).lower() not in lowered:
            raise InvalidArchiveError(f"Shapefile is missing its {required} companion file.")
    return shps[0]


# --------------------------------------------------------------- helpers
def _to_parsed_file(gdf: gpd.GeoDataFrame, crs: str) -> ParsedFile:
    features: list[ParsedFeature] = []
    geom_col = gdf.geometry.name
    prop_cols = [c for c in gdf.columns if c != geom_col]
    for i, (_, row) in enumerate(gdf.iterrows()):
        geom = row[geom_col]
        if geom is not None and geom.is_empty:
            geom = None
        if geom is not None:
            geom = force_2d(geom)  # KML often carries altitude; we only measure on the ground
        features.append(
            ParsedFeature(
                index=i,
                geometry_type=geom.geom_type if geom is not None else "None",
                geometry=geom,
                properties={c: _json_safe(row[c]) for c in prop_cols},
            )
        )
    return ParsedFile(crs=crs, features=features)


def _json_safe(value: Any) -> Any:
    """Attribute values can be NaN, numpy numbers or timestamps; make them JSON-friendly."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar -> python scalar
        value = value.item()
        if isinstance(value, float) and math.isnan(value):
            return None
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
