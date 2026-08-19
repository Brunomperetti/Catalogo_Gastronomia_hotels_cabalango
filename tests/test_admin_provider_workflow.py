import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base
from app.models import CatalogLead, CatalogLeadEvent, Empresa, Producto, Review, SolicitudPrestador, Usuario


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


def assert_server_rendered_panel(html, panel_id, expected_text):
    match = re.search(rf'<section\s+id="panel-{re.escape(panel_id)}"[^>]*>', html)
    assert match, f"panel-{panel_id} was not rendered"
    assert "hidden" not in match.group(0)
    assert expected_text in html


def redirect_query(response):
    return parse_qs(urlparse(response.headers["location"]).query)


def edit_company(client, company, **values):
    data = {
        "empresa_slug_actual": company.slug,
        "nombre": company.nombre,
        "theme": company.theme or "default",
    }
    data.update(values)
    return client.post("/empresa/editar_panel", data=data, follow_redirects=False)


@pytest.mark.parametrize(("initial", "form_data", "expected"), [
    (True, {}, False),
    (False, {"activo": "1"}, True),
])
def test_edit_provider_applies_active_checkbox_state(admin_app, initial, form_data, expected):
    client, db, _ = admin_app
    company = add_company(db, activo=initial)

    response = edit_company(client, company, **form_data)

    db.refresh(company)
    assert response.status_code == 303
    assert company.activo is expected


@pytest.mark.parametrize(("initial", "form_data", "expected"), [
    (True, {}, False),
    (False, {"destacado": "1"}, True),
])
def test_edit_provider_applies_featured_checkbox_state(admin_app, initial, form_data, expected):
    client, db, _ = admin_app
    company = add_company(db, destacado=initial)

    response = edit_company(client, company, **form_data)

    db.refresh(company)
    assert response.status_code == 303
    assert company.destacado is expected


def test_deactivating_provider_preserves_company_media_and_intake(admin_app):
    client, db, storage = admin_app
    company = add_company(
        db,
        nombre="Nombre anterior",
        activo=True,
        logo_url="/media/empresas/demo/logo.png",
        banner_url="/media/empresas/demo/banner.jpg",
        galeria_urls=json.dumps(["/media/empresas/demo/galeria/photo.jpg"]),
    )
    media_file = storage / "empresas" / company.slug / "galeria" / "photo.jpg"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"provider media")
    request = SolicitudPrestador(
        external_id="request-unchanged",
        status="pendiente",
        business_name="Solicitud sin cambios",
        raw_payload="{}",
    )
    db.add(request)
    db.commit()
    company_id = company.id
    request_id = request.id

    response = edit_company(client, company, nombre="Nombre actualizado")

    db.expire_all()
    saved_company = db.get(Empresa, company_id)
    saved_request = db.get(SolicitudPrestador, request_id)
    assert response.status_code == 303
    assert saved_company is not None
    assert saved_company.nombre == "Nombre actualizado"
    assert saved_company.activo is False
    assert saved_company.logo_url == "/media/empresas/demo/logo.png"
    assert saved_company.banner_url == "/media/empresas/demo/banner.jpg"
    assert json.loads(saved_company.galeria_urls) == ["/media/empresas/demo/galeria/photo.jpg"]
    assert media_file.read_bytes() == b"provider media"
    assert saved_request is not None
    assert saved_request.status == "pendiente"
    assert saved_request.business_name == "Solicitud sin cambios"


@pytest.mark.parametrize(("admin_tab", "expected_tab"), [
    ("ficha", "ficha"),
    ("contacto", "contacto"),
    ("rubro", "rubro"),
])
def test_saving_provider_data_preserves_originating_tab(admin_app, admin_tab, expected_tab):
    client, db, _ = admin_app
    company = add_company(db)
    response = client.post("/empresa/editar_panel", data={
        "empresa_slug_actual": company.slug,
        "nombre": company.nombre,
        "theme": "default",
        "admin_tab": admin_tab,
    }, follow_redirects=False)
    assert redirect_query(response) | {"status": [str(response.status_code)]} == {
        "area": ["prestador"], "empresa": ["demo"], "tab": [expected_tab],
        "msg": ["Empresa actualizada correctamente."], "status": ["303"],
    }


