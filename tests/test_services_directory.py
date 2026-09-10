from pathlib import Path
import re

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import (
    SERVICIOS_GRUPOS,
    SERVICIOS_FILTROS_PUBLICOS,
    app,
    build_commerce_delivery_status,
    build_commerce_card_product_facts,
    build_commerce_card_schedule,
    build_public_card_chips,
    get_db,
    is_laundry_service,
    public_service_category_key,
    service_card_kicker,
)
from app.models import Empresa


def test_services_taxonomy_filters_and_compatibility():
    assert SERVICIOS_GRUPOS["compras"] == "Compras"
    assert list(SERVICIOS_FILTROS_PUBLICOS) == [
        "almacenes", "locales", "transporte", "estacionamiento", "salud", "lavanderia", "otros"
    ]
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = TestingSession()
    records = [
        ("Almacén del Río", "almacen-rio", "compras", "Almacén", True),
        ("Manos de Cabalango", "manos-cabalango", "compras", "  PRODUCTOS   REGIONALES ", True),
        ("Remis Cabalango", "remis-cabalango", "transporte", "Remis", True),
        ("Costa Norte", "costa-norte", "estacionamiento", "Playa de estacionamiento", True),
        ("Pregot Rosana", "pregot-rosana", "salud", "Kinesiología", True),
        ("Lavadero Rita", "lavadero-rita", "otros", "Lavadero", True),
        ("Lavadero Centro", "lavadero-centro", "otros", "Lavadero de ropa", True),
        ("Histórico", "historico", "otros", "Gomería", True),
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
        assert 'href="/servicios?filtro=almacenes">Almacenes y kioscos</a>' in response.text
        filters = response.text.split('<nav class="services-filters"', 1)[1].split("</nav>", 1)[0]
        assert re.findall(r">([^<>]+)</a>", filters) == [
            "Todo", "Almacenes y kioscos", "Productos locales y artesanías", "Transporte",
            "Estacionamiento", "Salud y bienestar", "Lavandería", "Otros servicios",
        ]
        assert ">Compras</a>" not in filters
        assert "Servicios útiles" not in response.text
        assert "PARA VECINOS Y VISITANTES" in response.text
        assert "Comercio inactivo" not in response.text
        assert "Histórico" in response.text

        expectations = {
            "compras": ("Almacén del Río", "Remis Cabalango"),
            "transporte": ("Remis Cabalango", "Almacén del Río"),
            "estacionamiento": ("Costa Norte", "Remis Cabalango"),
            "salud": ("Pregot Rosana", "Costa Norte"),
            "otros": ("Lavadero Rita", "Almacén del Río"),
        }
        for group, (included, excluded) in expectations.items():
            filtered = client.get(f"/servicios?grupo={group}")
            assert filtered.status_code == 200
            assert included in filtered.text
            assert excluded not in filtered.text

        compras = client.get("/servicios?grupo=compras")
        assert 'href="/servicios?filtro=almacenes">Almacenes y kioscos</a>' in compras.text
        assert "Almacenes y kioscos" in compras.text
        assert "Productos locales y artesanías" in compras.text
        assert "Almacén del Río" in compras.text
        assert "Manos de Cabalango" in compras.text

        locales = client.get("/servicios?grupo=compras&tipo=locales")
        assert "Manos de Cabalango" in locales.text
        assert "Almacén del Río" not in locales.text
        assert "Descubrí sabores, objetos y productos creados por emprendedores de Cabalango." in locales.text

        almacenes = client.get("/servicios?grupo=compras&tipo=almacenes")
        assert "Almacén del Río" in almacenes.text
        assert "Manos de Cabalango" not in almacenes.text

        public_expectations = {
            "almacenes": ("Almacén del Río", "Manos de Cabalango"),
            "locales": ("Manos de Cabalango", "Almacén del Río"),
            "transporte": ("Remis Cabalango", "Costa Norte"),
            "estacionamiento": ("Costa Norte", "Pregot Rosana"),
            "salud": ("Pregot Rosana", "Lavadero Rita"),
            "lavanderia": ("Lavadero Rita", "Histórico"),
            "otros": ("Histórico", "Lavadero Rita"),
        }
        for public_filter, (included, excluded) in public_expectations.items():
            filtered = client.get(f"/servicios?filtro={public_filter}")
            assert included in filtered.text
            assert excluded not in filtered.text
        assert "¿Qué estás buscando?" not in client.get("/servicios?filtro=almacenes").text
        assert "Almacén" in client.get("/servicios?filtro=almacenes").text
        assert "Compras ·" not in client.get("/servicios?filtro=almacenes").text
        assert "Productos locales y artesanías" in client.get("/servicios?filtro=locales").text
        assert "Lavandería" in client.get("/servicios?filtro=lavanderia").text

        assert client.get("/prestador/remis-cabalango").status_code == 200
        for path in ["/gastronomia", "/alojamientos", "/actividades"]:
            assert client.get(path).status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        engine.dispose()


def test_public_service_category_uses_only_structured_taxonomy():
    cases = [
        ("compras", "Almacén", "almacenes"),
        ("compras", "Productos regionales", "locales"),
        ("transporte", "Remis", "transporte"),
        ("estacionamiento", "Estacionamiento", "estacionamiento"),
        ("salud", "Farmacia", "salud"),
        ("otros", "LAVADERO", "lavanderia"),
        ("otros", "lavadero de ropa", "lavanderia"),
        ("otros", "Gomería", "otros"),
    ]
    for group, subtype, expected in cases:
        empresa = Empresa(theme="servicios", subgrupo=group, subtipo=subtype)
        assert public_service_category_key(empresa) == expected
    misleading = Empresa(
        theme="servicios", subgrupo="otros", subtipo="Gomería",
        nombre="Lavandería", descripcion="Lavado de ropa",
    )
    assert not is_laundry_service(misleading)
    assert public_service_category_key(misleading) == "otros"
    assert service_card_kicker(Empresa(theme="servicios", subgrupo="otros", subtipo="Lavadero")) == "Lavandería"


def test_services_overview_groups_previews_without_changing_filtered_results():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = TestingSession()
    purchases = [
        Empresa(
            nombre=f"Compra editorial {index}", slug=f"compra-{index}",
            theme="servicios", subgrupo="compras", subtipo="Almacén",
            activo=True, horarios="Lunes a domingo", direccion="Centro",
            maps_url=f"https://maps.example/compra-{index}", whatsapp="543541111111",
        )
        for index in range(5)
    ]
    records = purchases + [
        Empresa(nombre="Remis portada", slug="remis-portada", theme="servicios", subgrupo="transporte", subtipo="Remis", activo=True),
        Empresa(nombre="Parking portada", slug="parking-portada", theme="servicios", subgrupo="estacionamiento", subtipo="Estacionamiento", activo=True),
        Empresa(nombre="Salud portada", slug="salud-portada", theme="servicios", subgrupo="salud", subtipo="Farmacia", activo=True),
        Empresa(nombre="Lavadero portada", slug="lavadero-portada", theme="servicios", subgrupo="otros", subtipo="Lavadero", activo=True),
    ]
    db.add_all(records)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        overview = client.get("/servicios")
        assert overview.status_code == 200
        html = overview.text
        assert '<a class="is-active" href="/servicios">Todo</a>' in html
        headings = [
            'id="services-group-almacenes">Almacenes y kioscos',
            'id="services-group-transporte">Transporte',
            'id="services-group-estacionamiento">Estacionamiento',
            'id="services-group-salud">Salud y bienestar',
            'id="services-group-lavanderia">Lavandería',
        ]
        assert all(heading in html for heading in headings)
        assert [html.index(heading) for heading in headings] == sorted(html.index(heading) for heading in headings)
        expected_ctas = {
            "almacenes": "Ver almacenes y kioscos",
            "transporte": "Ver transporte",
            "estacionamiento": "Ver estacionamientos",
            "salud": "Ver salud y bienestar",
            "lavanderia": "Ver lavandería",
        }
        for key, copy in expected_ctas.items():
            assert f'href="/servicios?filtro={key}">{copy}' in html

        compras_block = html.split('id="services-group-almacenes"', 1)[1].split('id="services-group-transporte"', 1)[0]
        estacionamiento_block = html.split('id="services-group-estacionamiento"', 1)[1].split('id="services-group-salud"', 1)[0]
        assert compras_block.count('class="prestador-card prestador-card-premium"') == 3
        assert "Parking portada" not in compras_block
        assert "Compra editorial" not in estacionamiento_block
        assert "Ver ficha" in compras_block
        assert "Cómo llegar" in compras_block
        assert "WhatsApp" in compras_block
        assert "Todos los días" in compras_block

        filtered = client.get("/servicios?grupo=compras")
        assert filtered.status_code == 200
        assert filtered.text.count('class="prestador-card prestador-card-premium"') == 5
        assert "¿Qué estás buscando?" in filtered.text
        assert "Almacenes y kioscos" in filtered.text
        assert "Productos locales y artesanías" in filtered.text
        assert '<a class="is-active" href="/servicios">Todo</a>' not in filtered.text
        assert 'href="/servicios?filtro=almacenes">Almacenes y kioscos</a>' in filtered.text

        db.query(Empresa).filter(Empresa.subgrupo == "otros").delete()
        db.commit()
        without_others = client.get("/servicios").text
        assert 'id="services-group-lavanderia"' not in without_others
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
        expected_version = "?v=20260908-home-photo-signature-1" if template == "descubri_cabalango.html" else "?v=20260904-provider-single-gallery-1" if template == "prestador.html" else "?v=20260901-agenda-card-alignment-2" if template == "actividades.html" else "?v=20260903-event-detail-flyer-contain-1" if template == "actividad_detalle.html" else "?v=20260910-public-service-filters-1" if template == "portal_prestadores.html" else "?v=20260810-commerce-services-1"
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
            "Días: Lunes a lunes | Horarios: Lunes a lunes 9 a 23",
            "Todos los días · 09:00–23:00",
        ),
        (
            "Días: Lunes, Martes, Miércoles, Jueves, Viernes, Sábado, Domingo | Horarios: 08 a 00hs | Todo el año: Sí",
            "Todos los días · 08:00–00:00",
        ),
        (
            "Días:Lunes,Martes,Miércoles,Jueves,Viernes,Sábado,Domingo|Horarios:08 a 00hs|Todo el año:Sí",
            "Todos los días · 08:00–00:00",
        ),
        ("Lunes a domingo", "Todos los días"),
        ("Días: Todos los dias | Horarios: Todos los dias 9 a 23", "Todos los días · 09:00–23:00"),
        ("Días: Todos los días | Horarios: Todos los días 9:00 a 23:00", "Todos los días · 09:00–23:00"),
        ("Días: Lunes a domingo | Horarios: Lunes a domingo 9 a 23", "Todos los días · 09:00–23:00"),
        ("Días: Lunes, Martes, Miércoles, Jueves, Viernes, Sábado, Domingo | Horarios: Lunes a domingo de 9 a 20 horas", "Todos los días · 09:00–20:00"),
        ("Días: Lunes, Martes, Miércoles, Jueves, Viernes, Sábado, Domingo | Horarios: Lunes a domingos de 9 a 20 horas", "Todos los días · 09:00–20:00"),
        ("lunes a lunes 9 a 20", "Todos los días · 09:00–20:00"),
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


