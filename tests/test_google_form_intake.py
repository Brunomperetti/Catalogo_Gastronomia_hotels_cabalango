import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base
from app.models import ActividadAgenda, Empresa, SolicitudPrestador, SolicitudPrestadorArchivo, Usuario

VALID_INTAKE_SECRET = "test-only-secret-with-32-characters"


@pytest.fixture()
def intake_app(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = Session()
    db.add(Usuario(username="intake-admin", password_hash=main.hash_password("secret"), rol="admin", activo=True))
    db.commit()
    monkeypatch.setenv("FORM_INTAKE_SECRET", VALID_INTAKE_SECRET)
    monkeypatch.setattr(main, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(main, "INTAKE_MEDIA_DIR", tmp_path / "intake")

    def override_db():
        yield db

    main.app.dependency_overrides[main.get_db] = override_db
    client = TestClient(main.app)
    try:
        yield client, db
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
        db.close()
        engine.dispose()


@pytest.fixture()
def payload():
    return {
        "external_id": "form-response-001", "submitted_at": "2026-08-13T10:00:00Z",
        "business_type": "Alojamiento", "business_name": "Posada del Río",
        "contact": {"name": "Ana", "phone": "3541", "public_whatsapp": "3541", "email": "ana@example.com"},
        "social": {"instagram": "@posada", "facebook": "", "website": "https://example.com"},
        "location": {"address": "Cabalango", "directions": "Junto al río", "maps_url": "https://maps.example/a"},
        "description": "Hospedaje familiar", "opening_hours": "Todo el año",
        "payment_methods": ["Efectivo"], "highlights": ["Río"],
        "specific_data": {"habitaciones": 4},
        "files": {"logo": [{"drive_file_id": "abc", "name": "logo.png", "mime_type": "image/png"}], "cover": [], "gallery": [], "video": []},
        "raw": {"sheet_row": 3},
    }


def post_intake(client, payload, token=VALID_INTAKE_SECRET):
    return client.post("/api/internal/intake/google-form", json=payload, headers={"Authorization": f"Bearer {token}"})


def png_file(name="photo.png"):
    from io import BytesIO
    from PIL import Image
    output = BytesIO()
    Image.new("RGB", (8, 8), "red").save(output, "PNG")
    return name, output.getvalue(), "application/octet-stream"


def post_media(client, external_id, kind, drive_id, upload=None, token=VALID_INTAKE_SECRET):
    upload = upload or png_file()
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return client.post(f"/api/internal/intake/google-form/{external_id}/media",
                       data={"kind": kind, "drive_file_id": drive_id}, files={"file": upload}, headers=headers)


def test_intake_requires_bearer_authentication(intake_app, payload, monkeypatch):
    client, _ = intake_app
    assert client.post("/api/internal/intake/google-form", json=payload).status_code == 401
    assert post_intake(client, payload, "wrong").status_code == 401
    assert client.post("/api/internal/intake/google-form", json=payload, headers={"Authorization": "Basic abc"}).status_code == 401
    monkeypatch.delenv("FORM_INTAKE_SECRET")
    assert post_intake(client, payload).status_code == 401


def test_intake_rejects_short_configured_secret(intake_app, payload, monkeypatch):
    client, _ = intake_app
    monkeypatch.setenv("FORM_INTAKE_SECRET", "too-short")
    response = post_intake(client, payload, "too-short")
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_valid_payload_is_pending_preserved_and_does_not_publish(intake_app, payload):
    client, db = intake_app
    response = post_intake(client, payload)
    assert response.status_code == 201
    assert response.json()["status"] == "received"
    item = db.query(SolicitudPrestador).one()
    assert item.status == "pendiente"
    assert json.loads(item.raw_payload) == payload
    assert item.facebook is None
    assert db.query(Empresa).count() == 0
    assert db.query(ActividadAgenda).count() == 0


def test_external_id_is_idempotent(intake_app, payload):
    client, db = intake_app
    first = post_intake(client, payload)
    second = post_intake(client, payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == {"status": "already_received", "id": first.json()["id"]}
    assert db.query(SolicitudPrestador).count() == 1


def test_admin_lists_reviews_and_rejects_request(intake_app, payload):
    client, db = intake_app
    item_id = post_intake(client, payload).json()["id"]
    client.post("/login", data={"username": "intake-admin", "password": "secret", "next": "/admin/solicitudes"})
    listing = client.get("/admin/solicitudes")
    assert listing.status_code == 200
    assert "Posada del Río" in listing.text
    reviewed = client.post(f"/admin/solicitudes/{item_id}/revisar", data={"status": "revisando", "review_notes": "Verificar habilitación"}, follow_redirects=False)
    assert reviewed.status_code == 303
    db.expire_all()
    assert db.get(SolicitudPrestador, item_id).status == "revisando"
    rejected = client.post(f"/admin/solicitudes/{item_id}/revisar", data={"status": "rechazada", "review_notes": "Datos incompletos"}, follow_redirects=False)
    assert rejected.status_code == 303
    db.expire_all()
    item = db.get(SolicitudPrestador, item_id)
    assert item.status == "rechazada"
    assert item.review_notes == "Datos incompletos"


def test_media_auth_and_missing_request(intake_app):
    client, _ = intake_app
    assert post_media(client, "missing", "cover", "a", token=None).status_code == 401
    assert post_media(client, "missing", "cover", "a", token="wrong").status_code == 401
    assert post_media(client, "missing", "cover", "a").status_code == 404


def test_media_is_idempotent_private_and_does_not_publish_or_change_state(intake_app, payload):
    client, db = intake_app
    item_id = post_intake(client, payload).json()["id"]
    first = post_media(client, payload["external_id"], "cover", "cover-1", png_file("../../evil.png"))
    second = post_media(client, payload["external_id"], "cover", "cover-1")
    assert first.status_code == 201
    assert second.status_code == 200 and second.json()["status"] == "already_received"
    record = db.query(SolicitudPrestadorArchivo).one()
    assert record.original_name == "evil.png" and ".." not in record.stored_name
    assert db.query(Empresa).count() == db.query(ActividadAgenda).count() == 0
    assert db.get(SolicitudPrestador, item_id).status == "pendiente"
    assert client.get(f"/media/{record.relative_path}").status_code == 404


def test_media_limits_types_and_size(intake_app, payload):
    client, db = intake_app
    post_intake(client, payload)
    for index in range(5):
        assert post_media(client, payload["external_id"], "gallery", f"gallery-{index}").status_code == 201
    assert post_media(client, payload["external_id"], "gallery", "gallery-6").status_code == 409
    assert post_media(client, payload["external_id"], "logo", "logo-1").status_code == 201
    assert post_media(client, payload["external_id"], "logo", "logo-2").status_code == 409
    mp4 = ("clip.mp4", b"\0\0\0\x18ftypisom" + b"0" * 20, "image/png")
    assert post_media(client, payload["external_id"], "video", "video-1", mp4).status_code == 201
    assert post_media(client, payload["external_id"], "video", "video-2", mp4).status_code == 409
    assert post_media(client, payload["external_id"], "cover", "bad", ("fake.jpg", b"not an image", "image/jpeg")).status_code == 415
    assert post_media(client, payload["external_id"], "cover", "large", ("big.png", b"x" * (main.INTAKE_MEDIA_MAX_BYTES + 1), "image/png")).status_code == 413


def test_admin_file_access_is_authenticated_and_scoped(intake_app, payload):
    client, db = intake_app
    first_id = post_intake(client, payload).json()["id"]
    record_id = post_media(client, payload["external_id"], "cover", "cover").json()["id"]
    other = dict(payload, external_id="other-response")
    other_id = post_intake(client, other).json()["id"]
    url = f"/admin/solicitudes/{first_id}/archivo/{record_id}"
    assert client.get(url, follow_redirects=False).status_code in {302, 303, 307}
    client.post("/login", data={"username": "intake-admin", "password": "secret", "next": url}, follow_redirects=False)
    response = client.get(url)
    assert response.status_code == 200 and response.headers["content-type"].startswith("image/png")
    assert client.get(f"/admin/solicitudes/{other_id}/archivo/{record_id}").status_code == 404


def test_specific_data_unicode_is_human_readable(intake_app, payload):
    client, _ = intake_app
    payload["specific_data"] = {"¿Tienen delivery?": "Sí"}
    item_id = post_intake(client, payload).json()["id"]
    client.post("/login", data={"username": "intake-admin", "password": "secret", "next": f"/admin/solicitudes/{item_id}"}, follow_redirects=False)
    html = client.get(f"/admin/solicitudes/{item_id}").text
    assert "¿Tienen delivery?" in html and "Sí" in html and "Pendiente de importar" in html
