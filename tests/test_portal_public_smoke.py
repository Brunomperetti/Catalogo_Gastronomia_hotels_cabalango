import re

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
    ("/servicios", "Servicios útiles", "Servicios útiles en Cabalango"),
    ("/actividades", "Actividades", "Actividades y comunidad en Cabalango"),
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
    assert response.text.count("Leer más") == 4
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
