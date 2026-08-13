import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base
from app.models import ActividadAgenda, Empresa, SolicitudPrestador, Usuario


@pytest.fixture()
def intake_app(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = Session()
    db.add(Usuario(username="intake-admin", password_hash=main.hash_password("secret"), rol="admin", activo=True))
    db.commit()
    monkeypatch.setenv("FORM_INTAKE_SECRET", "test-only-secret")

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


def post_intake(client, payload, token="test-only-secret"):
    return client.post("/api/internal/intake/google-form", json=payload, headers={"Authorization": f"Bearer {token}"})


def test_intake_requires_bearer_authentication(intake_app, payload, monkeypatch):
    client, _ = intake_app
    assert client.post("/api/internal/intake/google-form", json=payload).status_code == 401
    assert post_intake(client, payload, "wrong").status_code == 401
    assert client.post("/api/internal/intake/google-form", json=payload, headers={"Authorization": "Basic abc"}).status_code == 401
    monkeypatch.delenv("FORM_INTAKE_SECRET")
    assert post_intake(client, payload).status_code == 401


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
