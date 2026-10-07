import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _new_id() -> str:
    return uuid.uuid4().hex


class UploadedFile(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="PROCESSING")  # PROCESSING | COMPLETED | FAILED
    crs: Mapped[str | None] = mapped_column(String(100), nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    features: Mapped[list["FeatureRecord"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", order_by="FeatureRecord.index"
    )


class FeatureRecord(Base):
    __tablename__ = "features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    geometry_type: Mapped[str] = mapped_column(String(50))
    crs: Mapped[str] = mapped_column(String(100))
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # GeoJSON, original CRS
    properties: Mapped[dict] = mapped_column(JSON, default=dict)

    # Measurement results live next to the feature so one query answers /measurements/.
    measurement_status: Mapped[str] = mapped_column(String(20))
    projected_crs: Mapped[str | None] = mapped_column(String(100), nullable=True)
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    measurement_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    file: Mapped[UploadedFile] = relationship(back_populates="features")
