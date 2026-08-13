import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
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


def test_intake_accepts_matching_unicode_secret_and_rejects_wrong_token(intake_app, payload, monkeypatch):
    _, db = intake_app
    unicode_secret = "secreto-válido-para-intake-año-123456789"
    monkeypatch.setenv("FORM_INTAKE_SECRET", unicode_secret)

    async def call_endpoint(token, body):
        body_bytes = json.dumps(body).encode("utf-8")
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        request = Request({
            "type": "http", "method": "POST", "path": "/api/internal/intake/google-form",
            "headers": [(b"authorization", f"Bearer {token}".encode("latin-1"))],
        }, receive)
        return await main.receive_google_form_intake(request, db)

    response = asyncio.run(call_endpoint(unicode_secret, payload))
    assert response.status_code == 201
    assert json.loads(response.body)["status"] == "received"

    wrong = asyncio.run(call_endpoint(unicode_secret + "x", dict(payload, external_id="unicode-wrong")))
    assert wrong.status_code == 401
    assert json.loads(wrong.body) == {"detail": "Unauthorized"}


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


def test_media_removes_physical_file_when_persistence_fails(intake_app, payload, monkeypatch):
    client, db = intake_app
    item_id = post_intake(client, payload).json()["id"]
    original_commit = db.commit

    def fail_commit():
        raise RuntimeError("forced persistence failure")

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="forced persistence failure"):
        post_media(client, payload["external_id"], "cover", "orphan-test")
    monkeypatch.setattr(db, "commit", original_commit)

    assert list((main.INTAKE_MEDIA_DIR / str(item_id)).rglob("*.*")) == []
    assert db.query(SolicitudPrestadorArchivo).count() == 0
    assert db.get(SolicitudPrestador, item_id).status == "pendiente"
    assert db.query(Empresa).count() == 0
    assert db.query(ActividadAgenda).count() == 0


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


def authorized_payload(payload, **changes):
    body = json.loads(json.dumps(payload))
    body["specific_data"].update({
        "autorización_publicacion": "Sí, autorizo",
        "confirmacion_datos": "Sí, confirmo",
    })
    body.update(changes)
    return body


def login_admin(client):
    client.post("/login", data={"username": "intake-admin", "password": "secret", "next": "/admin/solicitudes"})


def test_conversion_requires_admin_and_missing_is_404(intake_app, payload):
    client, _ = intake_app
    item_id = post_intake(client, authorized_payload(payload)).json()["id"]
    assert client.post(f"/admin/solicitudes/{item_id}/convertir", follow_redirects=False).status_code in {302, 303, 307}
    login_admin(client)
    assert client.post("/admin/solicitudes/9999/convertir").status_code == 404


@pytest.mark.parametrize("field,message", [
    ("autorización_publicacion", "autorización"),
    ("confirmacion_datos", "confirmación"),
])
def test_conversion_requires_explicit_consent(intake_app, payload, field, message):
    client, db = intake_app
    body = authorized_payload(payload)
    body["specific_data"].pop(field)
    item_id = post_intake(client, body).json()["id"]
    login_admin(client)
    response = client.post(f"/admin/solicitudes/{item_id}/convertir", follow_redirects=True)
    assert message in response.text
    assert db.query(Empresa).count() == 0
    assert db.get(SolicitudPrestador, item_id).status == "pendiente"


def test_rejected_and_empty_name_do_not_convert(intake_app, payload):
    client, db = intake_app
    body = authorized_payload(payload, business_name="")
    empty_id = post_intake(client, body).json()["id"]
    rejected_body = authorized_payload(payload, external_id="rejected")
    rejected_id = post_intake(client, rejected_body).json()["id"]
    db.get(SolicitudPrestador, rejected_id).status = "rechazada"; db.commit()
    login_admin(client)
    assert "obligatorio" in client.post(f"/admin/solicitudes/{empty_id}/convertir", follow_redirects=True).text
    assert "rechazada" in client.post(f"/admin/solicitudes/{rejected_id}/convertir", follow_redirects=True).text
    assert db.query(Empresa).count() == 0


