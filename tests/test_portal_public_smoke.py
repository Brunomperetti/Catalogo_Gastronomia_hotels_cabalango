import json
import re
from types import SimpleNamespace

import pytest

pytest.importorskip("httpx", reason="FastAPI TestClient requires httpx")
from fastapi.testclient import TestClient

from app.main import app, run_startup_db_maintenance


@pytest.fixture(scope="module", autouse=True)
def _prepare_public_portal_database():
    run_startup_db_maintenance()


PUBLIC_SECTIONS = [
    ("/", "Inicio", "Descubrí Cabalango"),
    ("/gastronomia", "Gastronomía", "Gastronomía en Cabalango"),
    ("/alojamientos", "Alojamientos", "Alojamientos en Cabalango"),
    ("/servicios", "Compras y servicios", "Compras y servicios"),
    ("/actividades", "Qué hacer", "Qué hacer"),
]

SECTION_ILLUSTRATIONS = [
    ("/gastronomia", "gastronomia"),
    ("/alojamientos", "alojamientos"),
    ("/servicios", "servicios"),
    ("/actividades", "actividades"),
]


def _nav_markup(html: str) -> str:
    match = re.search(r'<nav class="portal-topnav"[^>]*>(.*?)</nav>', html, re.S)
    assert match, "public navigation should render"
    return match.group(1)


def _active_nav_labels(html: str) -> list[str]:
    nav = _nav_markup(html)
    return re.findall(r'<a class="[^"]*is-active[^"]*"[^>]*>([^<]+)</a>', nav)


def test_portal_home_smoke():
    response = TestClient(app).get("/", follow_redirects=False)

    assert response.status_code == 200
    assert "Descubrí Cabalango" in response.text
    for label in ["Historia", "Ubicación", "Naturaleza", "Vida local"]:
        assert label in response.text
    for visitor_copy in [
        "Río, monte y tiempo para disfrutar sin apuro.",
        "Río y balnearios",
        "Todo para tu visita",
        "Viví Cabalango a tu manera",
        "Escapada de fin de semana",
        "Plan en familia",
        "Tip para tu visita",
    ]:
        assert visitor_copy in response.text
    for href in [
        "/actividades",
        "/alojamientos",
        "/gastronomia",
        "/servicios?grupo=compras",
        "/como-llegar",
    ]:
        assert f'href="{href}"' in response.text
    assert response.text.count("destination-story-more") == 3
    assert 'id="como-llegar"' in response.text
    assert "Cómo llegar y moverse" in response.text
    assert 'href="#como-llegar"' not in response.text
    assert "?v=20260903-home-event-flyer-mobile-contain-1" in response.text
    for dialog_id in [
        "destination-dialog-historia",
        "destination-dialog-ubicacion",
        "destination-dialog-naturaleza",
        "destination-dialog-vida-local",
    ]:
        assert f'id="{dialog_id}"' in response.text
    assert "/static/js/portal-dialogs.js" in response.text
    assert "destination-dialog-content" in response.text
    for full_text in [
        "Un destino serrano de ritmo pausado",
        "Cabalango se encuentra en el Valle de Punilla",
        "Río, balnearios, senderos",
        "Ferias, sabores caseros",
    ]:
        assert full_text in response.text
    assert "Logo_Cabalango.png" in response.text
    assert "Postales del río y las sierras" not in response.text
    assert "Lugares para descubrir" not in response.text
    assert "Todas las fotos" not in response.text
    assert "Organizá tu visita a tu ritmo" in response.text
    assert 'href="/alojamientos">Alojamientos' in response.text
    assert 'href="/gastronomia">Gastronomía' in response.text
    assert 'href="/actividades">Qué hacer' in response.text
    assert "Rangos orientativos" in response.text
    for nearby_copy in [
        "Ciudades cerca de Cabalango",
        "Villa Carlos Paz",
        "Tanti",
        "Cosquín",
        "A pocos minutos",
        "Muy cerca",
        "A 25 km aprox.",
        "a 45 km aprox.",
    ]:
        assert nearby_copy in response.text
    assert "destination-nearby-map" in response.text
    assert "Si buscás más movimiento" not in response.text


