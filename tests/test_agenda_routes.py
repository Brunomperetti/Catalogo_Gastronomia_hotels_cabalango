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
            ActividadAgenda(tipo="actividad", titulo="Feria de temporada", slug="feria-temporada", categoria="artesania", momento="noche", horarios="Todos los días de 19:00 a 22:00", publicado=True, fecha_inicio=datetime(2026, 8, 1), fecha_fin=datetime(2026, 8, 31)),
            ActividadAgenda(tipo="actividad", titulo="Temporada terminada", slug="temporada-terminada", categoria="artesania", momento="noche", publicado=True, fecha_inicio=datetime(2026, 7, 1), fecha_fin=datetime(2026, 7, 31)),
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
        ("cuando=hoy", ("Feria de hoy", "Música esta noche"), ("Evento de mañana", "Yoga permanente", "Feria de temporada")),
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
    assert "Temporada terminada" in response.text
    assert "Finalizada" in response.text


def test_invalid_range_rolls_back_without_persisting(agenda_app):
    client, TestingSession = agenda_app
    login_admin(client)
    response = client.post("/admin/actividades/guardar", data={"tipo": "evento", "titulo": "Evento inválido", "categoria": "cultura", "momento": "dia", "fecha_inicio": "2026-08-10T20:00", "fecha_fin": "2026-08-10T19:00", "publicado": "1"}, follow_redirects=False)
    assert response.status_code == 303
    with TestingSession() as db:
        assert db.query(ActividadAgenda).filter_by(titulo="Evento inválido").first() is None
        assert db.query(ActividadAgenda).count() == 9


def test_seasonal_activity_detail_presents_schedule_before_validity(agenda_app):
    response = agenda_app[0].get("/actividades/feria-temporada")
    assert response.status_code == 200
    assert "Todos los días de 19:00 a 22:00" in response.text
    assert "Disponible del 01/08/2026 al 31/08/2026" in response.text
    assert response.text.index("Horarios / disponibilidad") < response.text.index("Disponible del")


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


def test_admin_saves_schedule_defaults_manual_override_and_new_flags(agenda_app):
    client, TestingSession = agenda_app
    login_admin(client)
    base = {"tipo": "evento", "titulo": "Festival oficial", "categoria": "cultura", "momento": "noche",
            "fecha_inicio": "2026-11-21T18:00", "fecha_fin": "2026-11-21T22:00", "publicado": "1",
            "oficial": "1", "mostrar_en_home": "1", "prioridad_home": "75", "estado": "programado"}
    assert client.post("/admin/actividades/guardar", data=base, follow_redirects=False).status_code == 303
    with TestingSession() as db:
        item = db.query(ActividadAgenda).filter_by(slug="festival-oficial").one()
        item_id = item.id
        assert (item.oficial, item.mostrar_en_home, item.prioridad_home) == (True, True, 75)
        assert item.publicar_desde == datetime(2026, 11, 7, 18)
        assert item.destacar_home_desde == datetime(2026, 11, 14, 18)
        assert item.ocultar_desde == datetime(2026, 11, 21, 22)

    edited = dict(base, id=str(item_id), estado="reprogramado", fecha_inicio="2026-12-05T18:00",
                  fecha_fin="2026-12-05T22:00", publicar_desde="2026-10-01T09:00")
    assert client.post("/admin/actividades/guardar", data=edited, follow_redirects=False).status_code == 303
    with TestingSession() as db:
        item = db.get(ActividadAgenda, item_id)
        assert item.estado == "reprogramado"
        assert item.publicar_desde == datetime(2026, 10, 1, 9)  # manual value survives
        assert item.destacar_home_desde == datetime(2026, 11, 28, 18)  # automatic value follows new date

    cancelled = dict(edited, estado="cancelado", publicar_desde="2026-10-01T09:00",
                     destacar_home_desde="2026-11-28T18:00", ocultar_desde="2026-12-05T22:00")
    client.post("/admin/actividades/guardar", data=cancelled, follow_redirects=False)
    with TestingSession() as db:
        assert db.get(ActividadAgenda, item_id).estado == "cancelado"


def test_card_omits_short_description_when_it_matches_title(agenda_app):
    client, TestingSession = agenda_app
    with TestingSession() as db:
        item = db.query(ActividadAgenda).filter_by(slug="yoga-permanente").one()
        item.descripcion_corta = "  YOGA PERMANENTE  "
        db.commit()

    response = client.get("/actividades")
    assert response.status_code == 200
    card = response.text.split('href="/actividades/yoga-permanente"', 1)[0].rsplit('<article class="agenda-card">', 1)[1]
    assert 'class="agenda-card__description"' not in card


def test_detail_whatsapp_is_primary_and_conditional(agenda_app):
    client, TestingSession = agenda_app
    with TestingSession() as db:
        item = db.query(ActividadAgenda).filter_by(slug="yoga-permanente").one()
        item.whatsapp = "+54 9 351-555-0101"
        db.commit()

    detail = client.get("/actividades/yoga-permanente").text
    whatsapp_tag = detail.split("Consultar por WhatsApp", 1)[0].rsplit("<a", 1)[1]
    assert 'class="portal-button"' in whatsapp_tag
    assert "portal-button-secondary" not in whatsapp_tag
    assert "wa.me/5493515550101" in whatsapp_tag

    without_whatsapp = client.get("/actividades/feria-hoy").text
    assert "Consultar por WhatsApp" not in without_whatsapp


def test_detail_never_renders_none_or_blank_optional_content(agenda_app):
    client, TestingSession = agenda_app
    with TestingSession() as db:
        item = db.query(ActividadAgenda).filter_by(slug="yoga-permanente").one()
        item.descripcion_corta = None
        item.descripcion = None
        item.horarios = None
        item.lugar = "   "
        item.direccion = None
        item.maps_url = None
        item.whatsapp = None
        item.instagram = None
        item.url_externa = None
        db.commit()

    response = client.get("/actividades/yoga-permanente")
    assert response.status_code == 200
    detail = response.text.split('<article class="agenda-detail">', 1)[1].split("</article>", 1)[0]
    assert "None" not in detail
    assert 'class="portal-subtitle"' not in detail
    assert 'class="agenda-description"' not in detail
    assert "<dt>Lugar</dt>" not in detail
    assert "<dt>Dirección</dt>" not in detail
