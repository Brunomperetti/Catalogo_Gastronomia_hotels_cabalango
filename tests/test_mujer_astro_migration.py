import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.database import Base
from app.main import app, get_db
from app.models import ActividadAgenda, ActividadAgendaFoto, Empresa


SLUG = "mujer-astro-astrologia-y-tarot"


@pytest.fixture
def migration_env(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    storage = tmp_path / "storage"
    monkeypatch.setattr(main_module, "STORAGE_DIR", storage)
    try:
        yield Session, storage
    finally:
        engine.dispose()


def _write_media(storage: Path, relative: str, content: bytes) -> str:
    path = storage / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return f"/media/{relative}"


def _seed_empresa(session, storage, *, missing_image=False):
    logo = _write_media(storage, f"empresas/{SLUG}/logo/logo.png", b"logo")
    banner = _write_media(storage, f"empresas/{SLUG}/banner/banner.webp", b"banner")
    gallery = [
        _write_media(storage, f"empresas/{SLUG}/galeria/one.jpg", b"one"),
        _write_media(storage, f"empresas/{SLUG}/galeria/two.jpeg", b"two"),
        _write_media(storage, f"empresas/{SLUG}/galeria/three.png", b"three"),
    ]
    if missing_image:
        gallery[1] = f"/media/empresas/{SLUG}/galeria/missing.jpeg"
    empresa = Empresa(
        nombre="Mujer Astro Astrología y Tarot", slug=SLUG,
        theme="actividades", activo=True, destacado=1,
        descripcion_corta="Astrología y Tarot",
        descripcion="Descripción completa conservada.",
        horarios="Días: todos los días | Horarios: 9:00–20:00 | Todo el año: Sí",
        whatsapp="+54 9 3541 000000", instagram="@mujer.astro",
        maps_url="https://maps.example/mujer", direccion="Cabalango",
        lugar_encuentro="Casa Mujer Astro", web_url="https://example.test",
        telefono="3541000000", facebook="mujerastro",
        logo_url=logo, banner_url=banner,
        galeria_urls=json.dumps([gallery[0], gallery[1], gallery[0], gallery[2]]),
    )
    session.add(empresa)
    session.commit()
    return empresa.id, {logo, banner, *gallery}


def test_complete_data_and_media_migration_is_idempotent(migration_env, caplog):
    caplog.set_level("INFO", logger="app.main")
    Session, storage = migration_env
    with Session() as db:
        empresa_id, source_urls = _seed_empresa(db, storage)
        original = {
            column.name: getattr(db.get(Empresa, empresa_id), column.name)
            for column in Empresa.__table__.columns if column.name != "activo"
        }

        assert main_module.migrate_mujer_astro_provider_to_activity(db) == 1
        activity = db.query(ActividadAgenda).filter_by(slug=SLUG).one()
        assert db.query(ActividadAgenda).count() == 1
        assert (activity.tipo, activity.categoria, activity.momento) == (
            "actividad", "bienestar", "todo_el_dia",
        )
        assert activity.publicado is True
        assert activity.estado == "programado"
        assert activity.mostrar_en_home is False
        assert activity.prioridad_home == 0
        assert activity.oficial is False
        assert activity.destacado is True
        assert activity.fecha_inicio is None and activity.fecha_fin is None
        assert activity.titulo == original["nombre"]
        assert activity.descripcion_corta == original["descripcion_corta"]
        assert activity.descripcion == original["descripcion"]
        assert activity.horarios == original["horarios"]
        assert activity.whatsapp == original["whatsapp"]
        assert activity.instagram == original["instagram"]
        assert activity.maps_url == original["maps_url"]
        assert activity.direccion == original["direccion"]
        assert activity.url_externa == original["web_url"]
        assert activity.lugar == original["lugar_encuentro"]

        source = db.get(Empresa, empresa_id)
        assert source.id == empresa_id and source.activo is False
        assert all(getattr(source, name) == value for name, value in original.items())
        assert activity.imagen_url.endswith(".webp")
        assert "/actividades/mujer-astro-astrologia-y-tarot/migrated-principal-" in activity.imagen_url
        photos = db.query(ActividadAgendaFoto).order_by(ActividadAgendaFoto.orden).all()
        assert [photo.orden for photo in photos] == list(range(4))
        assert [Path(photo.image_url).suffix for photo in photos] == [".jpg", ".jpeg", ".png", ".png"]
        assert all("/media/actividades/" in photo.image_url for photo in photos)
        assert all((storage / url.removeprefix("/media/")).exists() for url in source_urls)

        files_before = sorted(path.name for path in (storage / "actividades" / SLUG).iterdir())
        rows_before = [(photo.image_url, photo.orden) for photo in photos]
        assert main_module.migrate_mujer_astro_provider_to_activity(db) == 0
        assert db.query(ActividadAgenda).count() == 1
        assert [(p.image_url, p.orden) for p in db.query(ActividadAgendaFoto).order_by(ActividadAgendaFoto.orden)] == rows_before
        assert sorted(path.name for path in (storage / "actividades" / SLUG).iterdir()) == files_before
        assert "Unmapped legacy fields: telefono, facebook, logo" in caplog.text


def test_place_falls_back_to_address(migration_env):
    Session, storage = migration_env
    with Session() as db:
        empresa_id, _ = _seed_empresa(db, storage)
        db.get(Empresa, empresa_id).lugar_encuentro = "  "
        db.commit()
        assert main_module.migrate_mujer_astro_provider_to_activity(db) == 1
        assert db.query(ActividadAgenda).one().lugar == "Cabalango"


def test_missing_managed_file_rolls_back_and_keeps_legacy_active(migration_env, caplog):
    Session, storage = migration_env
    with Session() as db:
        empresa_id, _ = _seed_empresa(db, storage, missing_image=True)
        assert main_module.migrate_mujer_astro_provider_to_activity(db) == 0
        assert db.query(ActividadAgenda).count() == 0
        assert db.get(Empresa, empresa_id).activo is True
        target = storage / "actividades" / SLUG
        assert not target.exists() or not list(target.iterdir())
        assert "migration aborted safely: FileNotFoundError" in caplog.text


def test_existing_activity_conflict_does_not_overwrite_or_deactivate(migration_env, caplog):
    Session, storage = migration_env
    with Session() as db:
        empresa_id, _ = _seed_empresa(db, storage)
        db.add(ActividadAgenda(
            tipo="actividad", titulo="Edición manual", slug=SLUG,
            categoria="otros", momento="dia", publicado=False,
        ))
        db.commit()
        assert main_module.migrate_mujer_astro_provider_to_activity(db) == 0
        assert db.query(ActividadAgenda).one().titulo == "Edición manual"
        assert db.get(Empresa, empresa_id).activo is True
        assert "migration conflict" in caplog.text


def test_legacy_redirect_and_native_activity_pages(migration_env):
    Session, storage = migration_env
    with Session() as db:
        _seed_empresa(db, storage)
        assert main_module.migrate_mujer_astro_provider_to_activity(db) == 1

    def override_db():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            legacy = client.get(f"/prestador/{SLUG}", follow_redirects=False)
            assert legacy.status_code == 308
            assert legacy.headers["location"].endswith(f"/actividades/{SLUG}")
            detail = client.get(f"/actividades/{SLUG}")
            listing = client.get("/actividades")
        assert detail.status_code == 200
        assert "Mujer Astro Astrología y Tarot" in detail.text
        assert "Horarios / disponibilidad" in detail.text
        assert "Resumen del lugar" not in detail.text
        assert listing.status_code == 200
        assert "Mujer Astro Astrología y Tarot" in listing.text
        assert f'href="/prestador/{SLUG}"' not in listing.text
    finally:
        app.dependency_overrides.pop(get_db, None)
