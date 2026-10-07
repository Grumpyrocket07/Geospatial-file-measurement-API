from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.files import router as files_router
from app.database import Base, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)  # fine for a small service; Alembic would replace this at scale
    yield


app = FastAPI(
    title="Geospatial File Measurement API",
    description="Upload a KML or zipped Shapefile and get area/length measurements in metres.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(files_router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")