from typing import Any, Optional

from pydantic import BaseModel


class FileInfo(BaseModel):
    id: str
    filename: str
    feature_count: int
    crs: Optional[str]
    status: str
    error: Optional[str] = None


class FeatureOut(BaseModel):
    index: int
    geometry_type: str
    crs: str
    geometry: Optional[dict[str, Any]]
    properties: dict[str, Any]


class FeaturesResponse(BaseModel):
    file_id: str
    total: int
    limit: int
    offset: int
    features: list[FeatureOut]


class MeasurementOut(BaseModel):
    feature_index: int
    geometry_type: str
    status: str  # ok | not_applicable | unsupported | no_geometry | error
    projected_crs: Optional[str] = None
    area_m2: Optional[float] = None
    area_hectares: Optional[float] = None
    length_m: Optional[float] = None
    length_km: Optional[float] = None
    message: Optional[str] = None


class MeasurementSummary(BaseModel):
    total_area_m2: float
    total_length_m: float
    measured: int
    skipped: int


class MeasurementsResponse(BaseModel):
    file_id: str
    crs: Optional[str]
    total: int
    limit: int
    offset: int
    summary: MeasurementSummary
    measurements: list[MeasurementOut]
