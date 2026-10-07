import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _upload(client, path, name=None):
    with open(path, "rb") as f:
        return client.post("/api/files/", files={"file": (name or path.name, f)})


def test_kml_end_to_end(client, kml_file):
    r = _upload(client, kml_file)
    assert r.status_code == 201
    info = r.json()
    assert info["filename"] == "survey.kml" and info["feature_count"] == 3
    assert info["crs"] == "EPSG:4326" and info["status"] == "COMPLETED"

    assert client.get(f"/api/files/{info['id']}/").json() == info

    m = client.get(f"/api/files/{info['id']}/measurements/").json()
    by_type = {x["geometry_type"]: x for x in m["measurements"]}
    assert by_type["Polygon"]["area_m2"] == pytest.approx(1_000_000, rel=0.01)
    assert by_type["Polygon"]["projected_crs"] == "EPSG:32643"
    assert by_type["LineString"]["length_m"] == pytest.approx(1105, rel=0.01)
    assert by_type["Point"]["status"] == "not_applicable"
    assert m["summary"]["measured"] == 2 and m["summary"]["skipped"] == 1


def test_features_endpoint_and_pagination(client, kml_file):
    fid = _upload(client, kml_file).json()["id"]
    r = client.get(f"/api/files/{fid}/features/", params={"limit": 2}).json()
    assert r["total"] == 3 and len(r["features"]) == 2
    assert r["features"][0]["geometry"]["type"] == "Polygon"
    assert r["features"][0]["properties"]["Name"] == "plot"
    page2 = client.get(f"/api/files/{fid}/measurements/", params={"limit": 2, "offset": 2}).json()
    assert len(page2["measurements"]) == 1


def test_shapefile_zip(client, shp_zip):
    r = _upload(client, shp_zip)
    assert r.status_code == 201 and r.json()["crs"] == "EPSG:32643"
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()
    assert m["measurements"][0]["area_hectares"] == pytest.approx(100, rel=0.002)


def test_unknown_id_404(client):
    assert client.get("/api/files/nope/").status_code == 404
    assert client.get("/api/files/nope/measurements/").status_code == 404


def test_wrong_extension_415(client, tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("hi")
    assert _upload(client, p).status_code == 415


def test_corrupt_zip_is_422_and_recorded_as_failed(client, tmp_path):
    p = tmp_path / "bad.zip"
    p.write_text("not a zip")
    r = _upload(client, p)
    assert r.status_code == 422 and r.json()["status"] == "FAILED"
    fid = r.json()["id"]
    assert client.get(f"/api/files/{fid}/").json()["status"] == "FAILED"
    assert client.get(f"/api/files/{fid}/measurements/").status_code == 409


def test_size_limit(client, kml_file, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    assert _upload(client, kml_file).status_code == 413
