import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base
from app.models import Empresa, Usuario


@pytest.fixture()
def camping_app(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = Session()
    db.add(Usuario(username="admin-camping", password_hash=main.hash_password("secret"), rol="admin", activo=True))
    camping = Empresa(
        nombre="Camping El Socavón", slug="camping-el-socavon", theme="alojamiento",
        subtipo="Camping", activo=True, capacidad="400", habitaciones="0", horarios="Invierno: 10:00 a 18:00 | Verano: 9:00 a 20:30",
        banos="Baños disponibles", precio_desde="$10.000 por persona", rio=True,
        duchas=True, agua_caliente=True, electricidad=True, parrilla=True,
        proveeduria=True, wifi=True, cochera=True, mesas=True, quinchos=True,
        motorhome=True, mascotas=True, pileta=False,
    )
    cabin = Empresa(nombre="Cabaña Tradicional", slug="cabana-tradicional", theme="alojamiento", subtipo="Cabaña", activo=True, habitaciones="2", wifi=True)
    db.add_all([camping, cabin]); db.commit()
    monkeypatch.setattr(main, "ensure_empresa_media_columns", lambda: None)
    monkeypatch.setattr(main, "ensure_destino_media_table", lambda: None)
    monkeypatch.setattr(main, "ensure_destino_contenido_table", lambda: None)
    main.app.dependency_overrides[main.get_db] = lambda: (yield db)
    client = TestClient(main.app)
    try:
        yield client, db, camping, cabin
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
        db.close(); engine.dispose()


def test_schema_upgrade_adds_nullable_camping_columns_idempotently(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE empresas (id INTEGER PRIMARY KEY, nombre VARCHAR)"))
        connection.execute(text("INSERT INTO empresas (nombre) VALUES ('Legacy')"))
    monkeypatch.setattr(main, "engine", engine)
    main.ensure_empresa_media_columns(); main.ensure_empresa_media_columns()
    columns = {column["name"] for column in inspect(engine).get_columns("empresas")}
    expected = {"duchas", "agua_caliente", "electricidad", "proveeduria", "mesas", "quinchos", "motorhome"}
    assert expected <= columns
    with engine.connect() as connection:
        assert connection.execute(text("SELECT duchas, motorhome FROM empresas")).one() == (None, None)


def test_camping_option_listing_filter_and_existing_filters(camping_app):
    client, _db, _camping, _cabin = camping_app
    listing = client.get("/alojamientos")
    assert listing.status_code == 200
    assert 'value="camping"' in listing.text and "Camping El Socavón" in listing.text
    filtered = client.get("/alojamientos?tipo=camping&wifi=1&motorhome=1")
    assert filtered.status_code == 200
    assert "Camping El Socavón" in filtered.text and "Cabaña Tradicional" not in filtered.text
    assert "Servicios de camping" in filtered.text
    conventional = client.get("/alojamientos?tipo=cabaña&wifi=1")
    assert "Cabaña Tradicional" in conventional.text and "Camping El Socavón" not in conventional.text


def test_camping_detail_uses_specific_facts_and_hides_irrelevant_data(camping_app):
    client, _db, _camping, _cabin = camping_app
    html = client.get("/prestador/camping-el-socavon").text
    for value in ("Camping", "Hasta 400 personas", "Tarifa orientativa", "$10.000 por persona", "Duchas", "Agua caliente", "Electricidad", "Acepta motorhome", "Quinchos", "Horarios de atención", "Invierno: 10:00 a 18:00", "Verano: 9:00 a 20:30"):
        assert value in html
    assert "Habitaciones</dt>" not in html
    assert "Check-in" not in html
    conventional = main.build_prestador_quick_facts(_cabin, "alojamiento")
    assert {fact["label"]: fact["value"] for fact in conventional}["Habitaciones"] == "2"


def test_admin_edits_camping_and_normalizes_type(camping_app):
    client, db, camping, _cabin = camping_app
    login = client.post("/login", data={"username": "admin-camping", "password": "secret", "next": "/admin"})
    assert login.status_code == 200
    panel = client.get(f"/admin?area=prestador&empresa={camping.slug}&tab=rubro")
    assert panel.status_code == 200
    assert re.search(r'<option value="Camping"\s+selected>', panel.text)
    assert 'name="motorhome"' in panel.text and "Capacidad aproximada" in panel.text
    rubro_panel = panel.text.split('<section id="panel-rubro"', 1)[1].split('<section id="panel-', 1)[0]
    for expected in ("Horarios de atención", "Tarifa orientativa", "Estacionamiento/cochera", "Ej.: Invierno 10 a 18 · Verano 9 a 20:30"):
        assert expected in rubro_panel
    for irrelevant in ("Cómo se ofrece este alojamiento", "CONFIGURACIÓN DE HABITACIONES", "Check-in / Check-out", "Aire acondicionado", "Calefacción", "Desayuno"):
        assert irrelevant not in rubro_panel
    response = client.post("/empresa/editar_panel", data={
        "empresa_slug_actual": camping.slug, "nombre": camping.nombre, "theme": "alojamiento",
        "subtipo": " CAMPING ", "capacidad": "450", "horarios": "Todos los días de 9 a 21", "duchas": "1", "electricidad": "1", "motorhome": "1",
    }, follow_redirects=False)
    assert response.status_code == 303
    db.refresh(camping)
    assert camping.subtipo == "Camping" and camping.capacidad == "450"
    assert camping.horarios == "Todos los días de 9 a 21"
    assert camping.duchas is True and camping.electricidad is True and camping.motorhome is True


def test_conventional_accommodation_admin_form_is_unchanged(camping_app):
    client, _db, _camping, cabin = camping_app
    client.post("/login", data={"username": "admin-camping", "password": "secret", "next": "/admin"})
    html = client.get(f"/admin?area=prestador&empresa={cabin.slug}&tab=rubro").text
    rubro_panel = html.split('<section id="panel-rubro"', 1)[1].split('<section id="panel-', 1)[0]
    for expected in ("Cómo se ofrece este alojamiento", "Precio desde", "CONFIGURACIÓN DE HABITACIONES", "Habitaciones", "Check-in / Check-out", "Aire acondicionado", "Calefacción", "Desayuno"):
        assert expected in rubro_panel
