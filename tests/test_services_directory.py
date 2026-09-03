from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app, get_db
from app.models import Empresa


def test_services_taxonomy_filters_and_compatibility():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = TestingSession()
    records = [
        ("Proveeduría Tomaco", "tomaco", "compras", "Proveeduría", True),
        ("Remis Cabalango", "remis-cabalango", "transporte", "Remis", True),
        ("Costa Norte", "costa-norte", "estacionamiento", "Playa de estacionamiento", True),
        ("Pregot Rosana", "pregot-rosana", "salud", "Kinesiología", True),
        ("Lavadero Rita", "lavadero-rita", "otros", "Lavadero de ropa", True),
        ("Histórico", "historico", "valor-antiguo", "Gomería", True),
        ("Comercio inactivo", "inactivo", "compras", "Kiosco", False),
    ]
    for nombre, slug, subgrupo, subtipo, activo in records:
        db.add(Empresa(nombre=nombre, slug=slug, theme="servicios", subgrupo=subgrupo, subtipo=subtipo, activo=activo))
    db.add(Empresa(nombre="Food Truck", slug="food-truck", theme="gastronomia", subtipo="Food truck", activo=True))
    db.add(Empresa(nombre="Camping", slug="camping", theme="alojamiento", subtipo="Camping", activo=True))
    db.commit()

    def override_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        response = client.get("/servicios")
        assert response.status_code == 200
        assert "Compras y servicios" in response.text
        assert 'href="/servicios?grupo=compras">Almacenes y kioscos</a>' in response.text
        assert "Servicios útiles" not in response.text
        assert "PARA VECINOS Y VISITANTES" in response.text
        assert "Comercio inactivo" not in response.text
        assert "Histórico" in response.text

        expectations = {
            "compras": ("Proveeduría Tomaco", "Remis Cabalango"),
            "transporte": ("Remis Cabalango", "Proveeduría Tomaco"),
            "estacionamiento": ("Costa Norte", "Remis Cabalango"),
            "salud": ("Pregot Rosana", "Costa Norte"),
            "otros": ("Lavadero Rita", "Proveeduría Tomaco"),
        }
        for group, (included, excluded) in expectations.items():
            filtered = client.get(f"/servicios?grupo={group}")
            assert filtered.status_code == 200
            assert included in filtered.text
            assert excluded not in filtered.text

        compras = client.get("/servicios?grupo=compras")
        assert 'href="/servicios?grupo=compras">Almacenes y kioscos</a>' in compras.text

        assert client.get("/prestador/remis-cabalango").status_code == 200
        for path in ["/gastronomia", "/alojamientos", "/actividades"]:
            assert client.get(path).status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        engine.dispose()


def test_all_public_css_consumers_use_commerce_cache_key():
    templates = [
        "descubri_cabalango.html", "actividades.html", "portal_home.html",
        "actividad_detalle.html", "prestador.html", "portal_prestadores.html",
    ]
    for template in templates:
        source = (Path("app/templates") / template).read_text(encoding="utf-8")
        expected_version = "?v=20260903-home-event-flyer-mobile-contain-1" if template == "descubri_cabalango.html" else "?v=20260902-provider-amenities-1" if template == "prestador.html" else "?v=20260901-agenda-card-alignment-2" if template == "actividades.html" else "?v=20260903-event-detail-flyer-contain-1" if template == "actividad_detalle.html" else "?v=20260903-accommodation-mobile-filter-basis-1" if template == "portal_prestadores.html" else "?v=20260810-commerce-services-1"
        assert expected_version in source
