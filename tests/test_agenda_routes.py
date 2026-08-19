from datetime import datetime
from html import unescape
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.agenda as agenda_domain
import app.main as main_module
from app.database import Base
from app.main import app, get_db, hash_password
from app.models import ActividadAgenda, Usuario


NOW = datetime(2026, 8, 10, 20, 0, tzinfo=agenda_domain.CABALANGO_TZ)


def test_legacy_sqlite_agenda_bootstrap_is_additive_and_idempotent(tmp_path, monkeypatch):
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy-agenda.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE actividades_agenda (
                id INTEGER PRIMARY KEY,
                tipo VARCHAR NOT NULL,
                titulo VARCHAR NOT NULL,
                slug VARCHAR NOT NULL,
                publicado BOOLEAN NOT NULL DEFAULT FALSE
            )
        """))
        connection.execute(text("""
            INSERT INTO actividades_agenda (id, tipo, titulo, slug, publicado)
            VALUES (1, 'evento', 'Evento existente', 'evento-existente', TRUE)
        """))

    monkeypatch.setattr(main_module, "engine", legacy_engine)
    main_module.ensure_actividad_agenda_table()

    expected_columns = {
        "oficial", "estado", "publicar_desde", "destacar_home_desde",
        "ocultar_desde", "mostrar_en_home", "prioridad_home",
    }
    assert expected_columns <= {column["name"] for column in inspect(legacy_engine).get_columns("actividades_agenda")}
    with legacy_engine.connect() as connection:
        row = connection.execute(text("""
            SELECT titulo, oficial, estado, publicar_desde,
                   destacar_home_desde, ocultar_desde, mostrar_en_home, prioridad_home
            FROM actividades_agenda WHERE id = 1
        """)).mappings().one()
    assert row == {
        "titulo": "Evento existente", "oficial": 0, "estado": "programado",
        "publicar_desde": None, "destacar_home_desde": None, "ocultar_desde": None,
        "mostrar_en_home": 0, "prioridad_home": 0,
    }

    main_module.ensure_actividad_agenda_table()
    with legacy_engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM actividades_agenda")).scalar_one() == 1
    legacy_engine.dispose()


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
        ("cuando=hoy", ("Feria de hoy", "Música esta noche", "Yoga permanente", "Feria de temporada"), ("Evento de mañana",)),
        ("momento=noche", ("Feria de hoy", "Música esta noche", "Evento de mañana", "Feria de temporada"), ("Yoga permanente",)),
        ("categoria=bienestar", ("Yoga permanente", "Feria de hoy", "Música esta noche", "Evento de mañana"), ("Feria de temporada",)),
    ],
)
def test_public_filters(agenda_app, query, visible, hidden):
    html = agenda_app[0].get(f"/actividades?{query}").text
    assert all(title in html for title in visible)
    assert all(title not in html for title in hidden)


def test_experience_filters_do_not_change_official_agenda(agenda_app):
    client, TestingSession = agenda_app
    with TestingSession() as db:
        db.add_all([
            ActividadAgenda(tipo="actividad", titulo="Sendero naturaleza", slug="sendero-naturaleza", categoria="naturaleza", momento="dia", publicado=True),
            ActividadAgenda(tipo="actividad", titulo="Taller cultura", slug="taller-cultura", categoria="cultura", momento="noche", publicado=True),
            ActividadAgenda(tipo="evento", titulo="Festival cultura", slug="festival-cultura", categoria="cultura", momento="dia", publicado=True, fecha_inicio=datetime(2026, 8, 11, 18), fecha_fin=datetime(2026, 8, 11, 20)),
            ActividadAgenda(tipo="evento", titulo="Encuentro naturaleza", slug="encuentro-naturaleza", categoria="naturaleza", momento="dia", publicado=True, fecha_inicio=datetime(2026, 8, 12, 18), fecha_fin=datetime(2026, 8, 12, 20)),
        ])
        db.commit()

    def sections(query):
        html = client.get(f"/actividades?{query}").text
        official = html.split('class="official-agenda agenda-section"', 1)[1].split('class="experiences agenda-section"', 1)[0]
        experiences = html.split('class="experiences agenda-section"', 1)[1]
        return official, experiences

    official, experiences = sections("categoria=naturaleza")
    assert "Festival cultura" in official
    assert "Sendero naturaleza" in experiences and "Taller cultura" not in experiences

    official, experiences = sections("categoria=cultura")
    assert "Encuentro naturaleza" in official
    assert "Taller cultura" in experiences and "Sendero naturaleza" not in experiences

    official, experiences = sections("momento=noche")
    assert "Festival cultura" in official and "Encuentro naturaleza" in official
    assert "Taller cultura" in experiences and "Sendero naturaleza" not in experiences

    official, experiences = sections("cuando=hoy")
    assert "Feria de hoy" in official and "Música esta noche" in official
    assert "Festival cultura" not in official and "Encuentro naturaleza" not in official
    assert "Sendero naturaleza" in experiences and "Taller cultura" in experiences
    assert 'aria-label="Filtros de Agenda Oficial"' in official
    assert ">Hoy</a>" in official
    assert ">Hoy</a>" not in experiences


def test_filter_links_preserve_independent_query_state(agenda_app):
    client, _ = agenda_app

    today_html = client.get("/actividades?cuando=hoy").text
    assert 'href="/actividades?categoria=naturaleza&amp;cuando=hoy"' in today_html

    culture_html = client.get("/actividades?categoria=cultura").text
    assert 'href="/actividades?cuando=hoy&amp;categoria=cultura"' in culture_html

    combined_html = client.get("/actividades?cuando=hoy&categoria=cultura").text
    assert 'href="/actividades?momento=noche&amp;cuando=hoy"' in combined_html
    assert 'href="/actividades?cuando=hoy" class="' in combined_html  # Todo clears experience filters.

    all_filters_html = client.get("/actividades?cuando=hoy&categoria=cultura&momento=noche").text
    assert 'href="/actividades?categoria=cultura&amp;momento=noche" class="' in all_filters_html  # Próximos clears only cuando.

    for html in (today_html, culture_html, combined_html, all_filters_html):
        hrefs = [unescape(href) for href in re.findall(r'href="([^"]+)"', html) if href.startswith("/actividades")]
        assert all(marker not in href for href in hrefs for marker in ("??", "&&", "?&"))
        for href in hrefs:
            keys = [key for key, _ in parse_qsl(urlsplit(href).query, keep_blank_values=True)]
            assert len(keys) == len(set(keys))


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


@pytest.mark.parametrize(
    ("case_name", "submitted_order", "expected_order"),
    [
        ("empty", "", None), ("missing", None, None), ("whitespace", "   ", None),
        ("zero", "0", 0), ("numeric", "15", 15),
    ],
)
def test_admin_saves_optional_order(agenda_app, case_name, submitted_order, expected_order):
    client, TestingSession = agenda_app
    login_admin(client)
    data = {
        "tipo": "actividad", "titulo": f"Actividad orden {case_name}",
        "categoria": "bienestar", "momento": "dia",
    }
    if submitted_order is not None:
        data["orden"] = submitted_order

    response = client.post("/admin/actividades/guardar", data=data, follow_redirects=False)

    assert response.status_code == 303
    with TestingSession() as db:
        item = db.query(ActividadAgenda).filter_by(titulo=data["titulo"]).one()
        assert item.orden == expected_order


def test_admin_rejects_invalid_order_without_persisting(agenda_app):
    client, TestingSession = agenda_app
    login_admin(client)
    response = client.post(
        "/admin/actividades/guardar",
        data={
            "tipo": "actividad", "titulo": "Actividad con orden inválido",
            "categoria": "bienestar", "momento": "dia", "orden": "abc",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/admin/actividades?")
    assert "error=" in response.headers["location"]
    with TestingSession() as db:
        assert db.query(ActividadAgenda).filter_by(titulo="Actividad con orden inválido").first() is None


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


def test_admin_saves_undated_draft_then_schedules_it_with_defaults(agenda_app):
    client, TestingSession = agenda_app
    login_admin(client)
    draft = {
        "tipo": "evento", "titulo": "Congreso a confirmar", "categoria": "bienestar",
        "momento": "dia", "estado": "borrador", "publicado": "1", "mostrar_en_home": "1",
    }
    assert client.post("/admin/actividades/guardar", data=draft, follow_redirects=False).status_code == 303
    with TestingSession() as db:
        item = db.query(ActividadAgenda).filter_by(slug="congreso-a-confirmar").one()
        item_id = item.id
        assert item.estado == "borrador"
        assert item.publicado is False
        assert item.fecha_inicio is None and item.fecha_fin is None
        assert item.publicar_desde is None
        assert item.destacar_home_desde is None
        assert item.ocultar_desde is None

    scheduled = dict(
        draft, id=str(item_id), estado="programado", fecha_inicio="2026-11-21T18:00",
        fecha_fin="2026-11-21T22:00",
    )
    assert client.post("/admin/actividades/guardar", data=scheduled, follow_redirects=False).status_code == 303
    with TestingSession() as db:
        item = db.get(ActividadAgenda, item_id)
        assert item.estado == "programado"
        assert item.publicar_desde == datetime(2026, 11, 7, 18)
        assert item.destacar_home_desde == datetime(2026, 11, 14, 18)
        assert item.ocultar_desde == datetime(2026, 11, 21, 22)


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


@pytest.mark.parametrize("tipo", ["evento", "actividad"])
def test_admin_permanently_deletes_agenda_records(agenda_app, tipo):
    client, TestingSession = agenda_app
    login_admin(client)
    with TestingSession() as db:
        item = ActividadAgenda(
            tipo=tipo, titulo=f"Registro ficticio {tipo}", slug=f"registro-ficticio-{tipo}",
            categoria="otros", momento="dia", publicado=True,
            fecha_inicio=datetime(2026, 8, 11, 10) if tipo == "evento" else None,
            fecha_fin=datetime(2026, 8, 11, 12) if tipo == "evento" else None,
        )
        db.add(item)
        db.commit()
        item_id, slug = item.id, item.slug
    assert slug in client.get("/actividades").text

    response = client.post(f"/admin/actividades/{item_id}/eliminar", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/admin/actividades?msg=")
    with TestingSession() as db:
        assert db.get(ActividadAgenda, item_id) is None
    assert slug not in client.get("/actividades").text
    assert client.get(f"/actividades/{slug}").status_code == 404


def test_deleted_home_eligible_event_disappears_from_home(agenda_app, monkeypatch):
    client, TestingSession = agenda_app
    login_admin(client)
    monkeypatch.setattr(main_module, "now_cabalango", lambda: NOW)
    with TestingSession() as db:
        item = ActividadAgenda(
            tipo="evento", titulo="Home ficticio", slug="home-ficticio", categoria="cultura",
            momento="dia", publicado=True, mostrar_en_home=True, estado="programado",
            fecha_inicio=datetime(2026, 8, 11, 10), fecha_fin=datetime(2026, 8, 11, 12),
            destacar_home_desde=datetime(2026, 8, 1, 10),
        )
        db.add(item)
        db.commit()
        item_id = item.id
    assert "Home ficticio" in client.get("/").text
    assert client.post(f"/admin/actividades/{item_id}/eliminar", follow_redirects=False).status_code == 303
    assert "Home ficticio" not in client.get("/").text


def test_agenda_permanent_delete_requires_admin_post_and_existing_id(agenda_app):
    client, TestingSession = agenda_app
    with TestingSession() as db:
        item_id = db.query(ActividadAgenda).filter_by(slug="yoga-permanente").one().id
    assert client.get(f"/admin/actividades/{item_id}/eliminar").status_code == 405
    anonymous_post = client.post(f"/admin/actividades/{item_id}/eliminar", follow_redirects=False)
    assert anonymous_post.status_code == 303
    assert anonymous_post.headers["location"].startswith("/login?")
    with TestingSession() as db:
        assert db.get(ActividadAgenda, item_id) is not None
    login_admin(client)
    assert client.post("/admin/actividades/999999/eliminar").status_code == 404


def test_agenda_danger_zone_only_appears_while_editing(agenda_app):
    client, TestingSession = agenda_app
    login_admin(client)
    create_html = client.get("/admin/actividades").text
    assert "admin-danger-zone" not in create_html
    with TestingSession() as db:
        item = db.query(ActividadAgenda).filter_by(slug="yoga-permanente").one()
        item_id, title = item.id, item.titulo
    edit_html = client.get(f"/admin/actividades?edit={item_id}").text
    assert "Zona de peligro" in edit_html
    assert "Eliminar definitivamente" in edit_html
    assert title in edit_html
    assert f'action="/admin/actividades/{item_id}/eliminar"' in edit_html
    assert "onsubmit=\"return confirm" not in edit_html


def test_public_agenda_is_editorial_separated_and_accessible(agenda_app):
    client, TestingSession = agenda_app
    with TestingSession() as db:
        db.add_all([
            ActividadAgenda(
                tipo="evento", titulo="Taller nueva fecha", slug="taller-nueva-fecha",
                descripcion_corta="Una ronda para compartir memoria", categoria="cultura",
                momento="dia", lugar="SUM", horarios="17:00 hs", publicado=True,
                oficial=True, estado="reprogramado", imagen_url="/media/taller.jpg",
                fecha_inicio=datetime(2026, 8, 11, 17), fecha_fin=datetime(2026, 8, 11, 19),
            ),
            ActividadAgenda(
                tipo="evento", titulo="Encuentro sin foto", slug="encuentro-sin-foto",
                categoria="naturaleza", momento="dia", lugar="Plaza Nativa", publicado=True,
                fecha_inicio=datetime(2026, 8, 12, 9), fecha_fin=datetime(2026, 8, 12, 11),
            ),
        ])
        db.commit()

    response = client.get("/actividades")
    assert response.status_code == 200
    html = response.text
    official = html.split('class="official-agenda agenda-section"', 1)[1].split('class="experiences agenda-section"', 1)[0]
    experiences = html.split('class="experiences agenda-section"', 1)[1]
    assert "AGENDA OFICIAL" in official and "Lo próximo en Cabalango" in official
    assert "Taller nueva fecha" in official and "Encuentro sin foto" in official
    assert "Yoga permanente" not in official
    assert "Yoga permanente" in experiences and "Taller nueva fecha" not in experiences
    assert "NUEVA FECHA" in official and "MAÑANA" in official and "Evento oficial" in official
    assert '<time class="official-event__date" datetime="2026-08-11T17:00:00-03:00">11 AGO</time>' in official
    assert 'src="/media/taller.jpg" alt="Taller nueva fecha" loading="lazy"' in official
    assert official.count('/media/taller.jpg') == 1
    no_photo_card = official.split("Encuentro sin foto", 1)[0].rsplit('<article class="official-event', 1)[1]
    assert "<img" not in no_photo_card
    assert "Plaza Nativa" in official and "Ver evento" in official


def test_public_agenda_excludes_invalid_states_windows_and_finished_events(agenda_app):
    client, TestingSession = agenda_app
    common = dict(tipo="evento", categoria="cultura", momento="dia", publicado=True,
                  oficial=True, destacado=True, fecha_inicio=datetime(2026, 8, 11, 10),
                  fecha_fin=datetime(2026, 8, 11, 12))
    with TestingSession() as db:
        db.add_all([
            ActividadAgenda(titulo="Oculto borrador", slug="oculto-borrador", estado="borrador", **common),
            ActividadAgenda(titulo="Oculto cancelado", slug="oculto-cancelado", estado="cancelado", **common),
            ActividadAgenda(titulo="Oculto realizado", slug="oculto-realizado", estado="realizado", **common),
            ActividadAgenda(titulo="Oculto no publicado", slug="oculto-no-publicado", **(common | {"publicado": False})),
            ActividadAgenda(titulo="Oculto fuera de ventana", slug="oculto-fuera-ventana", publicar_desde=datetime(2026, 8, 10, 21), **common),
            ActividadAgenda(titulo="Oculto finalizado", slug="oculto-finalizado", **(common | {"fecha_inicio": datetime(2026, 8, 9, 10), "fecha_fin": datetime(2026, 8, 9, 12)})),
        ])
        db.commit()
    html = client.get("/actividades").text
    for title in ("Oculto borrador", "Oculto cancelado", "Oculto realizado", "Oculto no publicado", "Oculto fuera de ventana", "Oculto finalizado"):
        assert title not in html


def test_public_agenda_order_limit_and_empty_state(agenda_app):
    client, TestingSession = agenda_app
    with TestingSession() as db:
        db.query(ActividadAgenda).filter(ActividadAgenda.tipo == "evento").delete()
        for index in range(7):
            db.add(ActividadAgenda(
                tipo="evento", titulo=f"Próximo {index}", slug=f"proximo-{index}",
                categoria="otros", momento="dia", publicado=True,
                fecha_inicio=datetime(2026, 8, 11 + index, 10), fecha_fin=datetime(2026, 8, 11 + index, 12),
            ))
        db.commit()
    html = client.get("/actividades").text
    assert html.index("Próximo 0") < html.index("Próximo 5")
    assert "Próximo 6" not in html and "Ver agenda completa" not in html

    with TestingSession() as db:
        db.query(ActividadAgenda).filter(ActividadAgenda.tipo == "evento").delete()
        db.commit()
    html = client.get("/actividades").text
    assert "Por ahora no hay próximos eventos publicados." in html
    assert "Yoga permanente" in html


def test_que_hacer_uses_dedicated_stylesheet_cache_key_only():
    templates_dir = Path(main_module.__file__).parent / "templates"
    template = (templates_dir / "actividades.html").read_text()
    home = (templates_dir / "portal_home.html").read_text()
    assert "?v=20260818-agenda-official-1" in template
    assert "?v=20260810-commerce-services-1" not in template
    assert "?v=20260818-agenda-official-1" not in home