@pytest.mark.parametrize("business_type,theme,group,subtype", [
    ("Gastronomía", "gastronomia", None, None),
    ("Alojamiento", "alojamiento", None, None),
    ("Almacén / kiosco / proveeduría", "servicios", "compras", "Kiosco"),
    ("Productos regionales / artesanías", "servicios", "compras", "Productos regionales"),
    ("Camping", "alojamiento", None, "Camping"),
    ("Transporte / remis", "servicios", "transporte", "Remis"),
    ("Estacionamiento", "servicios", "estacionamiento", "Estacionamiento"),
    ("Salud y bienestar", "servicios", "salud", "Farmacia"),
    ("Otro servicio", "servicios", "otros", None),
])
def test_empresa_rubric_mapping_is_draft(intake_app, payload, business_type, theme, group, subtype):
    client, db = intake_app
    body = authorized_payload(payload, external_id=f"type-{intake_key_for_test(business_type)}", business_type=business_type)
    if business_type.startswith("Almacén"):
        body["specific_data"]["Tipo de comercio"] = "Kiosco"
    if business_type == "Salud y bienestar":
        body["specific_data"]["Tipo de servicio"] = "Farmacia"
    item_id = post_intake(client, body).json()["id"]
    login_admin(client)
    response = client.post(f"/admin/solicitudes/{item_id}/convertir", follow_redirects=False)
    assert response.status_code == 303
    company = db.query(Empresa).one()
    assert (company.theme, company.subgrupo, company.subtipo) == (theme, group, subtype)
    assert company.activo is False and company.destacado is False
    request = db.get(SolicitudPrestador, item_id)
    assert request.status == "procesada" and request.converted_entity_type == "empresa"
    assert request.converted_entity_id == company.id and request.processed_at is not None


def intake_key_for_test(value):
    return "".join(character if character.isalnum() else "-" for character in value.lower())


@pytest.mark.parametrize("business_type,expected", [
    ("Actividad turística / recreativa", "actividad"), ("Evento", "evento")
])
def test_agenda_conversion_is_unpublished(intake_app, payload, business_type, expected):
    client, db = intake_app
    body = authorized_payload(payload, external_id=f"agenda-{expected}", business_type=business_type)
    body["specific_data"].update({"Categoría": "Naturaleza", "Fecha inicio": "fecha inválida", "Punto de encuentro": "Puente"})
    item_id = post_intake(client, body).json()["id"]
    login_admin(client)
    assert client.post(f"/admin/solicitudes/{item_id}/convertir", follow_redirects=False).status_code == 303
    activity = db.query(ActividadAgenda).one()
    assert activity.tipo == expected and activity.categoria == "naturaleza"
    assert activity.publicado is False and activity.destacado is False and activity.fecha_inicio is None
    assert activity.lugar == "Puente"


def test_empresa_conversion_maps_short_description_and_promotion(intake_app, payload):
    client, db = intake_app
    body = authorized_payload(payload)
    body["specific_data"].update({
        "Descripción corta del negocio": "  Cerca del río  ",
        "Promoción o beneficio vigente": "  10% en efectivo  ",
    })
    item_id = post_intake(client, body).json()["id"]
    login_admin(client)

    assert client.post(f"/admin/solicitudes/{item_id}/convertir", follow_redirects=False).status_code == 303
    company = db.query(Empresa).one()
    assert company.descripcion_corta == "Cerca del río"
    assert company.promocion == "10% en efectivo"
    assert company.activo is False


