import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base
from app.models import Empresa, Usuario


@pytest.fixture()
def admin_app(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = Session()
    admin = Usuario(username="admin-test", password_hash=main.hash_password("secret"), rol="admin", activo=True)
    db.add(admin)
    db.commit()
    storage = tmp_path / "storage"
    monkeypatch.setattr(main, "STORAGE_DIR", storage)
    monkeypatch.setattr(main, "MEDIA_BASE_DIR", storage / "empresas")
    monkeypatch.setattr(main, "ensure_empresa_media_columns", lambda: None)
    monkeypatch.setattr(main, "ensure_destino_media_table", lambda: None)
    monkeypatch.setattr(main, "ensure_destino_contenido_table", lambda: None)

    def override_db():
        yield db

    main.app.dependency_overrides[main.get_db] = override_db
    client = TestClient(main.app)
    login = client.post("/login", data={"username": "admin-test", "password": "secret", "next": "/admin"})
    assert login.status_code == 200
    try:
        yield client, db, storage
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
        db.close()
        engine.dispose()


def add_company(db, **values):
    company = Empresa(nombre=values.pop("nombre", "Demo"), slug=values.pop("slug", "demo"), **values)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def gallery_url(company, filename):
    return f"/media/empresas/{company.slug}/galeria/{filename}"


def delete_photo(client, company, index):
    return client.post(f"/empresa/{company.id}/galeria/eliminar", data={"foto_indice": index}, follow_redirects=False)


def test_delete_gallery_photo_keeps_remaining_and_removes_managed_file(admin_app):
    client, db, storage = admin_app
    company = add_company(db)
    urls = [gallery_url(company, "one.jpg"), gallery_url(company, "two.jpg")]
    company.galeria_urls = json.dumps(urls)
    target = storage / "empresas" / company.slug / "galeria" / "one.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"photo")
    db.commit()

    response = delete_photo(client, company, 0)
    db.refresh(company)
    assert response.status_code == 303
    assert json.loads(company.galeria_urls) == [urls[1]]
    assert not target.exists()


def test_delete_last_gallery_photo_leaves_empty_list(admin_app):
    client, db, _ = admin_app
    company = add_company(db, slug="last")
    company.galeria_urls = json.dumps([gallery_url(company, "last.webp")])
    db.commit()
    assert delete_photo(client, company, 0).status_code == 303
    db.refresh(company)
    assert json.loads(company.galeria_urls) == []


def test_delete_missing_file_still_cleans_database_reference(admin_app):
    client, db, _ = admin_app
    company = add_company(db, slug="missing")
    company.galeria_urls = json.dumps([gallery_url(company, "gone.jpg")])
    db.commit()
    assert delete_photo(client, company, 0).status_code == 303
    db.refresh(company)
    assert json.loads(company.galeria_urls) == []


def test_gallery_delete_rejects_index_not_owned_by_company(admin_app):
    client, db, _ = admin_app
    owner = add_company(db, slug="owner")
    other = add_company(db, slug="other")
    owner.galeria_urls = json.dumps([gallery_url(owner, "owner.jpg")])
    other.galeria_urls = json.dumps([gallery_url(other, "other.jpg")])
    db.commit()
    response = delete_photo(client, owner, 1)
    db.refresh(owner)
    assert response.status_code == 400
    assert json.loads(owner.galeria_urls) == [gallery_url(owner, "owner.jpg")]


def test_malicious_gallery_reference_cannot_delete_outside_storage(admin_app, tmp_path):
    client, db, _ = admin_app
    company = add_company(db, slug="unsafe")
    outside = tmp_path / "do-not-delete.jpg"
    outside.write_bytes(b"safe")
    company.galeria_urls = json.dumps([f"/media/empresas/{company.slug}/galeria/../../../../do-not-delete.jpg"])
    db.commit()
    assert delete_photo(client, company, 0).status_code == 303
    db.refresh(company)
    assert json.loads(company.galeria_urls) == []
    assert outside.read_bytes() == b"safe"


def test_historical_pharmacy_is_inferred_in_admin_without_rewrite(admin_app):
    client, db, _ = admin_app
    company = add_company(db, slug="farmacia", theme="servicios", subtipo="Farmacia", subgrupo=None, activo=True)
    response = client.get(f"/admin?empresa={company.slug}&tab=rubro")
    assert response.status_code == 200
    assert '<option value="salud" selected>Salud y bienestar</option>' in response.text
    assert "Salud y bienestar · Farmacia" in response.text
    db.refresh(company)
    assert company.subgrupo is None


@pytest.mark.parametrize(("subtype", "group"), [
    ("Farmacia", "salud"),
    ("Remis", "transporte"),
    ("Playa de estacionamiento", "estacionamiento"),
    ("Almacén", "compras"),
    ("Lavadero de ropa", "otros"),
])
def test_saving_known_service_subtype_normalizes_group(admin_app, subtype, group):
    client, db, _ = admin_app
    company = add_company(db, slug=group + subtype.lower().replace(" ", "-")[:8], theme="servicios", subtipo="Otro")
    response = client.post("/empresa/editar_panel", data={
        "empresa_slug_actual": company.slug,
        "nombre": company.nombre,
        "theme": "servicios",
        "subgrupo": "compras" if group != "compras" else "otros",
        "subtipo": subtype,
    }, follow_redirects=False)
    db.refresh(company)
    assert response.status_code == 303
    assert company.subgrupo == group
    assert company.subtipo == subtype


def test_active_provider_summary_never_renders_none(admin_app):
    client, db, _ = admin_app
    company = add_company(db, slug="empty-summary", theme="alojamiento", subtipo=None, subgrupo=None, activo=False)
    response = client.get(f"/admin?empresa={company.slug}")
    assert response.status_code == 200
    assert "Prestador activo" in response.text
    assert "Alojamientos" in response.text
    assert "Inactivo" in response.text
    assert "None" not in response.text

def test_public_routes_remain_available(admin_app):
    client, db, _ = admin_app
    company = add_company(db, slug="public-provider", theme="servicios", subtipo="Almacén", subgrupo="compras", activo=True)
    for path in ["/", "/servicios", "/gastronomia", "/alojamientos", "/actividades", f"/prestador/{company.slug}"]:
        response = client.get(path)
        assert response.status_code == 200, path
