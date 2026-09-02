from datetime import datetime
from html import unescape
from pathlib import Path
import re
from urllib.parse import parse_qsl, quote, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.agenda as agenda_domain
import app.main as main_module
from app.database import Base
from app.main import app, get_db, hash_password
from app.models import ActividadAgenda, ActividadAgendaFoto, Usuario


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

    assert "actividades_agenda_fotos" in inspect(legacy_engine).get_table_names()
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


@pytest.mark.parametrize(
    ("field", "invalid_value", "message"),
    [
        ("fecha_inicio", "202623-09-01T05:09", "Fecha y hora de inicio inválida."),
        ("fecha_fin", "not-a-date", "Fecha y hora de finalización inválida."),
        ("publicar_desde", "not-a-date", "Fecha de publicación en Agenda inválida."),
        ("destacar_home_desde", "not-a-date", "Fecha para destacar en portada inválida."),
        ("ocultar_desde", "not-a-date", "Fecha de finalización de publicación inválida."),
    ],
)
def test_invalid_admin_date_redirects_without_creating_event(agenda_app, field, invalid_value, message):
    client, TestingSession = agenda_app
    login_admin(client)
    data = {
        "tipo": "evento", "titulo": f"Evento con {field} inválida", "categoria": "cultura",
        "momento": "dia", "fecha_inicio": "2026-09-01T05:09", "fecha_fin": "2026-09-01T07:09",
    }
    data[field] = invalid_value

    response = client.post("/admin/actividades/guardar", data=data, follow_redirects=False)

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    assert quote(message) in response.headers["location"]
    with TestingSession() as db:
        assert db.query(ActividadAgenda).filter_by(titulo=data["titulo"]).first() is None
        assert db.query(ActividadAgenda).count() == 9