def test_travel_guide_is_public_compact_and_uses_external_sources():
    response = TestClient(app).get("/como-llegar")
    html = response.text

    assert response.status_code == 200
    for copy in ["Cómo llegar a Cabalango", "En avión", "En colectivo", "En auto", "Remis Cabalango", "Horarios de Fono Bus"]:
        assert copy in html
    assert 'id="como-llegar"' in html
    assert "Aeropuerto → conexión" not in html
    assert re.search(r'<a[^>]+href="https://wa.me/541166483805"[^>]+target="_blank"[^>]+rel="noopener noreferrer"[^>]*>Consultar traslado por WhatsApp', html)
    assert re.search(r'<a[^>]+href="https://drive.google.com/file/d/12BSVtKJdSX54f6dZAnfxBOMhVF-5P-w7/view\?usp=drive_link"[^>]+target="_blank"[^>]+rel="noopener noreferrer"[^>]*>Ver horarios de Punilla', html)
    assert "Abrir en Google Maps" in html
    for label in ("Abrir en Google Maps", "Consultar traslado por WhatsApp", "Ver horarios de Punilla"):
        assert "travel-guide__action" in html.split(label, 1)[0].rsplit("<a", 1)[1]
    for label in ("Dónde dormir", "Dónde comer", "Qué hacer"):
        assert "travel-guide__action" not in html.split(label, 1)[0].rsplit("<a", 1)[1]
    assert "<table" not in html.lower()
    assert "fonobus_schedule" not in html
    assert "horarios_fonobus.json" not in html
    assert not re.search(r"\b(?:08:20|23:40)\b", html)


def test_travel_information_does_not_expand_home():
    html = TestClient(app).get("/").text

    for travel_only_copy in ["En avión", "En colectivo", "Remis Cabalango", "Horarios de Fono Bus"]:
        assert travel_only_copy not in html
    for existing_link in ["/alojamientos", "/gastronomia", "/actividades", "/servicios?grupo=compras"]:
        assert f'href="{existing_link}"' in html
    assert 'href="#lugares"' in html
    assert "aproximadamente 6 km" not in html