def test_arbitrary_edit_tab_is_normalized_by_backend(admin_app):
    client, db, _ = admin_app
    company = add_company(db)
    response = client.post("/empresa/editar_panel", data={
        "empresa_slug_actual": company.slug, "nombre": company.nombre,
        "theme": "default", "admin_tab": "javascript:alert(1)",
    }, follow_redirects=False)
    assert redirect_query(response)["tab"] == ["prestadores"]


def test_gallery_upload_and_delete_redirect_to_photos(admin_app):
    client, db, _ = admin_app
    company = add_company(db)
    upload = client.post("/empresa/galeria", data={"empresa_slug": company.slug}, follow_redirects=False)
    assert redirect_query(upload)["area"] == ["prestador"]
    assert redirect_query(upload)["empresa"] == [company.slug]
    assert redirect_query(upload)["tab"] == ["fotos"]
    company.galeria_urls = json.dumps([gallery_url(company, "photo.jpg")])
    db.commit()
    deleted = delete_photo(client, company, 0)
    assert redirect_query(deleted)["tab"] == ["fotos"]


def test_switching_provider_from_photos_preserves_tab(admin_app):
    client, db, _ = admin_app
    add_company(db, slug="crisma")
    add_company(db, slug="farmacia")
    response = client.post("/empresa/activar_panel", data={
        "slug": "farmacia", "admin_tab": "fotos",
    }, follow_redirects=False)
    assert redirect_query(response) == {
        "area": ["prestador"], "empresa": ["farmacia"], "tab": ["fotos"],
    }


def test_portal_redirect_omits_provider_context():
    response = main.panel_redirect(empresa_slug="demo", area="portal", tab="cabalango", msg="Guardado")
    assert redirect_query(response) == {"area": ["portal"], "tab": ["cabalango"], "msg": ["Guardado"]}


def test_admin_gallery_uses_compact_grid():
    template = Path("app/templates/upload.html").read_text()
    stylesheet = Path("app/static/css/admin.css").read_text()
    assert 'class="admin-gallery-grid"' in template
    assert "repeat(auto-fill, minmax(125px, 150px))" in stylesheet
    assert "aspect-ratio: 4 / 3" in stylesheet


def test_provider_management_forms_are_closed_native_disclosures(admin_app):
    client, db, _ = admin_app
    add_company(db)

    response = client.get("/admin?area=prestador&empresa=demo&tab=prestadores")

    assert response.status_code == 200
    area_nav = re.search(
        r'<div class="admin-area-nav" aria-label="Área activa">(?P<links>.*?)</div>',
        response.text,
        re.DOTALL,
    )
    assert area_nav
    area_links = re.findall(r'<a\s+class="admin-area-link[^>]*href="([^"]+)"([^>]*)>(.*?)</a>', area_nav.group("links"), re.DOTALL)
    assert len(area_links) == 2
    assert [re.search(r'admin-area-link__title">([^<]+)', link[2]).group(1) for link in area_links] == [
        "Prestador activo", "Portal / destino",
    ]
    assert area_links[0][0] == "/admin?area=prestador&empresa=demo&tab=prestadores"
    assert area_links[1][0] == "/admin?area=portal&tab=cabalango"
    assert 'aria-current="page"' in area_links[0][1]
    assert 'aria-current="page"' not in area_links[1][1]
    provider_nav = re.search(
        r'<div class="admin-tabs admin-tabs--provider-sections" aria-label="Secciones del prestador">'
        r'(?P<links>.*?)</div>',
        response.text,
        re.DOTALL,
    )
    assert provider_nav
    assert re.findall(r'tab=([^"&]+)"', provider_nav.group("links")) == [
        "prestadores", "ficha", "fotos", "contacto", "rubro", "leads", "opiniones", "usuarios",
    ]
    assert 'id="tab-empresa" class="admin-tab is-active"' in provider_nav.group("links")
    disclosures = list(re.finditer(
        r'<details class="admin-disclosure"(?P<attributes>[^>]*)>\s*'
        r'<summary[^>]*>(?P<summary>.*?)</summary>',
        response.text,
        re.DOTALL,
    ))
    edit_disclosure = next(match for match in disclosures if "Editar prestador activo" in match.group("summary"))
    create_disclosure = next(match for match in disclosures if "Crear nuevo prestador / lugar" in match.group("summary"))
    assert "open" not in edit_disclosure.group("attributes").split()
    assert "open" not in create_disclosure.group("attributes").split()
    assert 'class="admin-disclosure__copy"' in edit_disclosure.group("summary")
    assert response.text.count("admin-disclosure-card") == 2

    edit_form = '<form action="/empresa/editar_panel" method="post" class="stack-form">'
    create_form = '<form action="/empresa/crear_panel" method="post"'
    assert edit_disclosure.end() < response.text.index(edit_form) < create_disclosure.start()
    assert create_disclosure.end() < response.text.index(create_form)
    assert response.text.count('action="/empresa/editar_panel"') == 1


