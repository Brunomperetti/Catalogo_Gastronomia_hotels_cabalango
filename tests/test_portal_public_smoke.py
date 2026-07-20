import pytest

pytest.importorskip("httpx", reason="FastAPI TestClient requires httpx")
from fastapi.testclient import TestClient

from app.main import app


def test_portal_home_smoke():
    with TestClient(app) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 200
    assert "Gastronomía" in response.text
    assert "Alojamientos" in response.text
    assert "Servicios útiles" in response.text
    assert "Actividades y comunidad" in response.text
    assert "Logo_Cabalango.png" in response.text


def test_portal_gastronomia_smoke():
    with TestClient(app) as client:
        response = client.get("/gastronomia")

    assert response.status_code == 200
    assert "Gastronomía en Cabalango" in response.text
    assert "Logo_Cabalango.png" in response.text


def test_portal_alojamientos_smoke():
    with TestClient(app) as client:
        response = client.get("/alojamientos")

    assert response.status_code == 200
    assert "Alojamientos en Cabalango" in response.text


def test_portal_servicios_smoke():
    with TestClient(app) as client:
        response = client.get("/servicios")

    assert response.status_code == 200
    assert "Servicios útiles en Cabalango" in response.text


def test_portal_actividades_smoke():
    with TestClient(app) as client:
        response = client.get("/actividades")

    assert response.status_code == 200
    assert "Actividades y comunidad en Cabalango" in response.text
