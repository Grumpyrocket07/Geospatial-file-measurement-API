"""Glue: parse a stored file, measure every feature, save results."""
from pathlib import Path

from sqlalchemy.orm import Session

from app.errors import GeoFileError
from app.models import FeatureRecord, UploadedFile
from app.services.measurements import measure_geometry
from app.services.parser import parse_geofile


def process_file(db: Session, record: UploadedFile) -> UploadedFile:
    """Fill in `record` and its features. Never raises for bad user files; marks FAILED instead."""
    try:
        parsed = parse_geofile(Path(record.stored_path))
    except GeoFileError as exc:
        record.status, record.error = "FAILED", str(exc)
        db.commit()
        return record

    for feat in parsed.features:
        m = measure_geometry(feat.geometry, parsed.crs)
        record.features.append(
            FeatureRecord(
                index=feat.index,
                geometry_type=feat.geometry_type,
                crs=parsed.crs,
                geometry=feat.geometry_geojson(),
                properties=feat.properties,
                measurement_status=m.status,
                projected_crs=m.projected_crs,
                area_m2=m.area_m2,
                length_m=m.length_m,
                measurement_message=m.message,
            )
        )
    record.crs = parsed.crs
    record.feature_count = len(parsed.features)
    record.status = "COMPLETED"
    db.commit()
    return record
