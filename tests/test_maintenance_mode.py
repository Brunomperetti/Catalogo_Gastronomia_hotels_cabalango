import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app, run_startup_db_maintenance
from app.models import Usuario


@pytest.fixture(scope="module", autouse=True)
def prepare_portal_database():
    run_startup_db_maintenance()


@pytest.fixture(autouse=True)
def clean_maintenance_mode(monkeypatch):
    monkeypatch.delenv("MAINTENANCE_MODE", raising=False)


@pytest.fixture()
def client():
    return TestClient(app)


def test_home_is_online_when_variable_is_missing(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Descubrí Cabalango" in response.text


def test_home_is_online_when_maintenance_is_false(client, monkeypatch):
    monkeypatch.setenv("MAINTENANCE_MODE", "false")

    assert client.get("/").status_code == 200


@pytest.mark.parametrize("enabled_value", ["1", "true", "TRUE", "yes", "On"])
def test_truthy_values_enable_maintenance(client, monkeypatch, enabled_value):
    monkeypatch.setenv("MAINTENANCE_MODE", enabled_value)

    response = client.get("/")

    assert response.status_code == 503
    assert "Guía Turística de Cabalango" in response.text
    assert "Estamos preparando la versión final." in response.text
    assert (
        "¿Tenés un comercio, alojamiento, emprendimiento gastronómico, servicio, "
        "actividad o productos artesanales en Cabalango?"
    ) in response.text
    assert "Completá el formulario y sumate a la Guía Turística de Cabalango." in response.text
    assert "Muy pronto en" in response.text
    assert "www.cabalango.com.ar" in response.text
    assert response.headers["Retry-After"] == "3600"
    assert '<meta name="robots" content="noindex, nofollow">' in response.text


@pytest.mark.parametrize("path", ["/gastronomia", "/alojamientos"])
def test_public_sections_are_unavailable_during_maintenance(client, monkeypatch, path):
    monkeypatch.setenv("MAINTENANCE_MODE", "true")

    assert client.get(path).status_code == 503


def test_login_is_not_replaced_by_maintenance(client, monkeypatch):
    monkeypatch.setenv("MAINTENANCE_MODE", "true")

    response = client.get("/login")

    assert response.status_code == 200
    assert "Estamos preparando la versión final." not in response.text


def test_unauthenticated_admin_keeps_redirecting_to_login(client, monkeypatch):
    monkeypatch.setenv("MAINTENANCE_MODE", "true")

    response = client.get("/admin", follow_redirects=False)

    assert response.status_code in {302, 303, 307}
    assert response.headers["location"].startswith("/login")


def test_authenticated_admin_remains_available(client, monkeypatch):
    monkeypatch.setenv("MAINTENANCE_MODE", "true")
    username = "maintenance-test-admin"
    db = main.SessionLocal()
    db.query(Usuario).filter(Usuario.username == username).delete()
    db.add(Usuario(
        username=username,
        password_hash=main.hash_password("maintenance-test-password"),
        rol="admin",
        activo=True,
    ))
    db.commit()
    try:
        login = client.post(
            "/login",
            data={"username": username, "password": "maintenance-test-password", "next": "/admin"},
            follow_redirects=False,
        )
        response = client.get("/admin")

        assert login.status_code == 303
        assert response.status_code == 200
        assert "Estamos preparando la versión final." not in response.text
    finally:
        db.query(Usuario).filter(Usuario.username == username).delete()
        db.commit()
        db.close()


def test_static_asset_remains_available(client, monkeypatch):
    monkeypatch.setenv("MAINTENANCE_MODE", "true")

    response = client.get("/static/images/Logo_Cabalango.png")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")


def test_internal_api_is_not_intercepted(client, monkeypatch):
    monkeypatch.setenv("MAINTENANCE_MODE", "true")

    response = client.post("/api/internal/intake/google-form", json={})

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert "Retry-After" not in response.headers


@pytest.mark.parametrize("path", ["/healthz", "/_build"])
def test_operational_endpoints_remain_available(client, monkeypatch, path):
    monkeypatch.setenv("MAINTENANCE_MODE", "true")

    assert client.get(path).status_code == 200