@pytest.mark.parametrize(("tab", "panel_id", "expected_text"), [
    ("leads", "leads", "Tablero comercial"),
    ("usuarios", "usuarios", "Usuarios y accesos"),
    ("ficha", "ficha", "Ficha del prestador"),
    ("fotos", "fotos", "Fotos y video"),
    ("prestadores", "prestadores", "Editar prestador activo"),
    ("contacto", "contacto", "Contacto y ubicación"),
    ("rubro", "rubro", "Datos por rubro"),
    ("opiniones", "opiniones", "Moderación de opiniones"),
])
def test_provider_panels_are_complete_server_rendered_pages(admin_app, tab, panel_id, expected_text):
    client, db, _ = admin_app
    add_company(db)
    response = client.get(f"/admin?area=prestador&empresa=demo&tab={tab}")
    assert response.status_code == 200
    assert_server_rendered_panel(response.text, panel_id, expected_text)
    assert 'id="panel-cabalango"' not in response.text
    assert 'id="panel-configuracion"' not in response.text
    assert 'id="panel-tecnico"' not in response.text


def test_portal_configuration_requires_explicit_company_selection(admin_app):
    client, db, _ = admin_app
    add_company(db, nombre="Demo Company")
    response = client.get("/admin?area=portal&tab=configuracion")
    assert response.status_code == 200
    assert_server_rendered_panel(response.text, "configuracion", "Backup / Restore empresa completa")
    assert 'form action="/admin/empresa/exportar" method="get"' in response.text
    assert '<select name="empresa"' in response.text
    assert '<option value="demo">Demo Company</option>' in response.text
    assert "/admin/empresa/exportar?empresa=demo" not in response.text
    import_form = re.search(r'<form action="/admin/empresa/importar".*?</form>', response.text, re.DOTALL)
    assert import_form
    assert 'name="empresa_slug"' not in import_form.group(0)
    assert "No usa una empresa activa implícita" in response.text
    assert 'id="panel-prestadores"' not in response.text
    assert 'id="panel-leads"' not in response.text


def test_export_requires_company_instead_of_using_default(admin_app):
    client, db, _ = admin_app
    add_company(db)
    response = client.get("/admin/empresa/exportar")
    assert response.status_code == 400
    assert response.json() == {"error": "Seleccioná una empresa válida para exportar"}


def test_cabalango_portal_panel_is_server_rendered(admin_app):
    client, db, _ = admin_app
    add_company(db)
    response = client.get("/admin?area=portal&empresa=demo&tab=cabalango")
    assert response.status_code == 200
    assert_server_rendered_panel(response.text, "cabalango", "Descubrí Cabalango")
    assert 'id="panel-opiniones"' not in response.text


def test_both_technical_sections_are_visible_without_javascript(admin_app):
    client, db, _ = admin_app
    add_company(db)
    response = client.get("/admin?area=portal&empresa=demo&tab=tecnico")
    assert response.status_code == 200
    assert_server_rendered_panel(response.text, "tecnico", "Compatibilidad catálogo viejo")
    assert_server_rendered_panel(response.text, "tecnico-extra", "Zona peligrosa")
    assert response.text.count('<select name="empresa_slug"') == 3
    assert "Esta acción afecta únicamente al prestador seleccionado abajo" in response.text
    assert 'action="/delete_all_products"' in response.text
    assert 'name="empresa_slug" value="demo"' not in response.text
    assert 'id="panel-ficha"' not in response.text


def test_portal_navigation_links_never_carry_company(admin_app):
    client, db, _ = admin_app
    add_company(db)
    response = client.get("/admin?area=portal&empresa=demo&tab=configuracion")
    assert '/admin?area=portal&empresa=' not in response.text
    assert '/admin?area=portal&tab=cabalango' in response.text
    assert '/admin?area=portal&tab=tecnico' in response.text