def test_agenda_conversion_maps_only_short_description(intake_app, payload):
    client, db = intake_app
    body = authorized_payload(payload, business_type="Evento")
    body["specific_data"].update({
        "Descripción corta del negocio": "  Festival local  ",
        "Promoción o beneficio vigente": "  Entrada anticipada  ",
    })
    item_id = post_intake(client, body).json()["id"]
    login_admin(client)

    assert client.post(f"/admin/solicitudes/{item_id}/convertir", follow_redirects=False).status_code == 303
    activity = db.query(ActividadAgenda).one()
    assert activity.descripcion_corta == "Festival local"
    assert activity.descripcion == payload["description"]
    assert activity.url_externa == payload["social"]["website"]
    assert not hasattr(activity, "promocion")
    assert activity.publicado is False
    request = db.get(SolicitudPrestador, item_id)
    assert json.loads(request.raw_payload)["specific_data"]["Promoción o beneficio vigente"] == "  Entrada anticipada  "


@pytest.mark.parametrize("commerce_type,expected", [
    ("Despensa", "Almacén"),
    ("despensa", "Almacén"),
    ("DESPENSA", "Almacén"),
    ("  Almacén  ", "Almacén"),
    ("Kiosco", "Kiosco"),
    ("Proveeduría", "Proveeduría"),
    ("Tipo desconocido", None),
])
def test_commerce_type_uses_known_subtype_or_safe_fallback(intake_app, payload, commerce_type, expected):
    client, db = intake_app
    body = authorized_payload(
        payload,
        external_id=f"commerce-{intake_key_for_test(commerce_type)}",
        business_type="Almacén / kiosco / proveeduría",
    )
    body["specific_data"]["Tipo de comercio"] = commerce_type
    item_id = post_intake(client, body).json()["id"]
    login_admin(client)

    assert client.post(f"/admin/solicitudes/{item_id}/convertir", follow_redirects=False).status_code == 303
    company = db.query(Empresa).one()
    assert company.subgrupo == "compras"
    assert company.subtipo == expected
    assert company.activo is False


def test_slug_collision_and_double_post_are_idempotent(intake_app, payload):
    client, db = intake_app
    db.add(Empresa(nombre="Existente", slug="posada-del-rio", activo=True)); db.commit()
    item_id = post_intake(client, authorized_payload(payload)).json()["id"]
    login_admin(client)
    first = client.post(f"/admin/solicitudes/{item_id}/convertir", follow_redirects=False)
    second = client.post(f"/admin/solicitudes/{item_id}/convertir", follow_redirects=False)
    assert first.status_code == second.status_code == 303
    assert db.query(Empresa).count() == 2
    created = db.query(Empresa).filter(Empresa.nombre == payload["business_name"]).one()
    assert created.slug == "posada-del-rio-2"
    assert str(created.id) in second.headers["location"] or created.slug in second.headers["location"]


def test_conversion_copies_media_keeps_staging_and_maps_fields(intake_app, payload):
    client, db = intake_app
    body = authorized_payload(payload, business_type="Gastronomía")
    body["specific_data"].update({"¿Hacen delivery?": "Sí", "¿Retiro / take away?": "No", "¿Se puede comer en el lugar?": "Sí"})
    item_id = post_intake(client, body).json()["id"]
    for kind, drive_id in [("logo", "l"), ("cover", "c"), ("gallery", "g1"), ("gallery", "g2")]:
        assert post_media(client, body["external_id"], kind, drive_id).status_code == 201
    staging = [main.STORAGE_DIR / row.relative_path for row in db.query(SolicitudPrestadorArchivo).all()]
    login_admin(client)
    client.post(f"/admin/solicitudes/{item_id}/convertir", follow_redirects=False)
    company = db.query(Empresa).one()
    assert company.delivery is True and company.take_away is False and company.comer_en_lugar is True
    assert company.logo_url and company.banner_url and len(main.get_empresa_gallery_urls(company)) == 2
    urls = [company.logo_url, company.banner_url, *main.get_empresa_gallery_urls(company)]
    assert all((main.STORAGE_DIR / url.removeprefix("/media/")).is_file() for url in urls)
    assert all(path.is_file() for path in staging)
