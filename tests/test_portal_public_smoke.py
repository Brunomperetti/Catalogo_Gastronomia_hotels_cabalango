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
        "Tip de viaje",
    ]:
        assert visitor_copy in response.text
    for href in [
        "/actividades",
        "/alojamientos",
        "/gastronomia",
        "/servicios?grupo=compras",
        "#como-llegar",
    ]:
        assert f'href="{href}"' in response.text
    assert response.text.count("destination-story-more") == 3
    assert 'id="como-llegar"' in response.text
    assert "?v=20260812-home-editorial-1" in response.text
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
    assert "Fotos destacadas" in response.text
    assert "Ver foto destacada" in response.text
    assert "Todas las fotos" not in response.text
    assert "Organizá tu visita a tu ritmo" in response.text
    assert 'href="/alojamientos">Alojamientos' in response.text
    assert 'href="/gastronomia">Gastronomía' in response.text
    assert 'href="/actividades">Qué hacer' in response.text


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
