from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import (
    app,
    build_commerce_delivery_status,
    build_commerce_card_product_facts,
    build_commerce_card_schedule,
    build_public_card_chips,
    get_db,
)
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
        expected_version = "?v=20260903-home-event-flyer-mobile-contain-1" if template == "descubri_cabalango.html" else "?v=20260904-provider-single-gallery-1" if template == "prestador.html" else "?v=20260901-agenda-card-alignment-2" if template == "actividades.html" else "?v=20260903-event-detail-flyer-contain-1" if template == "actividad_detalle.html" else "?v=20260903-accommodation-mobile-filter-basis-1" if template == "portal_prestadores.html" else "?v=20260810-commerce-services-1"
        assert expected_version in source


def test_commerce_card_product_facts_keep_editorial_order_and_pluralize():
    empresa = Empresa(theme="servicios", subgrupo="compras")
    empresa.compras_productos_disponibles = '["fiambres", "bebidas frias", "alimentos", "bebidas"]'

    assert build_commerce_card_product_facts(empresa) == [
        "Alimentos", "Bebidas", "Bebidas frías", "+1 producto"
    ]

    empresa.compras_productos_disponibles = '["alimentos", "bebidas", "bebidas frias", "panificados", "fiambres"]'
    assert build_commerce_card_product_facts(empresa) == [
        "Alimentos", "Bebidas", "Bebidas frías", "+2 productos"
    ]


def test_commerce_delivery_status_is_tri_state_and_isolated():
    commerce = Empresa(theme="servicios", subgrupo="compras", delivery=True)
    assert build_commerce_delivery_status(commerce) == {
        "card_label": "Delivery", "detail_label": "Disponible", "icon": "delivery"
    }
    commerce.delivery = False
    assert build_commerce_delivery_status(commerce) == {
        "card_label": "Sin delivery", "detail_label": "No disponible", "icon": "delivery"
    }
    commerce.delivery = None
    assert build_commerce_delivery_status(commerce) is None
    assert build_commerce_delivery_status(Empresa(theme="servicios", subgrupo="transporte", delivery=True)) is None
    assert build_commerce_delivery_status(Empresa(theme="gastronomia", subgrupo="compras", delivery=False)) is None


def test_commerce_card_schedule_normalizes_safe_day_and_hour_patterns_without_mutation():
    empresa = Empresa(theme="servicios", subgrupo="compras")
    cases = [
        (
            "Días: Lunes, Martes, Miércoles, Jueves, Viernes, Sábado, Domingo | Horarios: 08 a 00hs | Todo el año: Sí",
            "Todos los días · 08:00–00:00",
        ),
        (
            "Días:Lunes,Martes,Miércoles,Jueves,Viernes,Sábado,Domingo|Horarios:08 a 00hs|Todo el año:Sí",
            "Todos los días · 08:00–00:00",
        ),
        ("Lunes a domingo", "Todos los días"),
        ("Días: Lunes, Martes, Miércoles, Jueves, Viernes | Horarios: 08:00 a 20:00", "Lun a vie · 08:00–20:00"),
        ("Días: Sábado, Domingo | Horarios: 09 a 22hs", "Sáb y dom · 09:00–22:00"),
        ("Días: Viernes, Sábado, Domingo | Horarios: 10 a 00hs", "Vie a dom · 10:00–00:00"),
        ("Días: Lunes, Miércoles, Viernes | Horarios: 09 a 18hs", "Lun · Mié · Vie · 09:00–18:00"),
        ("Días: Sábado | Horarios: 10 a 23hs", "Sáb · 10:00–23:00"),
        ("Horarios: 8:00 - 21:00", "08:00–21:00"),
        ("Horarios: 09:30 a 13:30", "09:30–13:30"),
        ("Horarios: 09:00 a 13:00 y 17:00 a 21:00", "09:00 a 13:00 y 17:00 a 21:00"),
    ]
    for original, expected in cases:
        empresa.horarios = original
        assert build_commerce_card_schedule(empresa) == expected
        assert empresa.horarios == original

    empresa.horarios = None
    assert build_commerce_card_schedule(empresa) is None
    empresa.horarios = ""
    assert build_commerce_card_schedule(empresa) is None


def test_compact_schedule_is_isolated_to_commerce_service_cards():
    raw = "Días: Lunes, Martes, Miércoles, Jueves, Viernes, Sábado, Domingo | Horarios: 08 a 00hs | Todo el año: Sí"
    commerce = Empresa(theme="servicios", subgrupo="compras", subtipo="Almacén", horarios=raw)
    transport = Empresa(theme="servicios", subgrupo="transporte", subtipo="Transporte", horarios=raw)
    lodging = Empresa(theme="alojamiento", subtipo="Posada", horarios=raw)

    assert build_public_card_chips(commerce, "servicios") == ["Almacén", "Todos los días · 08:00–00:00"]
    assert build_public_card_chips(transport, "servicios") == ["Transporte", raw]
    assert build_public_card_chips(lodging, "alojamientos") == []


