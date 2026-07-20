import re

import pytest

pytest.importorskip("httpx", reason="FastAPI TestClient requires httpx")
from fastapi.testclient import TestClient

from app.main import app


PUBLIC_SECTIONS = [
    ("/", "Inicio", "Descubrí Cabalango"),
    ("/gastronomia", "Gastronomía", "Gastronomía en Cabalango"),
    ("/alojamientos", "Alojamientos", "Alojamientos en Cabalango"),
    ("/servicios", "Servicios útiles", "Servicios útiles en Cabalango"),
    ("/actividades", "Actividades", "Actividades y comunidad en Cabalango"),
]


def _nav_markup(html: str) -> str:
    match = re.search(r'<nav class="portal-topnav"[^>]*>(.*?)</nav>', html, re.S)
    assert match, "public navigation should render"
    return match.group(1)


def _active_nav_labels(html: str) -> list[str]:
    nav = _nav_markup(html)
    return re.findall(r'<a class="[^"]*is-active[^"]*"[^>]*>([^<]+)</a>', nav)


def test_portal_home_smoke():
    with TestClient(app) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 200
    assert "Descubrí Cabalango" in response.text
    assert "Historia" in response.text
    assert "Ubicación" in response.text
    assert "Naturaleza" in response.text
    assert "Vida local" in response.text
    assert "Logo_Cabalango.png" in response.text


def test_descubri_cabalango_redirects_to_home():
    with TestClient(app) as client:
        response = client.get("/descubri-cabalango", follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == "/"


def test_public_navigation_has_no_independent_descubri_link():
    with TestClient(app) as client:
        response = client.get("/")

    nav = _nav_markup(response.text)
    assert 'href="/descubri-cabalango"' not in nav
    assert ">Descubrí Cabalango</a>" not in nav


@pytest.mark.parametrize(("path", "active_label", "expected_text"), PUBLIC_SECTIONS)
def test_public_sections_smoke_and_active_navigation(path, active_label, expected_text):
    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 200
    assert expected_text in response.text
    assert "Logo_Cabalango.png" in response.text
    assert _active_nav_labels(response.text) == [active_label]
