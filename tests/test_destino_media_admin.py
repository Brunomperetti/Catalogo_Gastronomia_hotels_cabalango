from io import BytesIO

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
    defaults = dict(tipo="foto", categoria="rio_naturaleza", titulo="Postal", descripcion="Original", image_path="/media/destino/fotos/original.jpg", orden=1, visible=True, destacado=False)
    defaults.update(values)
    item = DestinoMedia(**defaults)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def edit(client, item_id, **changes):
    data = {"titulo": "Postal editada", "categoria": "paisajes", "descripcion": "Descripción renovada", "orden": "0", "visible": "1", "destacado": "1", "video_url": ""}
    data.update(changes)
    data = {key: value for key, value in data.items() if value is not None}
    return client.post(f"/admin/cabalango/media/{item_id}/editar", data=data, follow_redirects=False)


def test_admin_renders_working_unique_edit_dialog_and_order_actions(destino_admin):
    client, db, _ = destino_admin
    item = add_media(db)
    response = client.get("/admin?area=portal&tab=cabalango")
    html = response.text
    assert response.status_code == 200
    for expected_text in (
        "Descubrí Cabalango",
        "Texto editorial del destino",
        "Fotos y videos del destino",
        "Contenido cargado",
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
