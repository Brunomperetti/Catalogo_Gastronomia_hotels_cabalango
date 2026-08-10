from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.agenda as agenda_domain
from app.database import Base
from app.main import app, get_db, hash_password
from app.models import ActividadAgenda, Usuario


NOW = datetime(2026, 8, 10, 20, 0, tzinfo=agenda_domain.CABALANGO_TZ)


@pytest.fixture
def agenda_app(monkeypatch):
    """Every route in this suite uses an isolated, process-local SQLite DB."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    with TestingSession() as seed:
        seed.add(Usuario(username="agenda-admin", password_hash=hash_password("safe-test-password"), rol="admin", activo=True))
        seed.add_all([
            ActividadAgenda(tipo="actividad", titulo="Yoga permanente", slug="yoga-permanente", descripcion_corta="Respirar junto al río", categoria="bienestar", momento="dia", publicado=True, destacado=True),
            ActividadAgenda(tipo="evento", titulo="Feria de hoy", slug="feria-hoy", descripcion_corta="Artesanos locales", categoria="cultura", momento="dia", publicado=True, fecha_inicio=datetime(2026, 8, 10, 10), fecha_fin=datetime(2026, 8, 10, 22)),
            ActividadAgenda(tipo="evento", titulo="Música esta noche", slug="musica-noche", descripcion_corta="Show junto al río", categoria="musica", momento="noche", publicado=True, fecha_inicio=datetime(2026, 8, 10, 21), fecha_fin=datetime(2026, 8, 10, 23)),
            ActividadAgenda(tipo="evento", titulo="Evento de mañana", slug="evento-manana", categoria="bienestar", momento="noche", publicado=True, fecha_inicio=datetime(2026, 8, 11, 21), fecha_fin=datetime(2026, 8, 11, 23)),
            ActividadAgenda(tipo="evento", titulo="Evento vencido", slug="evento-vencido", categoria="cultura", momento="noche", publicado=True, fecha_inicio=datetime(2026, 8, 9, 18), fecha_fin=datetime(2026, 8, 9, 20)),
            ActividadAgenda(tipo="evento", titulo="Evento borrador", slug="evento-borrador", categoria="otros", momento="dia", publicado=False, fecha_inicio=datetime(2026, 8, 11, 10), fecha_fin=datetime(2026, 8, 11, 12)),
            ActividadAgenda(tipo="evento", titulo="Evento despublicado", slug="evento-despublicado", categoria="cultura", momento="dia", publicado=False, fecha_inicio=datetime(2026, 8, 10, 10), fecha_fin=datetime(2026, 8, 10, 22)),
        ])
        seed.commit()

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(agenda_domain, "now_cabalango", lambda: NOW)
    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app), TestingSession
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def login_admin(client):
    response = client.post("/login", data={"username": "agenda-admin", "password": "safe-test-password", "next": "/admin/actividades"}, follow_redirects=False)
    assert response.status_code == 303


def test_public_listing_and_detail_visibility(agenda_app):
    client, _ = agenda_app
    assert client.get("/actividades").status_code == 200
    assert client.get("/actividades/yoga-permanente").status_code == 200
    assert client.get("/actividades/feria-hoy").status_code == 200
    for slug in ("evento-vencido", "evento-borrador", "evento-despublicado", "no-existe"):
        assert client.get(f"/actividades/{slug}").status_code == 404


@pytest.mark.parametrize(
    ("query", "visible", "hidden"),
    [
        ("cuando=hoy", ("Feria de hoy", "Música esta noche"), ("Evento de mañana", "Yoga permanente")),
        ("momento=noche", ("Música esta noche", "Evento de mañana"), ("Feria de hoy", "Yoga permanente")),
        ("categoria=bienestar", ("Yoga permanente", "Evento de mañana"), ("Feria de hoy", "Música esta noche")),
    ],
)
def test_public_filters(agenda_app, query, visible, hidden):
    html = agenda_app[0].get(f"/actividades?{query}").text
    assert all(title in html for title in visible)
    assert all(title not in html for title in hidden)


def test_authenticated_admin_keeps_expired_event_as_finalizado(agenda_app):
    client, _ = agenda_app
    login_admin(client)
    response = client.get("/admin/actividades")
    assert response.status_code == 200
    assert "Evento vencido" in response.text
    assert "Finalizado" in response.text


def test_invalid_range_rolls_back_without_persisting(agenda_app):
    client, TestingSession = agenda_app
    login_admin(client)
    response = client.post("/admin/actividades/guardar", data={"tipo": "evento", "titulo": "Evento inválido", "categoria": "cultura", "momento": "dia", "fecha_inicio": "2026-08-10T20:00", "fecha_fin": "2026-08-10T19:00", "publicado": "1"}, follow_redirects=False)
    assert response.status_code == 303
    with TestingSession() as db:
        assert db.query(ActividadAgenda).filter_by(titulo="Evento inválido").first() is None
        assert db.query(ActividadAgenda).count() == 7


def test_duplicate_is_draft_without_dates_and_preserves_content(agenda_app):
    client, TestingSession = agenda_app
    login_admin(client)
    with TestingSession() as db:
        source = db.query(ActividadAgenda).filter_by(slug="feria-hoy").one()
        source_id, source_slug = source.id, source.slug
    response = client.post(f"/admin/actividades/{source_id}/duplicar", follow_redirects=False)
    assert response.status_code == 303
    with TestingSession() as db:
        copies = db.query(ActividadAgenda).filter(ActividadAgenda.id != source_id, ActividadAgenda.titulo == "Feria de hoy").all()
        assert len(copies) == 1
        copy = copies[0]
        assert copy.slug != source_slug
        assert copy.publicado is False
        assert copy.fecha_inicio is None and copy.fecha_fin is None
        assert copy.descripcion_corta == "Artesanos locales"
        assert copy.categoria == "cultura" and copy.momento == "dia"


def test_edit_keeps_slug_stable_and_accepts_zero_order(agenda_app):
    client, TestingSession = agenda_app
    login_admin(client)
    with TestingSession() as db:
        item = db.query(ActividadAgenda).filter_by(slug="yoga-permanente").one()
        item_id = item.id
    response = client.post("/admin/actividades/guardar", data={"id": item_id, "tipo": "actividad", "titulo": "Yoga con título renovado", "categoria": "bienestar", "momento": "dia", "orden": "0", "publicado": "1"}, follow_redirects=False)
    assert response.status_code == 303
    with TestingSession() as db:
        item = db.get(ActividadAgenda, item_id)
        assert item.slug == "yoga-permanente"
        assert item.orden == 0