def test_commerce_cards_show_product_summary_and_independent_ordered_actions():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = TestingSession()
    commerce = Empresa(
        nombre="Crisma almacén", slug="crisma", theme="servicios", subgrupo="compras",
        subtipo="Almacén", activo=True, direccion="El Vergel 229",
        maps_url="https://maps.example/crisma", whatsapp="+54 (9) 3541-123-456",
        delivery=True,
        horarios="Días: Lunes, Martes, Miércoles, Jueves, Viernes, Sábado, Domingo | Horarios: 08 a 00hs | Todo el año: Sí",
        compras_productos_disponibles='["alimentos","bebidas","bebidas frias","panificados","fiambres","carbon / lena","golosinas"]',
    )
    transport = Empresa(
        nombre="Remis aislado", slug="remis-aislado", theme="servicios", subgrupo="transporte",
        subtipo="Transporte", activo=True, maps_url="https://maps.example/remis", whatsapp="543541999999",
        delivery=False,
        compras_productos_disponibles='["alimentos","bebidas"]',
    )
    lodging = Empresa(
        nombre="Posada aislada", slug="posada-aislada", theme="alojamiento", subtipo="Posada",
        activo=True, maps_url="https://maps.example/posada", whatsapp="543541888888", wifi=True,
    )
    commerce_no_products = Empresa(
        nombre="Comercio mínimo", slug="comercio-minimo", theme="servicios", subgrupo="compras",
        activo=True,
    )
    commerce_maps_only = Empresa(
        nombre="Comercio con mapa", slug="comercio-mapa", theme="servicios", subgrupo="compras",
        activo=True, maps_url="https://maps.example/solo",
    )
    commerce_whatsapp_only = Empresa(
        nombre="Comercio con contacto", slug="comercio-contacto", theme="servicios", subgrupo="compras",
        activo=True, whatsapp="543541777777", delivery=False,
    )
    db.add_all([
        commerce, transport, lodging, commerce_no_products, commerce_maps_only,
        commerce_whatsapp_only,
    ])
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        html = client.get("/servicios").text
        commerce_card = html.split('href="/prestador/crisma"', 1)[1].split("</article>", 1)[0]
        assert "Todos los días · 08:00–00:00" in commerce_card
        assert commerce_card.count(">Delivery<") == 1
        assert "Sin delivery" not in commerce_card
        for raw_fragment in ("Días:", "Todo el año", "Lunes, Martes", "08 a 00hs"):
            assert raw_fragment not in commerce_card
        assert commerce_card.count("Alimentos") == 1
        assert commerce_card.count("Bebidas</span>") == 1
        assert commerce_card.count("Bebidas frías") == 1
        assert "Panificados" not in commerce_card
        assert "+4 productos" in commerce_card
        assert commerce_card.count("El Vergel 229") == 1
        assert commerce_card.count("Cómo llegar") == 1
        assert commerce_card.count("WhatsApp</a>") == 1
        assert commerce_card.index("Ver ficha") < commerce_card.index("Cómo llegar") < commerce_card.index("WhatsApp</a>")
        assert 'href="https://maps.example/crisma" target="_blank" rel="noopener"' in commerce_card
        assert 'href="https://wa.me/5493541123456" target="_blank" rel="noopener"' in commerce_card

        transport_card = html.split('href="/prestador/remis-aislado"', 1)[1].split("</article>", 1)[0]
        assert "Alimentos" not in transport_card
        assert "Cómo llegar" not in transport_card
        assert transport_card.count("WhatsApp</a>") == 1
        assert ">Delivery<" not in transport_card
        assert "Sin delivery" not in transport_card

        minimum_card = html.split('href="/prestador/comercio-minimo"', 1)[1].split("</article>", 1)[0]
        assert "prestador-chip-row" not in minimum_card
        assert "Cómo llegar" not in minimum_card
        assert "WhatsApp</a>" not in minimum_card
        assert ">Delivery<" not in minimum_card
        assert "Sin delivery" not in minimum_card

        maps_card = html.split('href="/prestador/comercio-mapa"', 1)[1].split("</article>", 1)[0]
        assert maps_card.count("Cómo llegar") == 1
        assert "WhatsApp</a>" not in maps_card

        whatsapp_card = html.split('href="/prestador/comercio-contacto"', 1)[1].split("</article>", 1)[0]
        assert "Cómo llegar" not in whatsapp_card
        assert whatsapp_card.count("WhatsApp</a>") == 1
        assert whatsapp_card.count("Sin delivery") == 1

        lodging_html = client.get("/alojamientos").text
        assert 'class="accommodation-card"' in lodging_html
        assert "Posada aislada" in lodging_html
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        engine.dispose()
