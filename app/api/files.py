from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import FeatureRecord, UploadedFile
from app.schemas import (
    FeatureOut,
    FeaturesResponse,
    FileInfo,
    MeasurementOut,
    MeasurementsResponse,
    MeasurementSummary,
)
from app.services.processing import process_file

router = APIRouter(prefix="/api/files", tags=["files"])

ALLOWED_SUFFIXES = {".kml", ".zip"}
CHUNK = 1024 * 1024


def _get_file_or_404(db: Session, file_id: str) -> UploadedFile:
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise HTTPException(404, "File not found.")
    return record


def _info(record: UploadedFile) -> FileInfo:
    return FileInfo(
        id=record.id, filename=record.filename, feature_count=record.feature_count,
        crs=record.crs, status=record.status, error=record.error,
    )


@router.post("/", status_code=201, response_model=FileInfo, responses={422: {"description": "File could not be processed"}})
def upload_file(file: UploadFile, db: Session = Depends(get_db)):
    original = Path(file.filename or "").name  # strip any directories the client sent
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(415, "Unsupported file type. Upload a .kml or a .zip containing a Shapefile.")

    record = UploadedFile(filename=original, stored_path="")
    db.add(record)
    db.flush()  # assigns record.id

    # Our own generated name is used on disk, never the client's.
    dest_dir = settings.upload_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{record.id}{suffix}"
    limit = settings.max_upload_mb * 1024 * 1024
    written = 0
    with dest.open("wb") as out:
        while chunk := file.file.read(CHUNK):
            written += len(chunk)
            if written > limit:
                out.close()
                dest.unlink(missing_ok=True)
                db.rollback()
                raise HTTPException(413, f"File exceeds the {settings.max_upload_mb} MB limit.")
            out.write(chunk)
    record.stored_path = str(dest)

    process_file(db, record)
    if record.status == "FAILED":
        return JSONResponse(status_code=422, content={"detail": record.error, **_info(record).model_dump()})
    return _info(record)


@router.get("/{file_id}/", response_model=FileInfo)
def get_file(file_id: str, db: Session = Depends(get_db)):
    return _info(_get_file_or_404(db, file_id))


@router.get("/{file_id}/features/", response_model=FeaturesResponse)
def get_features(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    record = _get_file_or_404(db, file_id)
    rows = db.scalars(
        select(FeatureRecord).where(FeatureRecord.file_id == file_id)
        .order_by(FeatureRecord.index).limit(limit).offset(offset)
    ).all()
    return FeaturesResponse(
        file_id=file_id, total=record.feature_count, limit=limit, offset=offset,
        features=[
            FeatureOut(index=r.index, geometry_type=r.geometry_type, crs=r.crs,
                       geometry=r.geometry, properties=r.properties)
            for r in rows
        ],
    )


@router.get("/{file_id}/measurements/", response_model=MeasurementsResponse)
def get_measurements(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    record = _get_file_or_404(db, file_id)
    if record.status != "COMPLETED":
        raise HTTPException(409, f"File is {record.status}; measurements are not available.")

    rows = db.scalars(
        select(FeatureRecord).where(FeatureRecord.file_id == file_id)
        .order_by(FeatureRecord.index).limit(limit).offset(offset)
    ).all()

    # Totals cover the whole file, not just this page.
    total_area, total_len, measured = db.execute(
        select(
            func.coalesce(func.sum(FeatureRecord.area_m2), 0.0),
            func.coalesce(func.sum(FeatureRecord.length_m), 0.0),
            func.count().filter(FeatureRecord.measurement_status == "ok"),
        ).where(FeatureRecord.file_id == file_id)
    ).one()

    return MeasurementsResponse(
        file_id=file_id, crs=record.crs, total=record.feature_count, limit=limit, offset=offset,
        summary=MeasurementSummary(
            total_area_m2=round(total_area, 3), total_length_m=round(total_len, 3),
            measured=measured, skipped=record.feature_count - measured,
        ),
        measurements=[
            MeasurementOut(
                feature_index=r.index, geometry_type=r.geometry_type, status=r.measurement_status,
                projected_crs=r.projected_crs,
                area_m2=_r(r.area_m2), area_hectares=_r(r.area_m2, 1e-4, 6),
                length_m=_r(r.length_m), length_km=_r(r.length_m, 1e-3, 6),
                message=r.measurement_message,
            )
            for r in rows
        ],
    )


def _r(value, factor: float = 1.0, digits: int = 3):
    return None if value is None else round(value * factor, digits)
