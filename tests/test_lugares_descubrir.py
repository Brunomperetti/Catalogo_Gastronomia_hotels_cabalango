from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base
from app.models import LugarDescubrir, LugarDescubrirFoto, Usuario


def image_file(name="place.jpg"):
    out = BytesIO(); Image.new("RGB", (20, 20), "green").save(out, "JPEG"); out.seek(0)
    return (name, out, "image/jpeg")

@pytest.fixture
def env(monkeypatch, tmp_path):
    engine=create_engine("sqlite://", connect_args={"check_same_thread":False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Session=sessionmaker(bind=engine); Base.metadata.create_all(engine); db=Session()
    db.add(Usuario(username="admin-places", password_hash=main.hash_password("secret"), rol="admin", activo=True)); db.commit()
    monkeypatch.setattr(main, "STORAGE_DIR", tmp_path)
    def override(): yield db
    main.app.dependency_overrides[main.get_db]=override
    client=TestClient(main.app); client.post("/login", data={"username":"admin-places","password":"secret","next":"/admin"}, follow_redirects=False)
    yield client,db
    main.app.dependency_overrides.pop(main.get_db,None); db.close(); engine.dispose()


def create(client, name="Rincón", order="", featured=False, visible=True):
    data={"nombre":name,"categoria":"naturaleza","descripcion_corta":"Un lugar real para conocer.","orden":order}
    if visible:data["visible"]="1"
    if featured:data["destacado"]="1"
    return client.post("/admin/lugares/crear", data=data, files={"imagen_principal":image_file()}, follow_redirects=False)


def test_model_relationship_slug_and_cascade(env):
    client,db=env
    assert create(client,"Árbol") .status_code==303
    assert create(client,"Árbol").status_code==303
    places=db.query(LugarDescubrir).order_by(LugarDescubrir.id).all(); assert [p.slug for p in places]==["arbol","arbol-2"]
    photo=LugarDescubrirFoto(lugar=places[0],image_url="/x.jpg",orden=0); db.add(photo); db.commit(); pid=photo.id
    db.delete(places[0]); db.commit(); assert db.get(LugarDescubrirFoto,pid) is None


def test_home_visibility_limit_priority_and_postcards_replaced(env):
    client,db=env
    for i in range(5): create(client,f"Lugar {i}",str(i),featured=i==4)
    create(client,"Oculto",visible=False)
    html=client.get("/").text
    assert "Lugares para descubrir" in html and "Postales del río y las sierras" not in html
    assert html.count('class="destination-place-card')==4
    assert html.index("Lugar 4") < html.index("Lugar 0")
    assert "Oculto" not in html


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_home_exposes_exact_place_count_for_count_aware_layout(env, count):
    client, _ = env
    for index in range(count):
        create(client, f"Composición {count}-{index}", str(index))

    html = client.get("/").text

    assert f'data-count="{count}"' in html
    assert html.count('class="destination-place-card') == count


def test_portal_css_defines_every_place_count_and_mobile_override():
    css = open("app/static/css/portal.css", encoding="utf-8").read()

    for count in range(1, 5):
        assert f'.destination-places-grid[data-count="{count}"]' in css
    assert '@media(max-width:700px)' in css
    assert 'display:flex;height:auto;max-width:none;flex-direction:column' in css


def test_places_home_and_admin_expose_stable_layout_hooks(env):
    client, _ = env
    create(client, "Rincón ordenado", order="2", featured=True)

    home = client.get("/").text
    admin = client.get("/admin/lugares").text

    assert 'class="destination-places-grid" data-count="1"' in home
    assert 'class="destination-place-card is-primary"' in home
    assert 'class="destination-place-overlay"' in home
    assert 'class="admin-places-table" role="table"' in admin
    assert 'class="admin-place-thumbnail" role="cell" data-label="Foto"' in admin
    assert 'data-label="Visible"' in admin
    assert 'data-label="Destacado"' in admin
    assert 'class="admin-place-actions" role="cell" data-label="Acciones"' in admin


def test_public_detail_hidden_and_index(env):
    client,db=env; create(client,"Visible",order="0"); create(client,"Secreto",visible=False)
    visible=db.query(LugarDescubrir).filter_by(nombre="Visible").one(); hidden=db.query(LugarDescubrir).filter_by(nombre="Secreto").one()
    assert client.get(f"/lugares/{visible.slug}").status_code==200
    assert client.get(f"/lugares/{hidden.slug}").status_code==404
    assert client.get("/lugares/no-existe").status_code==404
    assert "Secreto" not in client.get("/lugares").text


def test_admin_edit_keeps_image_empty_order_gallery_and_delete(env):
    client,db=env; response=create(client,"Editable",order="0"); place=db.query(LugarDescubrir).filter_by(nombre="Editable").one(); old=place.imagen_principal_url
    response=client.post(f"/admin/lugares/{place.id}/editar",data={"nombre":"Nuevo nombre","categoria":"paseo","descripcion_corta":"Texto actualizado","orden":""},files=[("galeria",image_file("extra.jpg"))],follow_redirects=False)
    assert response.status_code==303; db.refresh(place); assert place.slug=="editable" and place.orden is None and place.imagen_principal_url==old and len(place.fotos)==1
    photo_id=place.fotos[0].id; assert client.post(f"/admin/lugares/{place.id}/fotos/{photo_id}/eliminar").status_code==200
    assert client.get(f"/admin/lugares/{place.id}/eliminar").status_code==405
    assert client.post(f"/admin/lugares/{place.id}/eliminar",follow_redirects=False).status_code==303
    assert client.post(f"/admin/lugares/{place.id}/eliminar").status_code==404


def test_unauthenticated_admin_cannot_delete(env):
    client,db=env; create(client,"Protegido"); place=db.query(LugarDescubrir).filter_by(nombre="Protegido").one(); client.get("/logout")
    assert client.post(f"/admin/lugares/{place.id}/eliminar",follow_redirects=False).status_code==303
    assert db.get(LugarDescubrir,place.id) is not None


@pytest.mark.parametrize("delete_photo", [False, True])
def test_destructive_commit_failure_rolls_back(monkeypatch, delete_photo):
    record = SimpleNamespace(id=7)

    class Query:
        def filter_by(self, **_values): return self
        def first(self): return record

    class FailingSession:
        rolled_back = False
        def query(self, _model): return Query()
        def get(self, _model, _record_id): return record
        def delete(self, _record): pass
        def commit(self): raise RuntimeError("database failure")
        def rollback(self): self.rolled_back = True

    db = FailingSession()
    monkeypatch.setattr(main, "require_admin", lambda request, session: object())

    with pytest.raises(RuntimeError, match="database failure"):
        if delete_photo:
            main.admin_lugar_photo_delete(1, 7, object(), db)
        else:
            main.admin_lugar_delete(7, object(), db)

    assert db.rolled_back is True
