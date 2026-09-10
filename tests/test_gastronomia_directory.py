import re

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import (
    GASTRONOMIA_FILTROS_PUBLICOS,
    app,
    get_db,
    is_bakery_provider,
    public_gastronomy_category_key,
)
from app.models import Empresa


def test_public_gastronomy_category_uses_only_structured_taxonomy():
    assert list(GASTRONOMIA_FILTROS_PUBLICOS) == [
        "restaurantes", "parrillas", "casas_comida", "bares", "cafeterias",
        "rotiserias", "food_trucks", "otros",
    ]
    cases = [
        ("gastronomia", "Restaurante", "restaurantes"),
        ("gastronomia", "Parrilla", "parrillas"),
        ("gastronomia", "Casa de comidas", "casas_comida"),
        ("gastronomia", "Bar", "bares"),
        ("gastronomia", "CAFETERÍA", "cafeterias"),
        ("gastronomia", "Rotisería", "rotiserias"),
        ("comida", "Food truck", "food_trucks"),
        ("comida", "Proveeduría histórica", "otros"),
    ]
    for theme, subtype, expected in cases:
        assert public_gastronomy_category_key(Empresa(theme=theme, subtipo=subtype)) == expected

    misleading = Empresa(
        theme="gastronomia", subtipo="Bar", nombre="Restaurante Parrilla",
        descripcion="Café y comidas para llevar",
    )
    assert public_gastronomy_category_key(misleading) == "bares"
    assert public_gastronomy_category_key(Empresa(theme="gastronomia", subtipo="Panadería")) is None
    assert public_gastronomy_category_key(Empresa(theme="servicios", subtipo="Bar")) is None


def test_gastronomy_directory_groups_previews_and_filters_exclusively():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = TestingSession()
    records = [
        *[
            Empresa(
                nombre=f"Restaurante {index}", slug=f"restaurante-{index}", theme="gastronomia",
                subtipo="Restaurante", activo=True, whatsapp="543541111111", direccion="Centro",
            )
            for index in range(1, 6)
        ],
        Empresa(nombre="Parrilla A", slug="parrilla-a", theme="gastronomia", subtipo="Parrilla", activo=True),
        Empresa(nombre="Casa de comidas A", slug="casa-a", theme="gastronomia", subtipo="Casa de comidas", activo=True),
        Empresa(nombre="Bar A", slug="bar-a", theme="gastronomia", subtipo="Bar", activo=True),
        Empresa(nombre="Bar B", slug="bar-b", theme="gastronomia", subtipo="Bar", activo=True),
        Empresa(nombre="Cafetería A", slug="cafeteria-a", theme="gastronomia", subtipo="Cafetería", activo=True),
        Empresa(nombre="Rotisería A", slug="rotiseria-a", theme="gastronomia", subtipo="Rotisería", activo=True),
        Empresa(nombre="Food truck A", slug="food-truck-a", theme="comida", subtipo="Food truck", activo=True),
        Empresa(nombre="Otro gastronómico A", slug="otro-a", theme="gastronomia", subtipo="Otro", activo=True),
        Empresa(nombre="Panadería A", slug="panaderia-a", theme="gastronomia", subtipo="Panadería", activo=True),
    ]
    db.add_all(records)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        response = client.get("/gastronomia")
        assert response.status_code == 200
        html = response.text
        filters = html.split('<nav class="services-filters"', 1)[1].split("</nav>", 1)[0]
        assert re.findall(r">([^<>]+)</a>", filters) == [
            "Todo", "Restaurantes", "Parrillas", "Casas de comida", "Bares",
            "Cafeterías", "Rotiserías", "Food trucks", "Otros",
        ]
        assert re.findall(r'href="([^"]+)"', filters) == [
            "/gastronomia", "/gastronomia?filtro=restaurantes", "/gastronomia?filtro=parrillas",
            "/gastronomia?filtro=casas_comida", "/gastronomia?filtro=bares",
            "/gastronomia?filtro=cafeterias", "/gastronomia?filtro=rotiserias",
            "/gastronomia?filtro=food_trucks", "/gastronomia?filtro=otros",
        ]
        assert '<a class="services-filter-all is-active" href="/gastronomia">Todo</a>' in html
        headings = [f'id="gastronomy-group-{key}"' for key in GASTRONOMIA_FILTROS_PUBLICOS]
        assert all(heading in html for heading in headings)
        assert [html.index(heading) for heading in headings] == sorted(html.index(heading) for heading in headings)
        assert html.count('class="services-overview-group"') == 8
        assert html.count("Restaurante 1") == 2  # Card image alt/label and heading.
        assert "Restaurante 4" not in html
        assert "Restaurante 5" not in html
        assert "Panadería A" not in html

        restaurants = client.get("/gastronomia?filtro=restaurantes").text
        assert all(f"Restaurante {index}" in restaurants for index in range(1, 6))
        assert "Bar A" not in restaurants
        assert "Encontrá restaurantes para disfrutar una comida en Cabalango." in restaurants
        assert 'class="is-active" href="/gastronomia?filtro=restaurantes"' in restaurants
        assert "services-overview-group" not in restaurants
        assert "Ver ficha" in restaurants and "WhatsApp" in restaurants

        bars = client.get("/gastronomia?filtro=bares").text
        assert "Bar A" in bars and "Bar B" in bars
        assert "Restaurante 1" not in bars and "Cafetería A" not in bars
        for key in GASTRONOMIA_FILTROS_PUBLICOS:
            assert "Panadería A" not in client.get(f"/gastronomia?filtro={key}").text

        bakery_service = client.get("/servicios?filtro=panaderias").text
        assert "Panadería A" in bakery_service
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        engine.dispose()


def test_gastronomy_overview_omits_empty_categories():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = TestingSession()
    db.add(Empresa(nombre="Solo Bar", slug="solo-bar", theme="gastronomia", subtipo="Bar", activo=True))
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        html = TestClient(app).get("/gastronomia").text
        assert 'id="gastronomy-group-bares"' in html
        assert 'id="gastronomy-group-restaurantes"' not in html
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        engine.dispose()


def test_legacy_comida_bakery_keeps_its_exclusive_public_placement():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = TestingSession()
    historical_bakery = Empresa(
        nombre="Panadería histórica", slug="panaderia-historica", theme="comida",
        subtipo="Panadería", activo=True,
    )
    db.add(historical_bakery)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        assert is_bakery_provider(historical_bakery) is True
        assert public_gastronomy_category_key(historical_bakery) is None
        gastronomy_with_only_bakery = client.get("/gastronomia").text
        assert "Panadería histórica" not in gastronomy_with_only_bakery

        db.add_all([
            Empresa(
                nombre="Restaurante histórico", slug="restaurante-historico", theme="comida",
                subtipo="Restaurante", activo=True,
            ),
            Empresa(
                nombre="Food truck histórico", slug="food-truck-historico", theme="comida",
                subtipo="Food truck", activo=True,
            ),
        ])
        db.commit()

        bakery_services = client.get("/servicios?filtro=panaderias").text
        assert "Panadería histórica" in bakery_services
        assert "Restaurante histórico" not in bakery_services
        assert "Food truck histórico" not in bakery_services

        restaurants = client.get("/gastronomia?filtro=restaurantes").text
        food_trucks = client.get("/gastronomia?filtro=food_trucks").text
        assert "Restaurante histórico" in restaurants
        assert "Food truck histórico" in food_trucks

        all_services = client.get("/servicios").text
        assert "Restaurante histórico" not in all_services
        assert "Food truck histórico" not in all_services
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        engine.dispose()
