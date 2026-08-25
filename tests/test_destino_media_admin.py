from io import BytesIO
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base
from app.models import DestinoMedia, Empresa, Usuario


@pytest.fixture()
def destino_admin(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = Session()
    db.add_all([
        Usuario(username="admin-media", password_hash=main.hash_password("secret"), rol="admin", activo=True),
        Empresa(nombre="Demo", slug="demo", activo=True),
    ])
    db.commit()
    monkeypatch.setattr(main, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(main, "ensure_empresa_media_columns", lambda: None)
    monkeypatch.setattr(main, "ensure_destino_media_table", lambda: None)
    monkeypatch.setattr(main, "ensure_destino_contenido_table", lambda: None)

    def override_db():
        yield db

    main.app.dependency_overrides[main.get_db] = override_db
    client = TestClient(main.app)
    assert client.post("/login", data={"username": "admin-media", "password": "secret"}).status_code == 200
    try:
        yield client, db, tmp_path
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
        db.close()
        engine.dispose()


def add_media(db, **values):
    defaults = dict(tipo="foto", categoria="rio_naturaleza", uso_portal="general", titulo="Postal", descripcion="Original", image_path="/media/destino/fotos/original.jpg", orden=1, visible=True, destacado=False)
    defaults.update(values)
    item = DestinoMedia(**defaults)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def edit(client, item_id, **changes):
    data = {"titulo": "Postal editada", "categoria": "paisajes", "uso_portal": "general", "descripcion": "Descripción renovada", "orden": "0", "visible": "1", "destacado": "1", "video_url": ""}
    data.update(changes)
    data = {key: value for key, value in data.items() if value is not None}
    return client.post(f"/admin/cabalango/media/{item_id}/editar", data=data, follow_redirects=False)


def home_section(html, class_name):
    return html.split(f'class="{class_name}', 1)[1].split("</section>", 1)[0]


def test_admin_renders_working_unique_edit_dialog_and_order_actions(destino_admin):
    client, db, _ = destino_admin
    item = add_media(db)
    response = client.get("/admin?area=portal&tab=cabalango")
    html = response.text
    assert response.status_code == 200
    assert "/static/css/admin.css?v=20260824-home-media-admin-2" in html
    for expected_text in (
        "Descubrí Cabalango",
        "Texto editorial del destino",
        "Fotos y videos del destino",
        "Biblioteca de fotos y videos",
        "Guardar texto editorial",
        "Guardar contenido de Cabalango",
    ):
        assert expected_text in html
    assert f'id="edit-destino-media-{item.id}"' in html
    assert f"/admin/cabalango/media/{item.id}/editar" in html
    assert "Editar</button>" in html
    assert "Editar</button><button" not in html
    assert "↑ Subir" in html and "↓ Bajar" in html
    assert "Ocultar" in html
    assert "Ubicación opcional" in html
    assert "Sin ubicación fija" in html


def test_home_journeys_use_explicit_visible_assignments_and_keep_ctas(destino_admin, monkeypatch):
    client, db, _ = destino_admin
    monkeypatch.setattr(main, "get_cabalango_weather", lambda: {"available": False})
    rio = add_media(db, uso_portal="journey_rio", titulo="Mañana de río", descripcion="Texto editado", image_path="/media/rio-slot.jpg")
    add_media(db, uso_portal="journey_escapada", titulo="Escapada personalizada", descripcion="Dos noches tranquilas", image_path="/media/escapada-slot.jpg")
    add_media(db, uso_portal="journey_familia", titulo="Familia en el monte", descripcion="Un plan compartido", image_path="/media/familia-slot.jpg")

    html = client.get("/").text

    for expected in ("Mañana de río", "Texto editado", "Escapada personalizada", "Dos noches tranquilas", "Familia en el monte", "Un plan compartido"):
        assert expected in html
    assert '/media/rio-slot.jpg' in html and '/media/escapada-slot.jpg' in html and '/media/familia-slot.jpg' in html
    assert '<a href="/actividades">Ver qué hacer' in html
    assert '<a href="/alojamientos">Ver alojamientos' in html
    assert '<a href="/actividades">Explorar actividades' in html
    assert html.count('class="destination-journey-card') == 3
    assert 'class="destination-journey-card is-featured"' in html
    assert rio.visible is True


def test_home_generic_placements_only_use_general_photos(destino_admin, monkeypatch):
    client, db, _ = destino_admin
    monkeypatch.setattr(main, "get_cabalango_weather", lambda: {"available": False})
    add_media(db, titulo="General secundaria", image_path="/media/general-about.jpg", orden=2)
    add_media(db, titulo="General destacada", image_path="/media/general-hero.jpg", orden=1, destacado=True)
    add_media(
        db,
        uso_portal="journey_escapada",
        titulo="Escapada reservada",
        descripcion="Solo para quedarse",
        image_path="/media/reserved-escapada.jpg",
        orden=0,
        destacado=True,
    )

    html = client.get("/").text
    hero = home_section(html, "destination-editorial-hero")
    about = home_section(html, "destination-section destination-about")
    journeys = home_section(html, "destination-journeys")

    assert "/media/general-hero.jpg" in hero
    assert "/media/reserved-escapada.jpg" not in hero
    assert "/media/general-about.jpg" in about
    assert "/media/reserved-escapada.jpg" not in about
    assert "/media/reserved-escapada.jpg" in journeys
    assert "Escapada reservada" in journeys


def test_home_falls_back_to_visible_photos_when_none_are_general(destino_admin, monkeypatch):
    client, db, _ = destino_admin
    monkeypatch.setattr(main, "get_cabalango_weather", lambda: {"available": False})
    add_media(db, uso_portal="journey_escapada", titulo="Única postal", image_path="/media/only-journey.jpg")

    response = client.get("/")
    hero = home_section(response.text, "destination-editorial-hero")
    about = home_section(response.text, "destination-section destination-about")

    assert response.status_code == 200
    assert "/media/only-journey.jpg" in hero
    assert "/media/only-journey.jpg" not in about


def test_assigning_general_photo_to_journey_removes_it_from_generic_home_pool(destino_admin, monkeypatch):
    client, db, _ = destino_admin
    monkeypatch.setattr(main, "get_cabalango_weather", lambda: {"available": False})
    retained = add_media(db, titulo="General disponible", image_path="/media/still-general.jpg", orden=2)
    assigned = add_media(db, titulo="Antes general", image_path="/media/assigned.jpg", orden=1, destacado=True)

    response = edit(client, assigned.id, uso_portal="journey_escapada", titulo="Ahora reservada")
    db.refresh(retained)
    db.refresh(assigned)
    html = client.get("/").text
    hero = home_section(html, "destination-editorial-hero")
    about = home_section(html, "destination-section destination-about")
    journeys = home_section(html, "destination-journeys")

    assert response.status_code == 303
    assert assigned.uso_portal == "journey_escapada"
    assert retained.uso_portal == "general"
    assert "/media/assigned.jpg" not in hero
    assert "/media/assigned.jpg" not in about
    assert "/media/still-general.jpg" in hero
    assert "/media/still-general.jpg" in about
    assert "/media/assigned.jpg" in journeys


def test_home_journeys_fallback_without_assignments_or_for_hidden_item(destino_admin, monkeypatch):
    client, db, _ = destino_admin
    monkeypatch.setattr(main, "get_cabalango_weather", lambda: {"available": False})
    add_media(db, uso_portal="journey_rio", titulo="No publicar", descripcion="Texto oculto", visible=False, image_path="/media/hidden.jpg")

    html = client.get("/").text

    for expected in (
        "Un día junto al río",
        "Balnearios, sombra y caminatas para disfrutar sin apuro.",
        "Quedarse un poco más",
        "Alojamiento, sabores locales y tranquilidad para desconectar.",
        "Tiempo para compartir",
        "Espacios abiertos y naturaleza para disfrutar en familia.",
    ):
        assert expected in html
    assert "No publicar" not in html
    assert "Texto oculto" not in html
    assert "/media/hidden.jpg" not in html


def test_admin_edit_assignment_updates_home_and_releases_previous_slot(destino_admin, monkeypatch):
    client, db, _ = destino_admin
    monkeypatch.setattr(main, "get_cabalango_weather", lambda: {"available": False})
    previous = add_media(db, uso_portal="journey_rio", titulo="Anterior")
    replacement = add_media(db, titulo="Biblioteca", image_path="/media/replacement.jpg")

    response = edit(client, replacement.id, uso_portal="journey_rio", titulo="Mañana de río", descripcion="Una experiencia tranquila junto al agua", destacado=None)
    db.refresh(previous)
    db.refresh(replacement)
    html = client.get("/").text

    assert response.status_code == 303
    assert previous.uso_portal == "general"
    assert replacement.uso_portal == "journey_rio"
    assert "Mañana de río" in html
    assert "Una experiencia tranquila junto al agua" in html
    assert "/media/replacement.jpg" in html
    admin_html = client.get("/admin?area=portal&tab=cabalango").text
    assert "Plan río" in admin_html
    assert "USO HOME:" not in admin_html


def test_create_video_forces_general_without_displacing_home_photo(destino_admin, monkeypatch):
    client, db, _ = destino_admin
    monkeypatch.setattr(main, "get_cabalango_weather", lambda: {"available": False})
    rio = add_media(db, uso_portal="journey_rio", titulo="Foto del río", image_path="/media/rio-correcta.jpg")

    response = client.post(
        "/admin/cabalango/media",
        data={
            "tipo": "video",
            "categoria": "videos",
            "uso_portal": "journey_rio",
            "titulo": "Video del río",
            "video_url": "https://example.com/video",
            "visible": "1",
        },
        follow_redirects=False,
    )
    video = db.query(DestinoMedia).filter(DestinoMedia.tipo == "video").one()
    db.refresh(rio)
    html = client.get("/").text

    assert response.status_code == 303
    assert video.uso_portal == "general"
    assert rio.uso_portal == "journey_rio"
    assert "Foto del río" in html
    assert "/media/rio-correcta.jpg" in html


def test_edit_video_forces_general_without_displacing_home_photo(destino_admin):
    client, db, _ = destino_admin
    escapada = add_media(db, uso_portal="journey_escapada", titulo="Foto escapada")
    video = add_media(db, tipo="video", categoria="videos", image_path=None, video_url="https://example.com/original")

    response = edit(
        client,
        video.id,
        categoria="videos",
        uso_portal="journey_escapada",
        video_url="https://example.com/editado",
    )
    db.refresh(video)
    db.refresh(escapada)

    assert response.status_code == 303
    assert video.uso_portal == "general"
    assert escapada.uso_portal == "journey_escapada"
    admin_html = client.get("/admin?area=portal&tab=cabalango").text
    assert "General. Las posiciones de Inicio utilizan fotografías." in admin_html


def test_admin_renders_destination_panel_without_active_provider(destino_admin):
    client, db, _ = destino_admin
    db.query(Empresa).delete()
    db.commit()

    response = client.get("/admin?area=portal&tab=cabalango")

    assert response.status_code == 200
    assert "Texto editorial del destino" in response.text
    assert "Fotos y videos del destino" in response.text


def test_edit_updates_fields_states_and_preserves_image(destino_admin):
    client, db, _ = destino_admin
    item = add_media(db, visible=True, destacado=False)
    old_path = item.image_path
    response = edit(client, item.id, visible=None)
    db.refresh(item)
    assert response.status_code == 303
    assert (item.titulo, item.descripcion, item.categoria, item.orden) == ("Postal editada", "Descripción renovada", "paisajes", 0)
    assert item.visible is False
    assert item.destacado is True
    assert item.image_path == old_path


def test_edit_can_clear_featured_and_enable_visible(destino_admin):
    client, db, _ = destino_admin
    item = add_media(db, visible=False, destacado=True)
    response = edit(client, item.id, destacado=None, visible="1")
    db.refresh(item)
    assert response.status_code == 303
    assert item.visible is True
    assert item.destacado is False


def test_edit_replaces_image_without_deleting_previous_file(destino_admin):
    client, db, tmp_path = destino_admin
    item = add_media(db)
    previous = tmp_path / "storage" / "destino" / "fotos" / "original.jpg"
    previous.parent.mkdir(parents=True)
    previous.write_bytes(b"old")
    response = client.post(
        f"/admin/cabalango/media/{item.id}/editar",
        data={"titulo": "Nueva", "categoria": "paisajes", "descripcion": "Texto", "orden": "2", "visible": "1", "video_url": ""},
        files={"nueva_imagen": ("replacement.jpg", BytesIO(b"new-image"), "image/jpeg")},
        follow_redirects=False,
    )
    db.refresh(item)
    assert response.status_code == 303
    assert item.image_path != "/media/destino/fotos/original.jpg"
    assert item.image_path.endswith(".jpg")
    assert previous.read_bytes() == b"old"


def test_edit_missing_id_is_404(destino_admin):
    client, _, _ = destino_admin
    assert edit(client, 99999).status_code == 404


def test_edit_commit_failure_rolls_back(destino_admin, monkeypatch):
    client, db, _ = destino_admin
    item = add_media(db)
    original_commit = db.commit
    rolled_back = False

    def fail_commit():
        raise RuntimeError("database unavailable")

    original_rollback = db.rollback
    def record_rollback():
        nonlocal rolled_back
        rolled_back = True
        original_rollback()

    monkeypatch.setattr(db, "commit", fail_commit)
    monkeypatch.setattr(db, "rollback", record_rollback)
    with pytest.raises(RuntimeError, match="database unavailable"):
        edit(client, item.id)
    assert rolled_back
    monkeypatch.setattr(db, "commit", original_commit)
    db.refresh(item)
    assert item.titulo == "Postal"


def test_existing_toggle_still_works(destino_admin):
    client, db, _ = destino_admin
    item = add_media(db, visible=True)
    response = client.post(f"/admin/cabalango/media/{item.id}/toggle", follow_redirects=False)
    db.refresh(item)
    assert response.status_code == 303
    assert item.visible is False


def test_move_up_and_down_swaps_administrative_order(destino_admin):
    client, db, _ = destino_admin
    first = add_media(db, titulo="First", orden=10)
    second = add_media(db, titulo="Second", orden=20)
    third = add_media(db, titulo="Third", orden=30)
    assert client.post(f"/admin/cabalango/media/{second.id}/mover", data={"direction": "up"}, follow_redirects=False).status_code == 303
    db.refresh(first); db.refresh(second)
    assert (first.orden, second.orden) == (20, 10)
    assert client.post(f"/admin/cabalango/media/{second.id}/mover", data={"direction": "down"}, follow_redirects=False).status_code == 303
    db.refresh(first); db.refresh(second); db.refresh(third)
    assert (first.orden, second.orden, third.orden) == (10, 20, 30)


def test_move_at_first_or_last_is_safe(destino_admin):
    client, db, _ = destino_admin
    first = add_media(db, orden=0)
    last = add_media(db, orden=1)
    up = client.post(f"/admin/cabalango/media/{first.id}/mover", data={"direction": "up"}, follow_redirects=False)
    down = client.post(f"/admin/cabalango/media/{last.id}/mover", data={"direction": "down"}, follow_redirects=False)
    db.refresh(first); db.refresh(last)
    assert up.status_code == down.status_code == 303
    assert (first.orden, last.orden) == (0, 1)


def test_move_duplicate_orders_is_deterministic(destino_admin):
    client, db, _ = destino_admin
    first = add_media(db, orden=4)
    second = add_media(db, orden=4)
    response = client.post(f"/admin/cabalango/media/{second.id}/mover", data={"direction": "up"}, follow_redirects=False)
    db.refresh(first); db.refresh(second)
    assert response.status_code == 303
    assert second.orden == 0 and first.orden == 1


def test_home_hero_uses_explicit_photos_in_order_and_excludes_other_slots(destino_admin, monkeypatch):
    client, db, _ = destino_admin
    monkeypatch.setattr(main, "get_cabalango_weather", lambda: {"available": False})
    third = add_media(db, uso_portal="home_hero", titulo="Hero tres", image_path="/media/hero-3.jpg", orden=30)
    first = add_media(db, uso_portal="home_hero", titulo="Hero uno", image_path="/media/hero-1.jpg", orden=10)
    second = add_media(db, uso_portal="home_hero", titulo="Hero dos", image_path="/media/hero-2.jpg", orden=20)
    add_media(db, uso_portal="home_about", titulo="Solo about", image_path="/media/about-only.jpg", orden=0)
    add_media(db, uso_portal="journey_rio", titulo="Solo journey", image_path="/media/journey-only.jpg", orden=0)

    hero = home_section(client.get("/").text, "destination-editorial-hero")

    assert hero.count("destination-hero-slide") == 3
    assert hero.index(first.image_path) < hero.index(second.image_path) < hero.index(third.image_path)
    assert "/media/about-only.jpg" not in hero
    assert "/media/journey-only.jpg" not in hero
    assert "data-hero-rotator" in hero


def test_home_about_assignment_is_exclusive_and_falls_back_only_to_general(destino_admin, monkeypatch):
    client, db, _ = destino_admin
    monkeypatch.setattr(main, "get_cabalango_weather", lambda: {"available": False})
    add_media(db, titulo="General", image_path="/media/general.jpg")
    add_media(db, uso_portal="journey_familia", titulo="Familia", image_path="/media/familia.jpg")
    assigned = add_media(db, uso_portal="home_about", titulo="About", image_path="/media/about.jpg")

    about = home_section(client.get("/").text, "destination-section destination-about")
    assert assigned.image_path in about
    assert "/media/general.jpg" not in about
    assert "/media/familia.jpg" not in about

    assigned.visible = False
    db.commit()
    about = home_section(client.get("/").text, "destination-section destination-about")
    assert "/media/general.jpg" in about
    assert "/media/familia.jpg" not in about


def test_fifth_visible_hero_photo_is_rejected_without_releasing_existing(destino_admin):
    client, db, _ = destino_admin
    existing = [add_media(db, uso_portal="home_hero", titulo=f"Hero {index}") for index in range(4)]
    candidate = add_media(db, titulo="Quinta")

    response = edit(client, candidate.id, uso_portal="home_hero", titulo="Quinta")
    db.expire_all()

    assert response.status_code == 303
    assert "error=Ya+hay+4+fotos+asignadas+al+Hero" in response.headers["location"]
    assert db.get(DestinoMedia, candidate.id).uso_portal == "general"
    assert all(db.get(DestinoMedia, item.id).uso_portal == "home_hero" for item in existing)


def test_admin_explains_all_home_placements(destino_admin):
    client, _, _ = destino_admin
    html = client.get("/admin?area=portal&tab=cabalango").text
    for copy in (
        "Imágenes utilizadas en Inicio", "HERO · DESCUBRÍ CABALANGO", "SOBRE CABALANGO",
        "Un día junto al río", "Quedarse un poco más", "Tiempo para compartir",
        "Biblioteca de fotos y videos",
    ):
        assert copy in html
    assert 'class="destination-home-dashboard"' in html
    assert 'class="destination-home-hero-thumb"' in html or "Usando foto predeterminada" in html
    assert 'class="destination-home-media-preview"' in html


def test_admin_home_slots_have_direct_contextual_dialogs(destino_admin):
    client, _, _ = destino_admin
    html = client.get("/admin?area=portal&tab=cabalango").text

    assert 'id="add-destino-hero"' in html
    hero_dialog = html.split('id="add-destino-hero"', 1)[1].split("</dialog>", 1)[0]
    assert 'action="/admin/cabalango/media"' in hero_dialog
    assert 'name="uso_portal" value="home_hero"' in hero_dialog
    assert 'name="tipo" value="foto"' in hero_dialog
    assert 'name="visible" value="1"' in hero_dialog
    assert 'href="#destino-media-form"' not in html

    expected_dialogs = {
        "home_about": "Cambiar foto de Sobre Cabalango",
        "journey_rio": "Editar Un día junto al río",
        "journey_escapada": "Editar Quedarse un poco más",
        "journey_familia": "Editar Tiempo para compartir",
    }
    for slot, title in expected_dialogs.items():
        assert f'id="home-slot-{slot}"' in html
        dialog = html.split(f'id="home-slot-{slot}"', 1)[1].split("</dialog>", 1)[0]
        assert title in dialog
        assert 'action="/admin/cabalango/media"' in dialog
        assert f'name="uso_portal" value="{slot}"' in dialog
        assert '<select' not in dialog


def hero_add_button(html):
    return html.split('class="btn-primary-custom destination-home-add"', 1)[1].split(">", 1)[0]


def test_admin_hero_dashboard_ignores_hidden_photo_for_preview_and_limit(destino_admin):
    client, db, _ = destino_admin
    for index in range(3):
        add_media(db, uso_portal="home_hero", titulo=f"Hero visible {index}", image_path=f"/media/hero-visible-{index}.jpg")
    add_media(db, uso_portal="home_hero", titulo="Hero oculta", image_path="/media/hero-hidden.jpg", visible=False)

    html = client.get("/admin?area=portal&tab=cabalango").text

    assert html.count('class="destination-home-hero-thumb"') == 3
    assert "disabled" not in hero_add_button(html)
    assert "/media/hero-hidden.jpg" in html  # Sigue disponible en la Biblioteca.
    assert "Hero oculta" in html and "Oculto" in html and ">Hero<" in html


def test_admin_hero_dashboard_disables_add_at_four_visible_photos(destino_admin):
    client, db, _ = destino_admin
    for index in range(4):
        add_media(db, uso_portal="home_hero", titulo=f"Hero {index}", image_path=f"/media/hero-{index}.jpg")

    html = client.get("/admin?area=portal&tab=cabalango").text

    assert html.count('class="destination-home-hero-thumb"') == 4
    assert "disabled" in hero_add_button(html)
    assert 'title="Máximo 4 fotos"' in hero_add_button(html)


def test_admin_about_hidden_assignment_uses_fallback_but_stays_in_library(destino_admin):
    client, db, _ = destino_admin
    add_media(db, uso_portal="home_about", titulo="About oculta", image_path="/media/about-hidden.jpg", visible=False)

    html = client.get("/admin?area=portal&tab=cabalango").text
    about_card = html.split('destination-home-panel--about', 1)[1].split("</article>", 1)[0]

    assert "Usando foto predeterminada" in about_card
    assert "/media/about-hidden.jpg" not in about_card
    assert "/media/about-hidden.jpg" in html
    assert "About oculta" in html and "Sobre Cabalango" in html and "Oculto" in html


def test_admin_journey_hidden_assignment_uses_default_content(destino_admin):
    client, db, _ = destino_admin
    add_media(db, uso_portal="journey_rio", titulo="Río oculto", image_path="/media/rio-hidden.jpg", visible=False)

    html = client.get("/admin?area=portal&tab=cabalango").text
    journey_card = html.split("PLAN RÍO", 1)[1].split("</article>", 1)[0]

    assert "Usando contenido predeterminado" in journey_card
    assert "/media/rio-hidden.jpg" not in journey_card
    assert "/media/rio-hidden.jpg" in html


def test_admin_journey_visible_assignment_shows_active_preview(destino_admin):
    client, db, _ = destino_admin
    add_media(db, uso_portal="journey_rio", titulo="Río publicado", descripcion="Plan activo", image_path="/media/rio-visible.jpg")

    html = client.get("/admin?area=portal&tab=cabalango").text
    journey_card = html.split("PLAN RÍO", 1)[1].split("</article>", 1)[0]

    assert "/media/rio-visible.jpg" in journey_card
    assert "Río publicado" in journey_card and "Plan activo" in journey_card
    assert "Contenido asignado" in journey_card


def test_hero_rotator_supports_reduced_motion():
    css = open("app/static/css/portal.css", encoding="utf-8").read()
    javascript = open("app/static/js/portal-hero-rotator.js", encoding="utf-8").read()
    assert "prefers-reduced-motion: reduce" in css
    assert "prefers-reduced-motion: reduce" in javascript


def test_hero_rotator_preserves_initial_slide_while_preparing_candidates():
    javascript = open("app/static/js/portal-hero-rotator.js", encoding="utf-8").read()

    assert 'hero.querySelector(".destination-hero-slide.is-active") || slides[0]' in javascript
    assert 'initialSlide.classList.add("is-active")' in javascript
    assert 'initialSlide.setAttribute("aria-hidden", "false")' in javascript
    assert "image.complete" in javascript
    assert 'addEventListener("error"' in javascript
    assert "Promise.all" not in javascript
    assert "is-unusable" not in javascript
    assert "prepareCandidate(initialSlide)" not in javascript
    assert "getRotationSlides().length >= 2" in javascript
    assert "rotationSlides.push" not in javascript
    assert "confirmedSlides.add(slide)" in javascript
    assert "orderedSlides.indexOf(activeSlide)" in javascript


def test_hero_rotator_runtime_fail_safe_scenarios():
    result = subprocess.run(
        ["node", "--test", "tests/test_portal_hero_rotator.js"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_hero_rotator_crossfades_before_changing_current_slide_and_caption():
    javascript = open("app/static/js/portal-hero-rotator.js", encoding="utf-8").read()

    incoming = javascript.index('next.classList.add("is-incoming")')
    transition_finished = javascript.index("const finalizeCrossfade")
    remove_current = javascript.index('current.classList.remove("is-active")')
    update_caption = javascript.index("caption.textContent = next.dataset.caption")
    assert incoming < transition_finished < remove_current
    assert incoming < transition_finished < update_caption
    assert "window.setTimeout(finalizeCrossfade, 1900)" in javascript
    assert "if (finalized) return" in javascript


def test_hero_rotator_visibility_management_keeps_one_timer():
    javascript = open("app/static/js/portal-hero-rotator.js", encoding="utf-8").read()

    start = javascript.split("const start = () => {", 1)[1].split("};", 1)[0]
    assert "stop();" in start
    assert "document.hidden" in javascript
    assert 'document.addEventListener("visibilitychange"' in javascript


def test_hero_rotator_css_keeps_slides_absolutely_layered():
    css = open("app/static/css/portal.css", encoding="utf-8").read()
    selector = ".destination-hero-image.has-rotator .destination-hero-slide"
    rule = css.split(f"{selector} {{", 1)[1].split("}", 1)[0]

    for declaration in (
        "height: 100%",
        "inset: 0",
        "object-fit: cover",
        "opacity: 0",
        "position: absolute",
        "width: 100%",
        "z-index: 0",
    ):
        assert declaration in rule
    assert ".destination-hero-image:not(.has-rotator) img {" in css
    assert ".destination-hero-image img {\n  display: block;" not in css


def test_destination_page_busts_only_hero_stylesheet_cache():
    template = open("app/templates/descubri_cabalango.html", encoding="utf-8").read()

    assert "portal.css') }}?v=20260824-hero-layering-fix-1" in template
    assert "portal-hero-rotator.js') }}?v=20260824-hero-crossfade-2" in template
