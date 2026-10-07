"""Settings read from environment variables, with safe local defaults."""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./geo_api.db")
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", "./uploads"))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "50"))


settings = Settings()