def test_invalid_admin_date_does_not_mutate_existing_event(agenda_app):
    client, TestingSession = agenda_app
    login_admin(client)
    with TestingSession() as db:
        item = db.query(ActividadAgenda).filter_by(slug="feria-hoy").one()
        item_id = item.id
        original = (item.titulo, item.fecha_inicio, item.fecha_fin, item.publicado)

    response = client.post(
        "/admin/actividades/guardar",
        data={
            "id": item_id, "tipo": "evento", "titulo": "Título que no debe guardarse",
            "categoria": "cultura", "momento": "dia", "fecha_inicio": "202623-09-01T05:09",
            "fecha_fin": "2026-09-01T07:09",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert f"edit={item_id}" in response.headers["location"]
    assert "Fecha%20y%20hora%20de%20inicio%20inv%C3%A1lida." in response.headers["location"]
    with TestingSession() as db:
        item = db.get(ActividadAgenda, item_id)
        assert (item.titulo, item.fecha_inicio, item.fecha_fin, item.publicado) == original


def test_empty_optional_admin_dates_remain_valid(agenda_app):
    client, TestingSession = agenda_app
    login_admin(client)
    response = client.post(
        "/admin/actividades/guardar",
        data={
            "tipo": "actividad", "titulo": "Actividad sin ventanas", "categoria": "bienestar",
            "momento": "dia", "publicar_desde": "", "destacar_home_desde": "", "ocultar_desde": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with TestingSession() as db:
        item = db.query(ActividadAgenda).filter_by(titulo="Actividad sin ventanas").one()
        assert item.publicar_desde is None
        assert item.destacar_home_desde is None
        assert item.ocultar_desde is None


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
        assert item.publicar_desde is None
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
        assert item.publicar_desde is None
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


def test_admin_activity_delete_removes_secondary_photo_file(agenda_app, tmp_path, monkeypatch):
    client, TestingSession = agenda_app
    login_admin(client)
    monkeypatch.setattr(main_module, "STORAGE_DIR", tmp_path)
    photo_path = tmp_path / "actividades" / "actividad-con-foto" / "galeria-test.jpg"
    photo_path.parent.mkdir(parents=True)
    photo_path.write_bytes(b"secondary-photo")
    with TestingSession() as db:
        item = ActividadAgenda(
            tipo="actividad", titulo="Actividad con foto", slug="actividad-con-foto",
            categoria="otros", momento="dia", publicado=True,
        )
        item.fotos.append(ActividadAgendaFoto(
            image_url="/media/actividades/actividad-con-foto/galeria-test.jpg", orden=0,
        ))
        db.add(item)
        db.commit()
        item_id, photo_id = item.id, item.fotos[0].id

    response = client.post(f"/admin/actividades/{item_id}/eliminar", follow_redirects=False)

    assert response.status_code == 303
    with TestingSession() as db:
        assert db.get(ActividadAgenda, item_id) is None
        assert db.get(ActividadAgendaFoto, photo_id) is None
    assert not photo_path.exists()


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


def test_public_agenda_order_without_default_limit_and_empty_state(agenda_app):
    client, TestingSession = agenda_app
    with TestingSession() as db:
        db.query(ActividadAgenda).filter(ActividadAgenda.tipo == "evento").delete()
        for index in range(9):
            db.add(ActividadAgenda(
                tipo="evento", titulo=f"Próximo {index}", slug=f"proximo-{index}",
                categoria="otros", momento="dia", publicado=True,
                fecha_inicio=datetime(2026, 8, 11 + index, 10), fecha_fin=datetime(2026, 8, 11 + index, 12),
            ))
        db.commit()
    html = client.get("/actividades").text
    assert all(f"Próximo {index}" in html for index in range(9))
    assert html.index("Próximo 0") < html.index("Próximo 8")
    assert "Ver agenda completa" not in html

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
    assert "?v=20260901-agenda-card-alignment-2" in template
    assert "?v=20260810-commerce-services-1" not in template
    assert "?v=20260901-agenda-card-alignment-2" not in home


def test_public_agenda_event_cards_keep_editorial_media_and_grid_rules():
    css = Path("app/static/css/portal.css").read_text(encoding="utf-8")
    image_rule = css.split(".public-agenda .official-event__image {", 1)[1].split("}", 1)[0]
    one_event_rule = css.split('.public-agenda .official-agenda__grid[data-count="1"] {', 1)[1].split("}", 1)[0]
    two_event_rule = css.split('.public-agenda .official-agenda__grid[data-count="2"] {', 1)[1].split("}", 1)[0]

    assert "object-fit: contain" in image_rule
    assert "object-fit: cover" not in image_rule
    assert "aspect-ratio: 4 / 3" in image_rule
    assert "32rem" in one_event_rule and "42rem" not in one_event_rule
    assert "justify-content: start" in one_event_rule
    assert "repeat(2, minmax(0, 1fr))" in two_event_rule
    assert "max-width: 60rem" in two_event_rule
    assert '@media (max-width: 600px)' in css
    assert 'grid-template-columns: 1fr; max-width: none; width: 100%;' in css


def test_public_agenda_event_card_metadata_rows_align_without_fixed_content_heights():
    css = Path("app/static/css/portal.css").read_text(encoding="utf-8")
    facts_rule = css.split(".public-agenda .official-event__facts {", 1)[1].split("}", 1)[0]
    actions_rule = css.split(".public-agenda .official-event__actions {", 1)[1].split("}", 1)[0]
    title_rule = css.split(".public-agenda .official-event h3 {", 1)[1].split("}", 1)[0]
    description_rule = css.split(".public-agenda .official-event__description {", 1)[1].split("}", 1)[0]

    assert "margin: auto 0 0" in facts_rule
    assert "margin-top: auto" not in actions_rule
    assert "min-height" not in title_rule
    assert "min-height" not in description_rule



def test_activity_gallery_upload_render_and_delete(agenda_app, tmp_path, monkeypatch):
    client, TestingSession = agenda_app
    monkeypatch.setattr(main_module, "STORAGE_DIR", tmp_path)
    login_admin(client)
    with TestingSession() as db:
        item = db.query(ActividadAgenda).filter_by(slug="yoga-permanente").one()
        item.imagen_url = "/media/actividades/yoga-permanente/principal.jpg"
        item_id = item.id
        db.commit()

    data = {"id": str(item_id), "tipo": "actividad", "titulo": "Yoga permanente",
            "categoria": "bienestar", "momento": "dia", "publicado": "1"}
    files = [("galeria", ("rio.jpg", b"first-photo", "image/jpeg")),
             ("galeria", ("monte.webp", b"second-photo", "image/webp"))]
    response = client.post("/admin/actividades/guardar", data=data, files=files, follow_redirects=False)
    assert response.status_code == 303
    with TestingSession() as db:
        item = db.get(ActividadAgenda, item_id)
        assert [photo.orden for photo in item.fotos] == [0, 1]
        first_id, first_url = item.fotos[0].id, item.fotos[0].image_url
        assert all(photo.actividad_id == item_id for photo in item.fotos)
    detail = client.get("/actividades/yoga-permanente").text
    assert first_url in detail
    assert "data-activity-gallery" in detail and "data-gallery-lightbox" in detail
    assert client.get(f"/admin/actividades/{item_id}/fotos/{first_id}/eliminar").status_code == 405
    assert client.post(f"/admin/actividades/{item_id}/fotos/{first_id}/eliminar", follow_redirects=False).status_code == 303
    with TestingSession() as db:
        assert db.get(ActividadAgenda, item_id) is not None
        assert db.get(ActividadAgendaFoto, first_id) is None
    assert not (tmp_path / first_url.removeprefix("/media/")).exists()



def test_activity_detail_normalizes_literal_breaks_and_keeps_html_escaped(agenda_app):
    client, TestingSession = agenda_app
    with TestingSession() as db:
        item = db.query(ActividadAgenda).filter_by(slug="yoga-permanente").one()
        item.descripcion = "Primera<br>Segunda<br/>Tercera<br />Cuarta<script>alert(1)</script>"
        db.commit()

    html = client.get("/actividades/yoga-permanente").text
    description = html.split('<div class="agenda-description">', 1)[1].split("</div>", 1)[0]
    assert description == "Primera<br>Segunda<br>Tercera<br>Cuarta&lt;script&gt;alert(1)&lt;/script&gt;"
    assert "&lt;br&gt;" not in description
    assert "<script>alert(1)</script>" not in html


def test_activity_gallery_renders_counter_and_dynamic_update(agenda_app):
    client, TestingSession = agenda_app
    with TestingSession() as db:
        item = db.query(ActividadAgenda).filter_by(slug="yoga-permanente").one()
        item.imagen_url = "/hero.jpg"
        item.fotos.extend([
            ActividadAgendaFoto(image_url=f"/secondary-{index}.jpg", orden=index)
            for index in range(3)
        ])
        db.commit()

    html = client.get("/actividades/yoga-permanente").text
    assert "data-gallery-counter" in html
    assert ">1 / 4</span>" in html
    assert "activity-gallery.js?v=20260831-2" in html

    script = Path("app/static/js/activity-gallery.js").read_text(encoding="utf-8")
    assert "counter.textContent = (current + 1) + ' / ' + images.length;" in script


def test_activity_detail_uses_polish_cache_keys():
    template = Path("app/templates/actividad_detalle.html").read_text(encoding="utf-8")
    assert "portal.css') }}?v=20260831-activity-gallery-polish-2" in template
    assert "activity-gallery.js') }}?v=20260831-2" in template

def test_activity_gallery_is_isolated_validated_and_cascades(agenda_app, tmp_path, monkeypatch):
    client, TestingSession = agenda_app
    monkeypatch.setattr(main_module, "STORAGE_DIR", tmp_path)
    login_admin(client)
    with TestingSession() as db:
        yoga = db.query(ActividadAgenda).filter_by(slug="yoga-permanente").one()
        feria = db.query(ActividadAgenda).filter_by(slug="feria-hoy").one()
        yoga.imagen_url = "/hero.jpg"
        yoga.fotos.append(ActividadAgendaFoto(image_url="/yoga-only.jpg", orden=2))
        feria.fotos.append(ActividadAgendaFoto(image_url="/feria-only.jpg", orden=0))
        yoga_id = yoga.id
        db.commit()
        feria_photo_id = feria.fotos[0].id
    html = client.get("/actividades/yoga-permanente").text
    assert "/yoga-only.jpg" in html and "/feria-only.jpg" not in html
    invalid = client.post("/admin/actividades/guardar", data={"id": yoga_id, "tipo": "actividad",
        "titulo": "Yoga permanente", "categoria": "bienestar", "momento": "dia"},
        files=[("galeria", ("attack.svg", b"bad", "image/svg+xml"))], follow_redirects=False)
    assert "error=" in invalid.headers["location"]
    with TestingSession() as db:
        db.delete(db.get(ActividadAgenda, yoga_id)); db.commit()
        assert db.query(ActividadAgendaFoto).filter_by(actividad_id=yoga_id).count() == 0
        assert db.get(ActividadAgendaFoto, feria_photo_id) is not None


def test_activity_without_gallery_keeps_original_media_markup(agenda_app):
    html = agenda_app[0].get("/actividades/yoga-permanente").text
    assert 'class="agenda-detail__image"' not in html  # Seed has no principal photo.
    assert "data-activity-gallery" not in html and "agenda-lightbox" not in html
    assert "data-gallery-counter" not in html and "activity-gallery.js" not in html


def test_activity_gallery_mobile_css_prevents_page_overflow():
    css = Path("app/static/css/portal.css").read_text()
    assert "@media (max-width: 700px)" in css
    assert ".agenda-gallery { min-width: 0; overflow: hidden; }" in css
    assert ".agenda-gallery__thumbs { width: 100%; }" in css


def test_admin_clearing_existing_agenda_embargo_persists_null(agenda_app):
    client, TestingSession = agenda_app
    login_admin(client)
    with TestingSession() as db:
        item = ActividadAgenda(
            tipo="evento", titulo="Evento embargado", slug="evento-embargado",
            categoria="cultura", momento="dia", publicado=True, estado="programado",
            fecha_inicio=datetime(2026, 9, 19, 18), fecha_fin=datetime(2026, 9, 19, 22),
            publicar_desde=datetime(2026, 9, 5, 18),
        )
        db.add(item)
        db.commit()
        item_id = item.id

    response = client.post(
        "/admin/actividades/guardar",
        data={
            "id": item_id, "tipo": "evento", "titulo": "Evento embargado",
            "categoria": "cultura", "momento": "dia", "publicado": "1",
            "estado": "programado", "fecha_inicio": "2026-09-19T18:00",
            "fecha_fin": "2026-09-19T22:00", "publicar_desde": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with TestingSession() as db:
        item = db.get(ActividadAgenda, item_id)
        assert item.publicar_desde is None
        assert item.ocultar_desde == datetime(2026, 9, 19, 22)
