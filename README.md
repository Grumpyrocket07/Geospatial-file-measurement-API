# Geospatial File Measurement API

A FastAPI backend that accepts a **KML** file or a **zipped Shapefile**, extracts every feature, and returns **area** (polygons) and **length** (lines) in metres, calculated in a proper projected coordinate system instead of raw latitude/longitude degrees.

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- API: http://localhost:8000
- Interactive docs (Swagger): http://localhost:8000/docs

Run the tests:

```bash
pytest
```

Try it with the bundled samples (regenerate with `python scripts/make_samples.py`):

```bash
curl -X POST http://localhost:8000/api/files/ -F "file=@samples/survey.kml"
```

**Docker (optional)**

```bash
docker build -t geo-api . && docker run -p 8000:8000 -v geo_data:/data geo-api
```

**Configuration (environment variables)**

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./geo_api.db` | SQLAlchemy database URL |
| `UPLOAD_DIR` | `./uploads` | Where uploaded files are stored |
| `MAX_UPLOAD_MB` | `50` | Maximum upload size |

## API

### `POST /api/files/` — upload and process

Multipart form field `file`: a `.kml`, or a `.zip` containing one Shapefile (`.shp`, `.shx`, `.dbf`, `.prj`).

```bash
curl -X POST http://localhost:8000/api/files/ -F "file=@samples/survey.kml"
```

`201 Created`
```json
{
  "id": "a0fd1fa84c324590a73acf6cf921409a",
  "filename": "survey.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "error": null
}
```

| Code | When |
|---|---|
| 201 | Processed successfully |
| 413 | File larger than `MAX_UPLOAD_MB` |
| 415 | Not a `.kml` or `.zip` |
| 422 | File accepted but unreadable (corrupt zip, missing `.prj`, empty file…). Body includes `detail` and the file `id`; the record is stored with status `FAILED` |

### `GET /api/files/{id}/` — file information

Returns the same object as the upload response. `404` if the id is unknown.

### `GET /api/files/{id}/measurements/` — measurements

Query params: `limit` (1–1000, default 100), `offset` (default 0). The `summary` always covers the whole file, not just the current page.

```json
{
  "file_id": "a0fd1fa84c324590a73acf6cf921409a",
  "crs": "EPSG:4326",
  "total": 3, "limit": 100, "offset": 0,
  "summary": { "total_area_m2": 999097.409, "total_length_m": 1106.941, "measured": 2, "skipped": 1 },
  "measurements": [
    { "feature_index": 0, "geometry_type": "Polygon", "status": "ok",
      "projected_crs": "EPSG:32643", "area_m2": 999097.409, "area_hectares": 99.909741,
      "length_m": null, "length_km": null, "message": null },
    { "feature_index": 1, "geometry_type": "LineString", "status": "ok",
      "projected_crs": "EPSG:32643", "area_m2": null, "area_hectares": null,
      "length_m": 1106.941, "length_km": 1.106941, "message": null },
    { "feature_index": 2, "geometry_type": "Point", "status": "not_applicable",
      "projected_crs": null, "area_m2": null, "area_hectares": null,
      "length_m": null, "length_km": null, "message": "Points have no area or length." }
  ]
}
```

Per-feature `status` values: `ok`, `not_applicable` (points), `unsupported` (e.g. GeometryCollection), `no_geometry`, `error`. A problem with one feature never fails the whole request. Returns `409` if the file's status is not `COMPLETED`.

### `GET /api/files/{id}/features/` — extracted features (extra)

Returns each feature's index, geometry type, GeoJSON geometry (in the file's original CRS), CRS and properties. Same `limit`/`offset` pagination.

## Architecture

```
app/
  main.py              FastAPI app, startup (creates tables)
  api/files.py         HTTP layer: validation, status codes, response shaping
  services/parser.py   Reads KML / Shapefile zip -> plain feature objects
  services/measurements.py   CRS selection + area/length maths
  services/processing.py     Orchestrates parse -> measure -> save
  models.py, schemas.py, database.py, config.py, errors.py
tests/                 Unit tests (parser, maths) + API tests
```

**File-processing flow**
1. Upload is checked (extension, size limit) and streamed to disk under a server-generated name (the client's filename is never used as a path).
2. A `files` row is created with status `PROCESSING`.
3. The parser reads the file. Shapefiles are read directly from inside the zip (no extraction to disk). KML layers are all read and combined.
4. Every feature is measured and saved; the file becomes `COMPLETED`. If the file is unreadable it becomes `FAILED` with an explanatory message.

**Measurement flow (per feature)**
1. Find the feature's centroid in longitude/latitude.
2. Choose the projected CRS for that location.
3. Re-project the geometry into it.
4. Read `.area` / `.length` (now in m² / m). Multi-part geometries are handled as one shape.

**CRS handling**
- KML is always WGS84 (EPSG:4326). A Shapefile's CRS comes from its `.prj`; if missing, the upload fails with a clear message rather than guessing.
- Measurements are never computed on degrees. Each feature is projected to its **UTM zone** (EPSG:326xx north / 327xx south), or Universal Polar Stereographic beyond 84°N / 80°S.
- Files already in a projected CRS are supported too: the geometry is transformed from its own CRS.
- Altitude (Z) values are dropped; measurements are ground-plane.

## Design Decisions

| Decision | Why | Alternatives considered |
|---|---|---|
| **FastAPI** | Little boilerplate, typed responses, free Swagger docs | Django + DRF: heavier for a small service |
| **UTM zone per feature** | Accurate for local areas, simple, widely understood | One equal-area projection for everything (more distortion for lines); geodesic calculation with `pyproj.Geod` (most accurate, but harder to explain and not "projected") |
| **Zone chosen per feature, not per file** | A file can span zones; each shape gets its own best zone | One zone per file (simpler, but wrong for large or spread-out files) |
| **SQLite + SQLAlchemy** | Zero setup for reviewers; the URL is configurable | PostGIS (best for spatial queries; overkill here) |
| **Synchronous processing** | Files are small; keeps the flow easy to follow. The `status` field already allows async later | Celery/RQ background jobs |
| **Read zip in place** | Avoids path-traversal risks; added zip-size and file-count checks against zip bombs | Extract to a temp directory |
| **Store measurements with the feature** | One query serves `/measurements/`; no recomputation | Compute on every GET |
| **Fail soft per feature** | One bad geometry should not hide the other 119 | Fail the whole file |

**Accuracy:** UTM stretches area slightly away from the zone's centre line (up to roughly 0.2%). Tests compare against an independent geodesic calculation to confirm results stay within that bound.

## Learnings

- Latitude/longitude are angles, so "area in degrees" is meaningless; measurements need a metre-based projection.
- Every flat map distorts something, so "which projection" is a real accuracy trade-off, and I checked it against a geodesic result instead of trusting it.
- Real files are messy (missing `.prj`, empty geometries, Z values, `NaN` attributes, multi-layer KML), so most of the code is defensive handling, not maths.
- Tests with known answers (a 1 km square should be about 1,000,000 m²) caught more than reading code did.

## Future Scope

- Background processing (task queue) and progress status for large files
- Geodesic (ellipsoidal) measurement as a switchable, higher-accuracy mode
- More formats: GeoJSON, GeoPackage, `.kmz`
- PostGIS storage for spatial queries (features within a bounding box)
- Authentication, per-user files, and file deletion/expiry
- Alembic migrations, structured logging, and CI via GitHub Actions