def test_weather_parses_apparent_temperature_and_up_to_seven_days(monkeypatch):
    import app.main as main_module

    payload = {
        "current": {"temperature_2m": 21, "apparent_temperature": 19.5, "weather_code": 1, "wind_speed_10m": 12},
        "daily": {
            "time": [f"2026-08-{day:02d}" for day in range(12, 19)],
            "weather_code": [1] * 7,
            "temperature_2m_max": [24] * 7,
            "temperature_2m_min": [10] * 7,
            "precipitation_probability_max": [5] * 7,
        },
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps(payload).encode()

    monkeypatch.setattr(main_module.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    main_module._weather_cache.update({"expires_at": None, "data": None})
    weather = main_module.get_cabalango_weather()

    assert weather["apparent_temperature"] == 19.5
    assert len(weather["forecast"]) == 6
    assert weather["forecast"][0]["label"] == "Mañana"


def test_weather_fallback_keeps_seasonal_guidance_without_dynamic_values(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "get_cabalango_weather", lambda: {
        "available": False,
        "message": "Clima no disponible por el momento.",
    })
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "Clima no disponible por el momento" in response.text
    assert "Rangos orientativos" in response.text
    assert "Primavera" in response.text
    assert "None" not in response.text
    assert "weather-temp" not in response.text
    assert "Actualizar clima" in response.text


def test_successful_weather_does_not_show_refresh_button(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "get_cabalango_weather", lambda: {
        "available": True, "temperature": 21, "apparent_temperature": 20,
        "condition": "Despejado", "min": 12, "max": 24,
        "rain_probability": 0, "wind": 8, "advice": "Ideal para recorrer.",
        "forecast": [],
    })

    assert "Actualizar clima" not in TestClient(app).get("/").text


def test_weather_refresh_forces_request_and_redirects_to_clean_url(monkeypatch):
    import app.main as main_module

    calls = []
    monkeypatch.setattr(main_module, "get_cabalango_weather", lambda force_refresh=False: calls.append(force_refresh) or {
        "available": False,
        "message": "Clima no disponible por el momento.",
    })
    response = TestClient(app).get("/?refresh_weather=1", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/#weather-title"
    assert calls == [True]


def test_weather_service_failure_returns_explicit_fallback(monkeypatch):
    import app.main as main_module

    def fail_request(*args, **kwargs):
        raise TimeoutError("Open-Meteo unavailable")

    monkeypatch.setattr(main_module.urllib.request, "urlopen", fail_request)
    main_module._weather_cache.update({"expires_at": None, "data": None})

    assert main_module.get_cabalango_weather() == {
        "available": False,
        "message": "Clima no disponible por el momento.",
    }


def test_destination_guide_uses_real_width_containment_not_master_clipping():
    css = open("app/static/css/portal.css", encoding="utf-8").read()
    guide_rules = re.findall(r"\.destination-guide\s*\{([^}]*)\}", css)

    assert guide_rules
    assert all("overflow: clip" not in rule for rule in guide_rules)
    planning_css = css[css.index(".destination-guide .destination-planning {"):]
    desktop_weather_days = planning_css[
        planning_css.index(".destination-guide .destination-planning .weather-days {"):
        planning_css.index(".destination-guide .destination-planning .weather-day {")
    ]
    mobile_planning = planning_css[planning_css.index("@media (max-width: 520px)"):]
    mobile_weather_days = mobile_planning[
        mobile_planning.index(".destination-guide .destination-planning .weather-days {"):
        mobile_planning.index(".destination-guide .destination-planning .season-grid {")
    ]
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in desktop_weather_days
    mobile_season_grid = mobile_planning[
        mobile_planning.index(".destination-guide .destination-planning .season-grid {"):
        mobile_planning.index(".destination-guide .destination-planning .season-grid > div:nth-of-type(n)")
    ]
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in mobile_weather_days
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in mobile_season_grid
    assert ".destination-nearby," in css


def test_home_hides_empty_video_section(monkeypatch):
    import app.main as main_module

    content = main_module.get_destino_content(next(main_module.get_db()))
    monkeypatch.setattr(content, "video_url", "")
    monkeypatch.setattr(main_module, "get_destino_content", lambda db: content)
    monkeypatch.setattr(main_module, "get_public_destino_media", lambda db, tipo=None: [])
    monkeypatch.setattr(main_module, "build_home_agenda", lambda db: [])

    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "Recorré el destino" not in response.text
    assert "Estamos preparando recorridos en video" not in response.text
    assert "destination-video-section" not in response.text


def test_home_preserves_editable_hero_content(monkeypatch):
    import app.main as main_module

    editable_intro = "Una introducción editorial cargada desde administración."
    editable_photo_title = "El río al caer la tarde"
    content = SimpleNamespace(
        introduccion=editable_intro,
        historia="Historia local",
        ubicacion="Ubicación serrana",
        naturaleza="Naturaleza junto al río",
        recomendaciones="Traé calzado cómodo.",
        vida_local="Vida local",
        video_url="",
    )
    photo = SimpleNamespace(
        id=1,
        destacado=True,
        image_path="/static/img/no-image.jpg",
        titulo=editable_photo_title,
        categoria="rio_naturaleza",
        descripcion=None,
    )
    monkeypatch.setattr(main_module, "get_destino_content", lambda db: content)
    monkeypatch.setattr(main_module, "get_public_destino_media", lambda db, tipo=None: [photo] if tipo == "foto" else [])
    monkeypatch.setattr(main_module, "build_home_agenda", lambda db: [])

    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert editable_intro in response.text
    assert editable_photo_title in response.text

    content.introduccion = None
    fallback_response = TestClient(app).get("/")
    assert fallback_response.status_code == 200
    assert "Descubrí balnearios, alojamientos, sabores y experiencias locales en un rincón tranquilo de las sierras de Córdoba." in fallback_response.text


def test_home_agenda_is_hidden_when_empty_and_renders_compact_event_cards(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "build_home_agenda", lambda db: [])
    empty_html = TestClient(app).get("/").text
    assert '<section class="home-agenda"' not in empty_html
    assert "Descubrí Cabalango" in empty_html

    with_image = SimpleNamespace(
        titulo="Encuentro del río", slug="encuentro-del-rio", imagen_url="/media/evento.webp",
        estado="reprogramado", oficial=True, categoria="cultura", descripcion_corta="Una propuesta local.", lugar="Costanera",
    )
    without_image = SimpleNamespace(
        titulo="Taller serrano", slug="taller-serrano", imagen_url=None,
        estado="programado", oficial=False, categoria="otros", descripcion_corta=None, lugar=None,
    )
    cards = [
        {"item": with_image, "label": "ESTA SEMANA", "date_label": "21–22 NOV", "datetime": "2026-11-21T18:00:00-03:00", "schedule": "18:00 hs", "category": "Cultura"},
        {"item": without_image, "label": "PRÓXIMAMENTE", "date_label": "25 NOV", "datetime": "2026-11-25T10:00:00-03:00", "schedule": None, "category": "Otros"},
    ]
    monkeypatch.setattr(main_module, "build_home_agenda", lambda db: cards)
    html = TestClient(app).get("/").text

    assert html.count('<article class="home-agenda-event') == 2
    assert 'data-count="2"' in html
    assert "NUEVA FECHA" in html and "ESTA SEMANA" in html and "EVENTO OFICIAL" in html
    assert 'src="/media/evento.webp" alt="Encuentro del río" loading="lazy"' in html
    assert 'href="/actividades/encuentro-del-rio"' in html
    assert 'href="/actividades/taller-serrano"' in html
    assert 'href="/actividades">Ver agenda completa' in html
    assert '<time datetime="2026-11-21T18:00:00-03:00">21–22 NOV</time>' in html
    assert html.index("Encuentro del río") < html.index("Taller serrano")
    assert 'src=""' not in html


@pytest.mark.parametrize("photo_count", [0, 1, 4])
def test_home_photo_fallbacks_render_for_zero_one_and_multiple_photos(monkeypatch, photo_count):
    import app.main as main_module

    photos = [
        SimpleNamespace(id=index + 1, destacado=index == 0, image_path=f"/media/postal-{index + 1}.webp", titulo=f"Postal {index + 1}", categoria="rio_naturaleza", descripcion=None)
        for index in range(photo_count)
    ]
    monkeypatch.setattr(main_module, "get_public_destino_media", lambda db, tipo=None: photos if tipo == "foto" else [])
    monkeypatch.setattr(main_module, "build_home_agenda", lambda db: [])
    response = TestClient(app).get("/")
    assert response.status_code == 200
    if photo_count >= 4:
        about = response.text[response.text.index('class="destination-about-intro"'):response.text.index('class="destination-story-grid"')]
        journeys = response.text[response.text.index('class="destination-journeys"'):response.text.index('class="destination-planning"')]
        assert '/media/postal-2.webp' in about
        assert '/media/postal-3.webp' in journeys
        assert '/media/postal-1.webp' not in about


def test_home_editorial_order_and_redundancy(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "build_home_agenda", lambda db: [])
    html = TestClient(app).get("/").text
    ordered = [
        "destination-editorial-hero", "destination-quick-links", "destination-about",
        "destination-journeys", "destination-planning", "destination-nearby",
        "destination-cta",
    ]
    assert [html.index(marker) for marker in ordered] == sorted(html.index(marker) for marker in ordered)
    assert "Balnearios, monte y caminatas tranquilas" not in html
    assert 'id="clima"' in html and 'id="fotos"' not in html and 'id="como-llegar"' in html


def test_home_hero_and_quick_links_navigation(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "build_home_agenda", lambda db: [])
    html = TestClient(app).get("/").text
    hero_actions = re.search(r'<div class="hero-actions".*?</div>', html, re.S).group()
    quick_links = re.search(
        r'<nav class="destination-quick-links".*?</nav>', html, re.S
    ).group()

    assert "Explorar Cabalango" in hero_actions
    for duplicate in ("Dónde dormir", "Dónde comer", "Ver lugares"):
        assert duplicate not in hero_actions

    for label in (
        "Dónde dormir", "Dónde comer", "Qué hacer", "Almacenes y kioscos",
        "Cómo llegar y moverse", "Balnearios y río",
    ):
        assert label in quick_links
    assert quick_links.count("<a ") == 6
    assert re.search(
        r'<a href="#lugares"><svg aria-hidden="true"><use href="#icon-water"/></svg>'
        r'<span>Balnearios y río</span></a>',
        quick_links,
    )
    template = __import__("pathlib").Path(
        "app/templates/descubri_cabalango.html"
    ).read_text(encoding="utf-8")
    assert 'id="lugares"' in template

    css = __import__("pathlib").Path("app/static/css/portal.css").read_text(encoding="utf-8")
    desktop_rule = re.search(
        r"\.destination-quick-links > div \{([^}]*)\}", css
    ).group(1)
    tablet_block = re.search(
        r"@media \(max-width: 1024px\) \{(.*?)\n\}", css, re.S
    ).group(1)
    mobile_block = re.search(
        r"@media \(max-width: 520px\) \{(.*?)\n\}", css, re.S
    ).group(1)
    assert "grid-template-columns: repeat(6, minmax(0, 1fr))" in desktop_rule
    assert re.search(
        r"\.destination-quick-links > div \{[^}]*"
        r"grid-template-columns: repeat\(3, minmax\(0, 1fr\)\)",
        tablet_block,
    )
    assert re.search(
        r"\.destination-quick-links > div \{[^}]*"
        r"grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)",
        mobile_block,
    )
    assert re.search(
        r"\.destination-quick-links > p \{[^}]*padding-inline: 20px",
        mobile_block,
    )


def test_home_planning_preserves_editable_tip_and_cta_has_no_image(monkeypatch):
    import app.main as main_module

    content = main_module.get_destino_content(next(main_module.get_db()))
    forecast = [
        {"label": label, "min": 10, "max": 22, "condition": "Despejado", "rain_probability": 0}
        for label in ["Hoy", "Mañana", "Jueves", "Viernes", "Sábado", "Domingo"]
    ]
    monkeypatch.setattr(main_module, "get_cabalango_weather", lambda: {
        "available": True, "temperature": 20, "condition": "Despejado", "min": 10,
        "max": 22, "advice": "Llevá abrigo liviano.", "apparent_temperature": 20,
        "rain_probability": 0, "wind": 8, "forecast": forecast,
    })
    monkeypatch.setattr(content, "recomendaciones", "TIP TEST")
    monkeypatch.setattr(main_module, "get_destino_content", lambda db: content)
    html = TestClient(app).get("/").text
    planning = html[html.index('class="destination-planning"'):html.index('class="destination-nearby"')]
    cta = html[html.index('class="destination-cta"'):html.index("</main>")]
    assert "TIP TEST" in planning
    assert "Planificá tu visita" in planning
    assert "El clima, antes de salir" in planning
    assert "Ahora y los próximos días" not in planning
    assert "Datos útiles" in planning
    assert "Próximos días" in planning
    assert "Mejor época para visitar" in planning
    assert planning.count('class="weather-day"') == 6
    assert "<img" not in cta
    for label in ["Alojamientos", "Gastronomía", "Qué hacer"]:
        assert label in cta


def test_home_editorial_order_includes_agenda_when_present(monkeypatch):
    import app.main as main_module

    item = SimpleNamespace(titulo="Evento", slug="evento", imagen_url=None, estado="programado", oficial=False, categoria="otros", descripcion_corta=None, lugar=None)
    card = {"item": item, "label": None, "date_label": "20 AGO", "datetime": "2026-08-20", "schedule": None, "category": "Otros"}
    monkeypatch.setattr(main_module, "build_home_agenda", lambda db: [card])
    html = TestClient(app).get("/").text
    ordered = ["destination-editorial-hero", "destination-quick-links", "home-agenda", "destination-about", "destination-journeys", "destination-planning", "destination-nearby", "destination-cta"]
    assert [html.index(marker) for marker in ordered] == sorted(html.index(marker) for marker in ordered)
    assert 'data-count="1"' in html

def test_descubri_cabalango_redirects_to_home():
    response = TestClient(app).get("/descubri-cabalango", follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == "/"


def test_cabalango_legacy_redirects_to_home():
    response = TestClient(app).get("/cabalango", follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == "/"


def test_public_navigation_has_no_independent_descubri_link():
    response = TestClient(app).get("/")

    nav = _nav_markup(response.text)
    assert 'href="/descubri-cabalango"' not in nav
    assert ">Descubrí Cabalango</a>" not in nav


@pytest.mark.parametrize(("path", "active_label", "expected_text"), PUBLIC_SECTIONS)
def test_public_sections_smoke_and_active_navigation(path, active_label, expected_text):
    response = TestClient(app).get(path)

    assert response.status_code == 200
    assert expected_text in response.text
    assert "Logo_Cabalango.png" in response.text
    assert _active_nav_labels(response.text) == [active_label]


@pytest.mark.parametrize(("path", "variant"), SECTION_ILLUSTRATIONS)
def test_public_sections_render_editorial_illustrations(path, variant):
    response = TestClient(app).get(path)

    assert response.status_code == 200
    assert "portal-section-hero-art" in response.text
    assert "portal-section-illustration" in response.text
    assert f'data-section-illustration="{variant}"' in response.text
    assert _active_nav_labels(response.text)
    assert len(_active_nav_labels(response.text)) == 1


def test_accommodation_browsing_grid_and_filters_smoke():
    response = TestClient(app).get("/alojamientos")

    assert response.status_code == 200
    assert "accommodation-results-header" in response.text
    assert "alojamiento" in response.text and "encontrado" in response.text
    assert 'class="accommodation-more-filters"' in response.text
    assert "<summary>Más filtros" in response.text
    for parameter in [
        "tipo",
        "capacidad",
        "habitaciones",
        "precio_max",
        "orden",
        "pileta",
        "rio",
        "mascotas",
        "cochera",
        "wifi",
        "parrilla",
    ]:
        assert f'name="{parameter}"' in response.text
    assert _active_nav_labels(response.text) == ["Alojamientos"]
    assert "Logo_Cabalango.png" in response.text

    if "accommodation-grid" in response.text:
        assert "accommodation-card" in response.text
        assert 'href="/prestador/' in response.text
        assert (
            "accommodation-card-image" in response.text
            or "accommodation-card-placeholder" in response.text
        )


def test_accommodation_card_template_limits_visible_amenities():
    template = (
        __import__("pathlib").Path("app/templates/partials/alojamiento_card.html").read_text(
            encoding="utf-8"
        )
    )

    assert "card_chips[:3]" in template
    assert "accommodation-more-amenities" in template


def test_accommodation_filter_structure_and_advanced_count():
    response = TestClient(app).get("/alojamientos?tipo=casa&habitaciones=2&pileta=1&wifi=1")
    main_form = re.search(r'<form class="alojamientos-filters".*?</form>', response.text, re.S).group()
    primary_grid = main_form.split('<div class="accommodation-filter-toolbar">', 1)[0]
    more_filters = re.search(r'<details class="accommodation-more-filters".*?</details>', main_form, re.S).group()
    results_header = re.search(r'<header class="accommodation-results-header".*?</header>', response.text, re.S).group()

    assert all(f'name="{name}"' in primary_grid for name in ("tipo", "capacidad", "precio_max"))
    assert 'name="habitaciones"' not in primary_grid
    assert 'name="orden"' not in primary_grid
    assert 'name="habitaciones"' in more_filters
    assert "Más filtros (3)" in more_filters and " open" in more_filters
    assert 'class="accommodation-results-order"' in results_header
    assert 'name="orden"' in results_header
    for name in ("tipo", "habitaciones", "pileta", "wifi"):
        assert f'name="{name}"' in results_header


def test_complex_advanced_filters_render_rooms_count_and_preserve_order_inputs():
    response = TestClient(app).get("/alojamientos?tipo=complejo&habitaciones=2&pileta=1&wifi=1")
    more_filters = re.search(
        r'<details class="accommodation-more-filters".*?</details>', response.text, re.S
    ).group()
    order_form = re.search(
        r'<form class="accommodation-results-order".*?</form>', response.text, re.S
    ).group()

    assert "Más filtros (3)" in more_filters
    assert re.search(r'<details class="accommodation-more-filters"[^>]*\bopen\b', more_filters)
    assert "Habitaciones por unidad" in more_filters
    for label in ("1+ habitación", "2+ habitaciones", "3+ habitaciones"):
        assert label in more_filters
    for name, value in (
        ("tipo", "complejo"), ("habitaciones", "2"), ("pileta", "1"), ("wifi", "1")
    ):
        assert re.search(
            rf'<input type="hidden" name="{name}" value="{value}">', order_form
        )


def test_accommodation_filter_css_protects_responsive_layout():
    css = __import__("pathlib").Path("app/static/css/portal.css").read_text(encoding="utf-8")

    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css
    assert "@media (max-width: 679px)" in css
    assert ".alojamientos-filter-panel .alojamientos-filters { grid-template-columns: 1fr; }" in css
    assert ".accommodation-more-filters .filter-amenities { display: flex; flex-wrap: wrap" in css
    assert ".amenity-pill:has(input:checked)" not in css

    desktop_rule = re.search(r"\.accommodation-more-filters \{([^}]*)\}", css).group(1)
    mobile_block = re.search(r"@media \(max-width: 679px\) \{(.*?)\n\}", css, re.S).group(1)
    mobile_rule = re.search(
        r"\.accommodation-filter-toolbar \.accommodation-more-filters \{([^}]*)\}",
        mobile_block,
    ).group(1)

    assert "flex: 1 1 620px" in desktop_rule
    assert "flex: 0 0 auto" in mobile_rule
    assert "width: 100%" in mobile_rule
    assert not re.search(r"(?:^|;)\s*(?:height|min-height|max-height|position)\s*:", mobile_rule)
    assert "!important" not in mobile_rule