def test_admin_template_has_no_legacy_client_tab_system():
    template = Path("app/templates/upload.html").read_text()
    for legacy_marker in ("data-tab-target", "data-tab-panel", "setupAdminTabs", "activateTab", 'role="tab"', 'role="tabpanel"'):
        assert legacy_marker not in template


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


def test_admin_uses_shopping_group_label_without_changing_value(admin_app):
    client, db, _ = admin_app
    company = add_company(db, slug="almacen", theme="servicios", subtipo="Almacén", subgrupo="compras")
    response = client.get(f"/admin?empresa={company.slug}&tab=rubro")
    assert response.status_code == 200
    assert '<option value="compras" selected>Almacenes y kioscos</option>' in response.text


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


def test_admin_permanently_deletes_provider_and_owned_relations(admin_app):
    client, db, storage = admin_app
    company = add_company(db, nombre="Prueba errónea", slug="prueba-erronea", activo=True)
    other = add_company(db, nombre="Prestador real", slug="prestador-real", activo=True)
    product = Producto(empresa_id=company.id, codigo="TEST", descripcion="Producto", precio=1)
    review = Review(prestador_id=company.id, nombre="Persona", rating=5, comentario="Opinión", estado="aprobada")
    lead = CatalogLead(empresa_catalogo_id=company.id, nombre="Lead", empresa="Prueba", email="lead@example.com")
    db.add_all([product, review, lead])
    db.flush()
    event = CatalogLeadEvent(lead_id=lead.id, empresa_catalogo_id=company.id, event_type="view")
    intake = SolicitudPrestador(
        external_id="intake-auditable", status="procesada", business_name=company.nombre,
        raw_payload="{}", converted_entity_type="empresa", converted_entity_id=company.id,
    )
    db.add_all([event, intake])
    db.commit()
    company_id, other_id, intake_id = company.id, other.id, intake.id
    media_file = storage / "empresas" / company.slug / "logo.png"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"retained media")

    response = client.post(f"/admin/prestadores/{company_id}/eliminar", follow_redirects=False)

    db.expire_all()
    assert response.status_code == 303
    assert db.get(Empresa, company_id) is None
    assert db.get(Empresa, other_id) is not None
    assert db.query(Producto).filter_by(empresa_id=company_id).count() == 0
    assert db.query(Review).filter_by(prestador_id=company_id).count() == 0
    assert db.query(CatalogLead).filter_by(empresa_catalogo_id=company_id).count() == 0
    assert db.query(CatalogLeadEvent).filter_by(empresa_catalogo_id=company_id).count() == 0
    assert db.get(SolicitudPrestador, intake_id) is not None
    assert db.get(SolicitudPrestador, intake_id).converted_entity_id == company_id
    assert media_file.read_bytes() == b"retained media"
    assert client.get("/prestador/prueba-erronea").status_code == 404


def test_provider_permanent_delete_requires_admin_and_post(admin_app):
    _, db, _ = admin_app
    company = add_company(db, slug="protected")
    company_id = company.id
    anonymous = TestClient(main.app)

    get_response = anonymous.get(f"/admin/prestadores/{company_id}/eliminar", follow_redirects=False)
    post_response = anonymous.post(f"/admin/prestadores/{company_id}/eliminar", follow_redirects=False)

    assert get_response.status_code == 405
    assert post_response.status_code == 303
    assert post_response.headers["location"].startswith("/login?")
    db.expire_all()
    assert db.get(Empresa, company_id) is not None


def test_provider_permanent_delete_missing_id_is_404(admin_app):
    client, _, _ = admin_app
    assert client.post("/admin/prestadores/999999/eliminar").status_code == 404


def test_provider_edit_has_strong_confirmation_but_empty_admin_does_not(admin_app):
    client, db, _ = admin_app
    company = add_company(db, nombre="Nombre dinámico", slug="nombre-dinamico")
    edit_html = client.get(f"/admin?area=prestador&empresa={company.slug}&tab=prestadores").text
    assert "Zona de peligro" in edit_html
    assert "Eliminar definitivamente" in edit_html
    assert "Nombre dinámico" in edit_html
    db.delete(company)
    db.commit()
    empty_html = client.get("/admin?area=prestador&tab=prestadores").text
    assert "admin-danger-zone" not in empty_html