def test_compact_schedule_is_applied_to_all_service_cards_only():
    raw = "Días: Lunes, Martes, Miércoles, Jueves, Viernes, Sábado, Domingo | Horarios: 08 a 00hs | Todo el año: Sí"
    commerce = Empresa(theme="servicios", subgrupo="compras", subtipo="Almacén", horarios=raw)
    transport = Empresa(theme="servicios", subgrupo="transporte", subtipo="Transporte", horarios=raw)
    lodging = Empresa(theme="alojamiento", subtipo="Posada", horarios=raw)

    assert build_public_card_chips(commerce, "servicios") == ["Almacén", "Todos los días · 08:00–00:00"]
    assert build_public_card_chips(transport, "servicios") == ["Transporte", "Todos los días · 08:00–00:00"]
    assert build_public_card_chips(lodging, "alojamientos") == []


def test_commerce_card_prioritizes_beef_chicken_and_short_stationery_label():
    company = Empresa(
        theme="servicios", subgrupo="compras", subtipo="Almacén",
        compras_productos_disponibles=(
            '["alimentos","bebidas","congelados","carne vacuna","pollo",'
            '"articulos de libreria y fotocopias"]'
        ),
    )
    assert build_commerce_card_product_facts(company) == [
        "Carne vacuna", "Pollo", "Librería / fotocopias", "+3 productos",
    ]

    company.compras_productos_disponibles = '["carne vacuna","alimentos","bebidas","bebidas frias"]'
    assert build_commerce_card_product_facts(company) == [
        "Carne vacuna", "Alimentos", "Bebidas", "+1 producto",
    ]
    company.compras_productos_disponibles = '["pollo","alimentos","bebidas","bebidas frias"]'
    assert build_commerce_card_product_facts(company) == [
        "Pollo", "Alimentos", "Bebidas", "+1 producto",
    ]


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
        horarios="Días: Lunes, Martes, Miércoles, Jueves, Viernes, Sábado, Domingo | Horarios: Lunes a domingo de 9 a 20 horas | Todo el año: Sí",
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
    service_maps_only = Empresa(
        nombre="Estacionamiento con mapa", slug="servicio-mapa", theme="servicios", subgrupo="estacionamiento",
        activo=True, maps_url="https://maps.example/solo",
    )
    service_whatsapp_only = Empresa(
        nombre="Transporte con contacto", slug="servicio-contacto", theme="servicios", subgrupo="transporte",
        activo=True, whatsapp="543541777777", delivery=False,
    )
    db.add_all([
        commerce, transport, lodging, commerce_no_products, service_maps_only,
        service_whatsapp_only,
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
        assert "Todos los días · 09:00–20:00" in transport_card
        for raw_fragment in ("Días:", "Horarios:", "Todo el año:"):
            assert raw_fragment not in transport_card
        assert transport_card.count("Cómo llegar") == 1
        assert transport_card.count("WhatsApp</a>") == 1
        assert transport_card.index("Ver ficha") < transport_card.index("Cómo llegar") < transport_card.index("WhatsApp</a>")
        assert ">Delivery<" not in transport_card
        assert "Sin delivery" not in transport_card

        minimum_card = html.split('href="/prestador/comercio-minimo"', 1)[1].split("</article>", 1)[0]
        assert "prestador-chip-row" not in minimum_card
        assert "Cómo llegar" not in minimum_card
        assert "WhatsApp</a>" not in minimum_card
        assert ">Delivery<" not in minimum_card
        assert "Sin delivery" not in minimum_card

        maps_card = html.split('href="/prestador/servicio-mapa"', 1)[1].split("</article>", 1)[0]
        assert maps_card.count("Cómo llegar") == 1
        assert "WhatsApp</a>" not in maps_card

        whatsapp_card = html.split('href="/prestador/servicio-contacto"', 1)[1].split("</article>", 1)[0]
        assert "Cómo llegar" not in whatsapp_card
        assert whatsapp_card.count("WhatsApp</a>") == 1
        assert "Sin delivery" not in whatsapp_card

        lodging_html = client.get("/alojamientos").text
        assert 'class="accommodation-card"' in lodging_html
        assert "Posada aislada" in lodging_html
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        engine.dispose()
