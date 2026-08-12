from fastapi import FastAPI, UploadFile, File, Depends, Request, Form, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text, func, case, or_
from pydantic import BaseModel
from typing import List
import pandas as pd
import zipfile
import shutil
import os
import re
import json
import math
import uuid
import hashlib
import hmac
import secrets
import threading
import urllib.request
import unicodedata
from urllib.parse import quote, urlparse, urlencode
from pathlib import Path
from io import BytesIO
from datetime import datetime, timezone, timedelta

# PDF
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

from app.database import SessionLocal, engine, Base
from app import models
from app.agenda import CATEGORIES, MOMENTS, TYPES, derived_status, get_public_activities, group_public_agenda, now_cabalango, validate_activity

app = FastAPI()
APP_BUILD = "2026-07-01-descubri-cabalango-v1"
MEDIA_ROOT_ENV = os.getenv("MEDIA_ROOT")
MEDIA_URL_PREFIX = (os.getenv("MEDIA_URL", "/media").strip() or "/media").rstrip("/") or "/media"
STORAGE_DIR = Path(MEDIA_ROOT_ENV or os.getenv("STORAGE_DIR", "app/storage")).resolve()
MEDIA_BASE_DIR = STORAGE_DIR / "empresas"
PRODUCTOS_MEDIA_TYPE = "productos"
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_MENU_IMAGE_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS
PRICE_POLICY_VALUES = {"mostrar", "consultar", "automatico"}
STOCK_POLICY_VALUES = {"mostrar", "ocultar", "automatico"}
THEME_VALUES = {"default", "autopartes", "comida", "gastronomia", "alojamiento", "servicios", "actividades", "farmacia", "ferreteria", "petshop"}
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_BASE_DIR.mkdir(parents=True, exist_ok=True)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "cambia-esto-en-render"),
    same_site="lax",
    https_only=False,
)

# ---------------------------------------------------
# STARTUP (Render-safe)
# ---------------------------------------------------
def run_startup_db_maintenance():
    """Run DB bootstrap work without blocking Render's port detection.

    Render marks the deploy as failed if the ASGI process spends too long in
    FastAPI startup before Uvicorn opens $PORT.  These operations are
    idempotent, but they can wait on a remote database lock/connection, so they
    run in a daemon thread after startup returns.
    """
    try:
        Base.metadata.create_all(bind=engine)
        ensure_empresa_media_columns()
        ensure_usuario_columns()
        ensure_catalog_lead_columns()
        ensure_review_columns()
        ensure_destino_media_table()
        ensure_destino_contenido_table()
        ensure_actividad_agenda_table()
        ensure_default_admin_user()
        print("[catalogo] db maintenance completed")
    except Exception as exc:
        print(f"[catalogo] db maintenance failed: {exc}")


@app.on_event("startup")
def on_startup():
    global _startup_db_maintenance_started
    with _startup_db_maintenance_lock:
        if not _startup_db_maintenance_started:
            threading.Thread(
                target=run_startup_db_maintenance,
                name="catalogo-db-maintenance",
                daemon=True,
            ).start()
            _startup_db_maintenance_started = True
    print("CODEX_SIGNATURE_2026_04_15")
    route_paths = sorted(
        {
            getattr(r, "path", "")
            for r in app.routes
            if getattr(r, "path", "")
        }
    )
    print(
        "[catalogo] startup build=",
        APP_BUILD,
        " commit=",
        os.getenv("RENDER_GIT_COMMIT", ""),
        " service=",
        os.getenv("RENDER_SERVICE_ID", ""),
    )
    print("[catalogo] routes=", ", ".join(route_paths))

# ---------------------------------------------------
# Static & Templates
# ---------------------------------------------------
app.mount("/static", StaticFiles(directory="app/static"), name="static")
if STORAGE_DIR.exists() or MEDIA_ROOT_ENV:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    app.mount(MEDIA_URL_PREFIX, StaticFiles(directory=str(STORAGE_DIR)), name="media")
templates = Jinja2Templates(directory="app/templates")
_startup_db_maintenance_started = False
_startup_db_maintenance_lock = threading.Lock()


def ensure_empresa_media_columns():
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("empresas")}
    with engine.begin() as conn:
        if "logo_url" not in columns:
            conn.execute(text("ALTER TABLE empresas ADD COLUMN logo_url VARCHAR"))
        if "banner_url" not in columns:
            conn.execute(text("ALTER TABLE empresas ADD COLUMN banner_url VARCHAR"))
        if "politica_precio_catalogo" not in columns:
            conn.execute(text("ALTER TABLE empresas ADD COLUMN politica_precio_catalogo VARCHAR DEFAULT 'automatico'"))
        if "politica_stock_catalogo" not in columns:
            conn.execute(text("ALTER TABLE empresas ADD COLUMN politica_stock_catalogo VARCHAR DEFAULT 'mostrar'"))
        if "theme" not in columns:
            conn.execute(text("ALTER TABLE empresas ADD COLUMN theme VARCHAR DEFAULT 'default'"))
        optional_columns = {
            "descripcion": "TEXT",
            "telefono": "VARCHAR",
            "instagram": "VARCHAR",
            "direccion": "VARCHAR",
            "maps_url": "VARCHAR",
            "subgrupo": "VARCHAR",
            "subtipo": "VARCHAR",
            "descripcion_corta": "VARCHAR",
            "facebook": "VARCHAR",
            "web_url": "VARCHAR",
            "destacado": "BOOLEAN",
            "activo": "BOOLEAN",
            "horarios": "VARCHAR",
            "precio_desde": "VARCHAR",
            "capacidad": "VARCHAR",
            "habitaciones": "VARCHAR",
            "banos": "VARCHAR",
            "video_url": "VARCHAR",
            "menu_url": "VARCHAR",
            "promocion": "VARCHAR",
            "guardia": "VARCHAR",
            "fecha": "VARCHAR",
            "organizador": "VARCHAR",
            "lugar_encuentro": "VARCHAR",
            "delivery": "BOOLEAN",
            "take_away": "BOOLEAN",
            "comer_en_lugar": "BOOLEAN",
            "pileta": "BOOLEAN",
            "rio": "BOOLEAN",
            "mascotas": "BOOLEAN",
            "cochera": "BOOLEAN",
            "wifi": "BOOLEAN",
            "parrilla": "BOOLEAN",
            "aire_acondicionado": "BOOLEAN",
            "calefaccion": "BOOLEAN",
            "galeria_urls": "TEXT",
            "menu_fotos_urls": "TEXT",
            "rating_promedio": "FLOAT",
            "rating_cantidad": "INTEGER",
            "reviews_destacadas": "TEXT",
        }
        for column_name, column_type in optional_columns.items():
            if column_name not in columns:
                conn.execute(text(f"ALTER TABLE empresas ADD COLUMN {column_name} {column_type}"))
        conn.execute(
            text(
                "UPDATE empresas "
                "SET politica_precio_catalogo = 'automatico' "
                "WHERE politica_precio_catalogo IS NULL "
                "OR politica_precio_catalogo NOT IN ('mostrar','consultar','automatico')"
            )
        )
        conn.execute(
            text(
                "UPDATE empresas "
                "SET politica_stock_catalogo = 'mostrar' "
                "WHERE politica_stock_catalogo IS NULL "
                "OR politica_stock_catalogo NOT IN ('mostrar','ocultar','automatico')"
            )
        )
        conn.execute(
            text(
                "UPDATE empresas "
                "SET theme = 'default' "
                "WHERE theme IS NULL "
                "OR theme NOT IN ('default','autopartes','comida','gastronomia','alojamiento','servicios','actividades','farmacia','ferreteria','petshop')"
            )
        )


def ensure_usuario_columns():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "usuarios" not in tables:
        return

    columns = {col["name"] for col in inspector.get_columns("usuarios")}
    with engine.begin() as conn:
        if "rol" not in columns:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN rol VARCHAR DEFAULT 'cliente'"))
        if "activo" not in columns:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN activo BOOLEAN DEFAULT TRUE"))
        if "empresa_id" not in columns:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN empresa_id INTEGER"))


def ensure_catalog_lead_columns():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "catalog_leads" not in tables:
        return

    columns = {col["name"] for col in inspector.get_columns("catalog_leads")}
    with engine.begin() as conn:
        if "estado" not in columns:
            conn.execute(text("ALTER TABLE catalog_leads ADD COLUMN estado VARCHAR DEFAULT 'nuevo'"))
        if "notas_internas" not in columns:
            conn.execute(text("ALTER TABLE catalog_leads ADD COLUMN notas_internas TEXT"))
        if "archived_at" not in columns:
            conn.execute(text("ALTER TABLE catalog_leads ADD COLUMN archived_at TIMESTAMP"))
        if "deleted_at" not in columns:
            conn.execute(text("ALTER TABLE catalog_leads ADD COLUMN deleted_at TIMESTAMP"))
        conn.execute(
            text(
                "UPDATE catalog_leads "
                "SET estado = 'nuevo' "
                "WHERE estado IS NULL OR estado NOT IN ('nuevo','contactado','oportunidad','archivado')"
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_catalog_leads_estado ON catalog_leads(estado)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_catalog_leads_archived_at ON catalog_leads(archived_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_catalog_leads_deleted_at ON catalog_leads(deleted_at)"))


def ensure_review_columns():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "reviews" not in tables:
        Base.metadata.create_all(bind=engine, tables=[models.Review.__table__])
        return

    columns = {col["name"] for col in inspector.get_columns("reviews")}
    optional_columns = {
        "prestador_id": "INTEGER",
        "nombre": "VARCHAR",
        "contacto": "VARCHAR",
        "rating": "INTEGER",
        "comentario": "TEXT",
        "tipo_visitante": "VARCHAR",
        "fecha": "VARCHAR",
        "estado": "VARCHAR DEFAULT 'pendiente'",
        "visible": "BOOLEAN DEFAULT FALSE",
        "created_at": "TIMESTAMP",
    }
    with engine.begin() as conn:
        for column_name, column_type in optional_columns.items():
            if column_name not in columns:
                conn.execute(text(f"ALTER TABLE reviews ADD COLUMN {column_name} {column_type}"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reviews_prestador_id ON reviews(prestador_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reviews_estado ON reviews(estado)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reviews_visible ON reviews(visible)"))


def ensure_destino_contenido_table():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "destino_contenido" not in tables:
        Base.metadata.create_all(bind=engine, tables=[models.DestinoContenido.__table__])
        return

    columns = {col["name"] for col in inspector.get_columns("destino_contenido")}
    optional_columns = {
        "introduccion": "TEXT",
        "historia": "TEXT",
        "ubicacion": "TEXT",
        "naturaleza": "TEXT",
        "recomendaciones": "TEXT",
        "vida_local": "TEXT",
        "video_url": "VARCHAR",
        "visible": "BOOLEAN DEFAULT TRUE",
        "updated_at": "TIMESTAMP",
    }
    with engine.begin() as conn:
        for column_name, column_type in optional_columns.items():
            if column_name not in columns:
                conn.execute(text(f"ALTER TABLE destino_contenido ADD COLUMN {column_name} {column_type}"))


def ensure_destino_media_table():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "destino_media" not in tables:
        Base.metadata.create_all(bind=engine, tables=[models.DestinoMedia.__table__])
        return

    columns = {col["name"] for col in inspector.get_columns("destino_media")}
    optional_columns = {
        "tipo": "VARCHAR DEFAULT 'foto'",
        "categoria": "VARCHAR DEFAULT 'rio_naturaleza'",
        "titulo": "VARCHAR",
        "descripcion": "TEXT",
        "image_path": "VARCHAR",
        "video_url": "VARCHAR",
        "destacado": "BOOLEAN DEFAULT FALSE",
        "orden": "INTEGER DEFAULT 0",
        "visible": "BOOLEAN DEFAULT TRUE",
        "created_at": "TIMESTAMP",
    }
    with engine.begin() as conn:
        for column_name, column_type in optional_columns.items():
            if column_name not in columns:
                conn.execute(text(f"ALTER TABLE destino_media ADD COLUMN {column_name} {column_type}"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_destino_media_tipo ON destino_media(tipo)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_destino_media_categoria ON destino_media(categoria)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_destino_media_visible ON destino_media(visible)"))


def ensure_actividad_agenda_table():
    """Idempotent, additive migration: no existing table or row is altered."""
    if "actividades_agenda" not in set(inspect(engine).get_table_names()):
        Base.metadata.create_all(bind=engine, tables=[models.ActividadAgenda.__table__])

# ---------------------------------------------------
# DB Dependency
# ---------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------
# RESOLUCIÓN DE EMPRESA (sin estado global)
# ---------------------------------------------------
def get_empresa_by_slug(db: Session, slug: str | None):
    slug = (slug or "").strip().lower()
    if not slug:
        return None
    return db.query(models.Empresa).filter(models.Empresa.slug == slug).first()


def get_default_empresa(db: Session):
    return db.query(models.Empresa).order_by(models.Empresa.nombre.asc()).first()


ADMIN_TAB_ALIASES = {"empresa": "prestadores", "productos": "tecnico", "backup": "configuracion", "avanzado": "tecnico", "datos_rubro": "rubro"}
ADMIN_PROVIDER_TABS = {"prestadores", "ficha", "fotos", "contacto", "rubro", "leads", "opiniones", "usuarios"}
ADMIN_PORTAL_TABS = {"cabalango", "configuracion", "tecnico"}


def normalize_admin_tab(tab: str | None, area: str | None = None) -> str:
    normalized = ADMIN_TAB_ALIASES.get(clean_text(tab, default="prestadores").lower(), clean_text(tab, default="prestadores").lower())
    normalized_area = clean_text(area, default="").lower()
    allowed = ADMIN_PORTAL_TABS if normalized_area == "portal" else ADMIN_PROVIDER_TABS if normalized_area == "prestador" else ADMIN_PROVIDER_TABS | ADMIN_PORTAL_TABS
    return normalized if normalized in allowed else ("cabalango" if normalized_area == "portal" else "prestadores")


def panel_redirect(
    empresa_slug: str | None = None,
    msg: str = "",
    error: str = "",
    path: str = "/admin",
    area: str | None = None,
    tab: str | None = None,
    active_tab: str | None = None,
):
    requested_tab = tab or active_tab
    normalized_area = clean_text(area, default="").lower()
    if path == "/admin":
        if normalized_area not in {"prestador", "portal"}:
            candidate = normalize_admin_tab(requested_tab) if requested_tab else ""
            normalized_area = "portal" if candidate in ADMIN_PORTAL_TABS else "prestador"
        requested_tab = normalize_admin_tab(requested_tab, normalized_area) if requested_tab else None
    params = {}
    if path == "/admin" and normalized_area:
        params["area"] = normalized_area
    if empresa_slug and (path != "/admin" or normalized_area == "prestador"):
        params["empresa"] = empresa_slug
    if path == "/admin" and requested_tab:
        params["tab"] = requested_tab
    if msg:
        params["msg"] = msg
    if error:
        params["error"] = error
    query = urlencode(params)
    return RedirectResponse(url=f"{path}?{query}" if query else path, status_code=303)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 310000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _, salt, saved = password_hash.split("$", 2)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 310000).hex()
        return hmac.compare_digest(digest, saved)
    except Exception:
        return False


def ensure_default_admin_user():
    username = (os.getenv("ADMIN_USER", "admin").strip() or "admin").lower()
    raw_password = os.getenv("ADMIN_PASSWORD", "admin123").strip() or "admin123"
    with SessionLocal() as db:
        existing = db.query(models.Usuario).filter(models.Usuario.username == username).first()
        if existing:
            return
        user = models.Usuario(
            username=username,
            password_hash=hash_password(raw_password),
            rol="admin",
            activo=True,
            empresa_id=None,
        )
        db.add(user)
        db.commit()


def get_current_user(request: Request, db: Session) -> models.Usuario | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(models.Usuario).filter(models.Usuario.id == user_id, models.Usuario.activo == True).first()


def require_login(request: Request, db: Session):
    user = get_current_user(request, db)
    if user:
        return user
    next_path = quote(str(request.url.path))
    return RedirectResponse(url=f"/login?next={next_path}", status_code=303)


def require_admin(request: Request, db: Session):
    user = require_login(request, db)
    if isinstance(user, RedirectResponse):
        return user
    if user.rol != "admin":
        return RedirectResponse(url="/mi-ficha?error=No tenés permisos para acceder al panel admin", status_code=303)
    return user


def get_user_empresa(user: models.Usuario, db: Session):
    if user.rol == "cliente":
        if not user.empresa_id:
            return None
        return db.query(models.Empresa).filter(models.Empresa.id == user.empresa_id).first()
    return None


def resolve_empresa_for_user(user: models.Usuario, db: Session, slug: str | None):
    if user.rol == "admin":
        return get_empresa_by_slug(db, slug) or get_default_empresa(db)
    return get_user_empresa(user, db)


def get_dashboard_path(user: models.Usuario) -> str:
    return "/admin" if user.rol == "admin" else "/mi-ficha"


def redirect_for_user(user: models.Usuario, empresa_slug: str | None = None, msg: str = "", error: str = ""):
    return panel_redirect(
        empresa_slug=empresa_slug,
        msg=msg,
        error=error,
        path=get_dashboard_path(user),
    )


def can_access_empresa(user: models.Usuario, empresa_slug: str | None, db: Session):
    empresa = resolve_empresa_for_user(user, db, empresa_slug)
    if not empresa:
        return None
    if user.rol == "cliente" and user.empresa_id != empresa.id:
        return None
    return empresa


LEAD_SESSION_KEY = "catalog_lead_sessions"
EVENT_TYPES = {
    "catalog_entered",
    "search_performed",
    "product_viewed",
    "cart_item_added",
    "whatsapp_clicked",
    "pdf_downloaded",
}
EVENT_TYPE_LABELS = {
    "catalog_entered": "Ingresó al catálogo",
    "search_performed": "Realizó búsqueda",
    "product_viewed": "Vio producto",
    "cart_item_added": "Agregó al pedido",
    "whatsapp_clicked": "Click en WhatsApp",
    "pdf_downloaded": "Descargó PDF",
}
LEAD_STATUS_VALUES = {"nuevo", "contactado", "oportunidad", "archivado"}
LEAD_STATUS_LABELS = {
    "nuevo": "Nuevo",
    "contactado": "Contactado",
    "oportunidad": "Oportunidad",
    "archivado": "Archivado",
}

DESTINO_MEDIA_CATEGORIES = {
    "rio_naturaleza": "Río y naturaleza",
    "paisajes": "Paisajes y montaña",
    "vida_local": "Vida local",
    "eventos": "Eventos y ferias",
    "actividades": "Caminatas y actividades",
    "videos": "Videos / recorridos",
}
DESTINO_MEDIA_CATEGORY_DESCRIPTIONS = {
    "rio_naturaleza": "Agua clara, sombra y rincones para bajar el ritmo.",
    "paisajes": "Sierras, monte nativo y postales abiertas del valle.",
    "vida_local": "La calidez de la comunidad y sus pequeños momentos.",
    "eventos": "Ferias, encuentros y propuestas que conectan visitantes y vecinos.",
    "actividades": "Caminatas, recorridos y experiencias al aire libre.",
    "videos": "Recorridos para sentir Cabalango antes de llegar.",
}

def normalize_destino_categoria(value: str) -> str:
    value = clean_text(value, default="rio_naturaleza").lower()
    return value if value in DESTINO_MEDIA_CATEGORIES else "rio_naturaleza"

def normalize_destino_tipo(value: str) -> str:
    return "video" if clean_text(value, default="foto").lower() == "video" else "foto"

def get_destino_media_dir() -> Path:
    return STORAGE_DIR / "destino" / "fotos"

def build_destino_media_url(filename: str) -> str:
    return f"{MEDIA_URL_PREFIX}/destino/fotos/{filename}"

async def save_destino_image(upload: UploadFile) -> str:
    target_dir = get_destino_media_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_unique_filename(upload, prefix="cabalango")
    with open(target_dir / filename, "wb") as f:
        f.write(await upload.read())
    return build_destino_media_url(filename)

def get_public_destino_media(db: Session, tipo: str | None = None) -> list[models.DestinoMedia]:
    query = db.query(models.DestinoMedia).filter(models.DestinoMedia.visible == True)
    if tipo:
        query = query.filter(models.DestinoMedia.tipo == tipo)
    return query.order_by(models.DestinoMedia.destacado.desc(), models.DestinoMedia.orden.asc(), models.DestinoMedia.created_at.desc(), models.DestinoMedia.id.desc()).all()


DESTINO_DEFAULT_CONTENT = {
    "introduccion": "Cabalango combina río, monte, sierras y vida local en un entorno tranquilo para descansar y recorrer.",
    "historia": "Un destino serrano de ritmo pausado, memoria local y paisajes que invitan a volver a lo simple.",
    "ubicacion": "Cabalango se encuentra en el Valle de Punilla, Córdoba, cerca de Villa Carlos Paz y conectado por caminos serranos.",
    "naturaleza": "Río, balnearios, senderos, monte nativo y paisajes serranos forman parte de la experiencia cotidiana.",
    "recomendaciones": "Traé calzado cómodo, abrigo liviano para la tarde y revisá el clima antes de planificar caminatas o río.",
    "vida_local": "Ferias, sabores caseros, prestadores familiares y encuentros comunitarios muestran la identidad del pueblo.",
    "video_url": "",
}

def get_destino_content(db: Session) -> models.DestinoContenido:
    ensure_destino_contenido_table()
    content = db.query(models.DestinoContenido).order_by(models.DestinoContenido.id.asc()).first()
    if content:
        return content
    content = models.DestinoContenido(**DESTINO_DEFAULT_CONTENT, visible=True, updated_at=utc_now())
    db.add(content)
    db.commit()
    db.refresh(content)
    return content

_weather_cache = {"expires_at": None, "data": None}
WEATHER_CODE_LABELS = {0: "Despejado", 1: "Mayormente despejado", 2: "Parcialmente nublado", 3: "Nublado", 45: "Neblina", 48: "Neblina", 51: "Llovizna", 53: "Llovizna", 55: "Llovizna", 61: "Lluvia", 63: "Lluvia", 65: "Lluvia intensa", 80: "Chaparrones", 95: "Tormenta"}

def get_cabalango_weather() -> dict:
    now = utc_now()
    if _weather_cache["data"] and _weather_cache["expires_at"] and _weather_cache["expires_at"] > now:
        return _weather_cache["data"]
    params = urlencode({
        "latitude": -31.395,
        "longitude": -64.562,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "America/Argentina/Cordoba",
        "forecast_days": 7,
    })
    fallback = {"available": False, "message": "Clima no disponible por el momento."}
    try:
        with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{params}", timeout=2.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        current = payload.get("current") or {}
        daily = payload.get("daily") or {}
        temp = current.get("temperature_2m")
        rain = (daily.get("precipitation_probability_max") or [None])[0]
        times = daily.get("time") or []
        maxs = daily.get("temperature_2m_max") or []
        mins = daily.get("temperature_2m_min") or []
        rains = daily.get("precipitation_probability_max") or []
        codes = daily.get("weather_code") or []
        forecast = []
        for idx in range(1, min(7, len(times))):
            forecast.append({
                "label": "Mañana" if idx == 1 else f"En {idx} días",
                "min": mins[idx] if idx < len(mins) else None,
                "max": maxs[idx] if idx < len(maxs) else None,
                "rain_probability": rains[idx] if idx < len(rains) else 0,
                "condition": WEATHER_CODE_LABELS.get(codes[idx] if idx < len(codes) else None, "Clima serrano"),
            })
        if (rain or 0) >= 45:
            advice = "Posible lluvia, revisá antes de salir."
        elif (temp or 20) >= 26 and (rain or 0) < 35:
            advice = "Buen día para río y caminatas."
        elif (temp or 20) < 16:
            advice = "Llevá abrigo liviano."
        else:
            advice = "Ideal para recorrer."
        weather = {
            "available": temp is not None,
            "temperature": temp,
            "apparent_temperature": current.get("apparent_temperature"),
            "condition": WEATHER_CODE_LABELS.get(current.get("weather_code"), "Clima serrano"),
            "min": (daily.get("temperature_2m_min") or [None])[0],
            "max": (daily.get("temperature_2m_max") or [None])[0],
            "rain_probability": rain,
            "wind": current.get("wind_speed_10m"),
            "advice": advice,
            "forecast": forecast,
        }
    except Exception:
        weather = fallback
    _weather_cache.update({"data": weather, "expires_at": now + timedelta(minutes=25)})
    return weather

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class CatalogEventPayload(BaseModel):
    event_type: str
    product_code: str | None = None
    search_term: str | None = None
    metadata: dict | None = None


def utc_now():
    return datetime.now(timezone.utc)


def get_lead_session_for_slug(request: Request, slug: str) -> dict | None:
    sessions = request.session.get(LEAD_SESSION_KEY) or {}
    lead_session = sessions.get(slug)
    if isinstance(lead_session, dict):
        return lead_session
    return None


def set_lead_session_for_slug(request: Request, slug: str, lead_id: int, session_token: str):
    sessions = request.session.get(LEAD_SESSION_KEY) or {}
    sessions[slug] = {"lead_id": lead_id, "session_token": session_token}
    request.session[LEAD_SESSION_KEY] = sessions


def clear_lead_session_for_slug(request: Request, slug: str):
    sessions = request.session.get(LEAD_SESSION_KEY) or {}
    if slug in sessions:
        sessions.pop(slug, None)
        request.session[LEAD_SESSION_KEY] = sessions


def get_active_catalog_lead(request: Request, slug: str, empresa_id: int, db: Session) -> models.CatalogLead | None:
    lead_session = get_lead_session_for_slug(request, slug)
    if not lead_session:
        return None

    lead_id = lead_session.get("lead_id")
    session_token = lead_session.get("session_token")
    if not lead_id or not session_token:
        clear_lead_session_for_slug(request, slug)
        return None

    lead = (
        db.query(models.CatalogLead)
        .filter(
            models.CatalogLead.id == int(lead_id),
            models.CatalogLead.empresa_catalogo_id == empresa_id,
            models.CatalogLead.session_token == str(session_token),
        )
        .first()
    )
    if not lead:
        clear_lead_session_for_slug(request, slug)
        return None
    return lead


def register_catalog_event(
    db: Session,
    lead: models.CatalogLead,
    empresa_id: int,
    event_type: str,
    product_code: str | None = None,
    search_term: str | None = None,
    metadata: dict | None = None,
):
    if event_type not in EVENT_TYPES:
        return

    event = models.CatalogLeadEvent(
        lead_id=lead.id,
        empresa_catalogo_id=empresa_id,
        event_type=event_type,
        product_code=clean_text(product_code, default="") or None,
        search_term=clean_text(search_term, default="") or None,
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False) if metadata else None,
        created_at=utc_now(),
    )
    lead.ultima_actividad = utc_now()
    db.add(event)
    db.add(lead)
    db.commit()


def parse_bool_query_flag(value: str | None) -> bool | None:
    clean = clean_text(value, default="").lower()
    if clean in {"1", "true", "si", "sí", "yes"}:
        return True
    if clean in {"0", "false", "no"}:
        return False
    return None


def normalize_lead_status(value: str | None) -> str:
    status = clean_text(value, default="nuevo").lower()
    return status if status in LEAD_STATUS_VALUES else "nuevo"


def compute_lead_interest(
    search_count: int,
    product_view_count: int,
    cart_add_count: int,
    has_whatsapp_click: bool,
    has_pdf_download: bool,
) -> dict:
    score = 1
    score += min(int(search_count or 0), 8)
    score += min(int(product_view_count or 0), 10)
    score += min(int(cart_add_count or 0) * 4, 12)
    if has_whatsapp_click:
        score += 7
    if has_pdf_download:
        score += 5

    if score >= 15:
        return {"label": "Caliente", "slug": "caliente", "score": score}
    if score >= 7:
        return {"label": "Interesado", "slug": "interesado", "score": score}
    return {"label": "Frío", "slug": "frio", "score": score}


def get_lead_priority(
    *,
    lead_status: str,
    interest: dict,
    last_activity_at: datetime | None,
    created_at: datetime | None,
    cart_add_count: int,
    has_whatsapp_click: bool,
    has_pdf_download: bool,
    has_notes: bool,
) -> dict:
    status = normalize_lead_status(lead_status)
    now = utc_now()
    score = 0

    status_weight = {
        "nuevo": 20,
        "contactado": 12,
        "oportunidad": 24,
        "archivado": -40,
    }
    interest_weight = {
        "frio": 5,
        "interesado": 14,
        "caliente": 25,
    }
    score += status_weight.get(status, 0)
    score += interest_weight.get(interest.get("slug", "frio"), 5)
    score += min(int(cart_add_count or 0) * 5, 20)
    score += 7 if has_whatsapp_click else 0
    score += 4 if has_pdf_download else 0
    score += 2 if has_notes else 0

    reference_activity = last_activity_at or created_at
    if reference_activity:
        delta_hours = max((now - reference_activity).total_seconds() / 3600, 0)
        if delta_hours <= 6:
            score += 12
        elif delta_hours <= 24:
            score += 9
        elif delta_hours <= 72:
            score += 6
        elif delta_hours <= 168:
            score += 3
        elif delta_hours > 720:
            score -= 3

    if created_at and max((now - created_at).total_seconds(), 0) <= 86400:
        score += 3

    if status == "archivado":
        score = min(score, 0)

    if status == "archivado":
        label = "Archivado"
        slug = "archivado"
    elif score >= 52:
        label = "Alta"
        slug = "alta"
    elif score >= 32:
        label = "Media"
        slug = "media"
    else:
        label = "Baja"
        slug = "baja"
    return {"score": score, "label": label, "slug": slug}


def format_human_time_ago(dt: datetime | None) -> str:
    if not dt:
        return "-"
    now = utc_now()
    delta_seconds = int(max((now - dt).total_seconds(), 0))

    if delta_seconds < 60:
        return "Hace instantes"
    if delta_seconds < 3600:
        minutes = max(delta_seconds // 60, 1)
        return f"Hace {minutes} min"
    if delta_seconds < 86400:
        hours = max(delta_seconds // 3600, 1)
        return f"Hace {hours} h"
    if delta_seconds < 172800:
        return "Ayer"
    if delta_seconds < 604800:
        days = max(delta_seconds // 86400, 2)
        return f"Hace {days} días"
    return dt.strftime("%d/%m/%Y")


def build_lead_metrics_subquery(db: Session, empresa_id: int):
    return (
        db.query(
            models.CatalogLeadEvent.lead_id.label("lead_id"),
            func.sum(case((models.CatalogLeadEvent.event_type == "search_performed", 1), else_=0)).label("search_count"),
            func.sum(case((models.CatalogLeadEvent.event_type == "product_viewed", 1), else_=0)).label("product_view_count"),
            func.sum(case((models.CatalogLeadEvent.event_type == "cart_item_added", 1), else_=0)).label("cart_add_count"),
            func.max(case((models.CatalogLeadEvent.event_type == "whatsapp_clicked", 1), else_=0)).label("has_whatsapp_click"),
            func.max(case((models.CatalogLeadEvent.event_type == "pdf_downloaded", 1), else_=0)).label("has_pdf_download"),
            func.max(models.CatalogLeadEvent.created_at).label("last_event_at"),
        )
        .filter(models.CatalogLeadEvent.empresa_catalogo_id == empresa_id)
        .group_by(models.CatalogLeadEvent.lead_id)
        .subquery()
    )


def list_catalog_leads_for_admin(
    db: Session,
    empresa_id: int,
    search_query: str = "",
    whatsapp_filter: bool | None = None,
    pdf_filter: bool | None = None,
    cart_filter: bool | None = None,
    status_filter: str = "",
    interest_filter: str = "",
    include_archived: bool = False,
):
    metrics_sq = build_lead_metrics_subquery(db, empresa_id)
    query = (
        db.query(
            models.CatalogLead,
            metrics_sq.c.search_count,
            metrics_sq.c.product_view_count,
            metrics_sq.c.cart_add_count,
            metrics_sq.c.has_whatsapp_click,
            metrics_sq.c.has_pdf_download,
            metrics_sq.c.last_event_at,
        )
        .outerjoin(metrics_sq, metrics_sq.c.lead_id == models.CatalogLead.id)
        .filter(models.CatalogLead.empresa_catalogo_id == empresa_id)
        .filter(models.CatalogLead.deleted_at.is_(None))
    )

    q = clean_text(search_query, default="")
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            or_(
                models.CatalogLead.nombre.ilike(pattern),
                models.CatalogLead.empresa.ilike(pattern),
                models.CatalogLead.email.ilike(pattern),
                models.CatalogLead.telefono.ilike(pattern),
            )
        )

    if whatsapp_filter is True:
        query = query.filter(func.coalesce(metrics_sq.c.has_whatsapp_click, 0) > 0)
    if pdf_filter is True:
        query = query.filter(func.coalesce(metrics_sq.c.has_pdf_download, 0) > 0)
    if cart_filter is True:
        query = query.filter(func.coalesce(metrics_sq.c.cart_add_count, 0) > 0)

    normalized_status_filter = normalize_lead_status(status_filter) if status_filter else ""
    if normalized_status_filter:
        query = query.filter(models.CatalogLead.estado == normalized_status_filter)
    elif not include_archived:
        query = query.filter(models.CatalogLead.estado != "archivado")

    rows = (
        query
        .order_by(models.CatalogLead.id.desc())
        .all()
    )

    lead_rows = []
    for (
        lead,
        search_count,
        product_view_count,
        cart_add_count,
        has_whatsapp_click,
        has_pdf_download,
        last_event_at,
    ) in rows:
        interest = compute_lead_interest(
            search_count=int(search_count or 0),
            product_view_count=int(product_view_count or 0),
            cart_add_count=int(cart_add_count or 0),
            has_whatsapp_click=bool(has_whatsapp_click or 0),
            has_pdf_download=bool(has_pdf_download or 0),
        )
        if interest_filter and interest["slug"] != clean_text(interest_filter, default="").lower():
            continue

        last_activity_at = last_event_at or lead.ultima_actividad or lead.fecha_ingreso
        has_notes = bool(clean_text(lead.notas_internas, default=""))
        priority = get_lead_priority(
            lead_status=lead.estado or "nuevo",
            interest=interest,
            last_activity_at=last_activity_at,
            created_at=lead.fecha_ingreso,
            cart_add_count=int(cart_add_count or 0),
            has_whatsapp_click=bool(has_whatsapp_click or 0),
            has_pdf_download=bool(has_pdf_download or 0),
            has_notes=has_notes,
        )

        lead_rows.append(
            {
                "lead": lead,
                "search_count": int(search_count or 0),
                "product_view_count": int(product_view_count or 0),
                "cart_add_count": int(cart_add_count or 0),
                "has_whatsapp_click": bool(has_whatsapp_click or 0),
                "has_pdf_download": bool(has_pdf_download or 0),
                "last_event_at": last_event_at,
                "last_activity_at": last_activity_at,
                "last_activity_human": format_human_time_ago(last_activity_at),
                "interest": interest,
                "estado_label": LEAD_STATUS_LABELS.get(lead.estado or "nuevo", "Nuevo"),
                "priority": priority,
                "has_notes": has_notes,
                "is_recent": bool(lead.fecha_ingreso and (utc_now() - lead.fecha_ingreso).total_seconds() <= 172800),
            }
        )
    return sorted(
        lead_rows,
        key=lambda item: (
            1 if (item["lead"].estado or "nuevo") == "archivado" else 0,
            -int(item["priority"]["score"]),
            -(item["last_activity_at"].timestamp() if item["last_activity_at"] else 0),
            -int(item["lead"].id),
        ),
    )


def build_leads_kpis(rows: list[dict]) -> list[dict]:
    active_rows = [row for row in rows if (row["lead"].estado or "nuevo") != "archivado"]
    unmanaged = [row for row in active_rows if (row["lead"].estado or "nuevo") == "nuevo"]
    return [
        {
            "key": "nuevos",
            "label": "Leads nuevos",
            "value": len(unmanaged),
            "hint": "Estado Nuevo (no archivados)",
            "query": "lead_status=nuevo",
        },
        {
            "key": "calientes",
            "label": "Leads calientes",
            "value": sum(1 for row in active_rows if row["interest"]["slug"] == "caliente"),
            "hint": "Interés comercial alto",
            "query": "lead_interest=caliente",
        },
        {
            "key": "pedido",
            "label": "Con pedido",
            "value": sum(1 for row in active_rows if row["cart_add_count"] > 0),
            "hint": "Agregaron productos",
            "query": "lead_cart=1",
        },
        {
            "key": "whatsapp",
            "label": "Click en WhatsApp",
            "value": sum(1 for row in active_rows if row["has_whatsapp_click"]),
            "hint": "Intención de contacto",
            "query": "lead_whatsapp=1",
        },
        {
            "key": "pdf",
            "label": "Descarga de PDF",
            "value": sum(1 for row in active_rows if row["has_pdf_download"]),
            "hint": "Interés en propuesta",
            "query": "lead_pdf=1",
        },
        {
            "key": "sin_gestionar",
            "label": "Sin gestionar",
            "value": len(unmanaged),
            "hint": "Pendientes de primer contacto",
            "query": "lead_unmanaged=1",
        },
    ]


def get_lead_summary_from_events(events: list[models.CatalogLeadEvent]) -> dict:
    summary = {
        "search_count": 0,
        "product_view_count": 0,
        "cart_add_count": 0,
        "has_whatsapp_click": False,
        "has_pdf_download": False,
    }
    for event in events:
        if event.event_type == "search_performed":
            summary["search_count"] += 1
        elif event.event_type == "product_viewed":
            summary["product_view_count"] += 1
        elif event.event_type == "cart_item_added":
            summary["cart_add_count"] += 1
        elif event.event_type == "whatsapp_clicked":
            summary["has_whatsapp_click"] = True
        elif event.event_type == "pdf_downloaded":
            summary["has_pdf_download"] = True
    summary["interest"] = compute_lead_interest(
        search_count=summary["search_count"],
        product_view_count=summary["product_view_count"],
        cart_add_count=summary["cart_add_count"],
        has_whatsapp_click=summary["has_whatsapp_click"],
        has_pdf_download=summary["has_pdf_download"],
    )
    return summary


def build_lead_timeline_rows(events: list[models.CatalogLeadEvent]) -> list[dict]:
    rows = []
    for event in events:
        metadata = {}
        if event.metadata_json:
            try:
                parsed = json.loads(event.metadata_json)
                metadata = parsed if isinstance(parsed, dict) else {}
            except Exception:
                metadata = {}
        rows.append(
            {
                "id": event.id,
                "created_at": event.created_at,
                "event_type": event.event_type,
                "event_label": EVENT_TYPE_LABELS.get(event.event_type, event.event_type),
                "search_term": event.search_term,
                "product_code": event.product_code,
                "metadata": metadata,
                "metadata_summary": summarize_event_metadata(event.event_type, metadata),
            }
        )
    return rows


def summarize_event_metadata(event_type: str, metadata: dict) -> str:
    if not metadata:
        return ""
    if event_type == "search_performed":
        term = clean_text(metadata.get("term"), default="")
        if term:
            return f"Término buscado: {term}"
    if event_type == "product_viewed":
        origin = clean_text(metadata.get("origin"), default="")
        if origin:
            return f"Origen de vista: {origin}"
    if event_type == "cart_item_added":
        quantity = clean_text(metadata.get("quantity"), default="")
        if quantity:
            return f"Cantidad agregada: {quantity}"
    if event_type == "whatsapp_clicked":
        target = clean_text(metadata.get("target"), default="")
        if target:
            return f"Canal: {target}"
    return ""


def clean_text(value, default=""):
    if value is None or pd.isna(value):
        return default
    text = str(value).strip()
    if text.lower() == "nan":
        return default
    return text


def normalize_external_url(value):
    """Return a safe absolute http(s) URL for public external links."""
    text = clean_text(value, default="")
    if not text or text.startswith("@") or any(char.isspace() for char in text):
        return None
    candidate = text if re.match(r"^https?://", text, re.IGNORECASE) else f"https://{text}"
    try:
        parsed = urlparse(candidate)
    except Exception:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    hostname = parsed.hostname or ""
    if not hostname or "." not in hostname or hostname.startswith(".") or hostname.endswith("."):
        return None
    return candidate


def normalize_instagram_contact(value):
    text = clean_text(value, default="")
    if not text:
        return {"label": "", "url": None}
    url = normalize_external_url(text)
    if url:
        return {"label": text, "url": url}
    if text.startswith("@") and re.fullmatch(r"@[A-Za-z0-9._]{1,30}", text):
        return {"label": text, "url": f"https://instagram.com/{text[1:]}"}
    return {"label": text, "url": None}


def normalize_whatsapp_url(value):
    clean_number = re.sub(r"\D+", "", clean_text(value, default=""))
    return f"https://wa.me/{clean_number}" if clean_number else None


def clean_price(value, default=0.0):
    if value is None or pd.isna(value):
        return default
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except Exception:
        return default


def clean_stock(value, default=0):
    if value is None or pd.isna(value):
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def normalize_price_policy(value: str | None) -> str:
    policy = clean_text(value, default="automatico").lower()
    return policy if policy in PRICE_POLICY_VALUES else "automatico"


def normalize_stock_policy(value: str | None) -> str:
    policy = clean_text(value, default="mostrar").lower()
    return policy if policy in STOCK_POLICY_VALUES else "mostrar"


def normalize_theme(value: str | None) -> str:
    theme = clean_text(value, default="default").lower()
    return theme if theme in THEME_VALUES else "default"


def public_section_for_theme(value: str | None) -> str:
    theme = normalize_theme(value)
    if theme == "comida":
        return "gastronomia"
    if theme in {"gastronomia", "alojamiento", "servicios", "actividades"}:
        return theme
    return "default"


def theme_display_label(value: str | None) -> str:
    labels = {
        "gastronomia": "Gastronomía",
        "comida": "Gastronomía",
        "alojamiento": "Alojamientos",
        "servicios": "Compras y servicios",
        "actividades": "Actividades y comunidad",
        "default": "Otro / General",
        "autopartes": "Autopartes",
        "farmacia": "Farmacia",
        "ferreteria": "Ferretería",
        "petshop": "Pet shop",
    }
    return labels.get(normalize_theme(value), "Otro / General")


def has_valid_price(value) -> bool:
    if value is None:
        return False
    try:
        parsed = float(value)
        return math.isfinite(parsed) and parsed > 0
    except Exception:
        return False


def resolve_price_display(policy: str, precio) -> dict:
    price_ok = has_valid_price(precio)
    if policy == "consultar":
        return {"mostrar_numerico": False, "texto": "Consultar"}
    if policy == "automatico":
        if price_ok:
            return {"mostrar_numerico": True, "texto": f"${float(precio):,.2f}"}
        return {"mostrar_numerico": False, "texto": "Consultar"}
    if price_ok:
        return {"mostrar_numerico": True, "texto": f"${float(precio):,.2f}"}
    return {"mostrar_numerico": False, "texto": "Consultar"}


def resolve_stock_display(policy: str, stock_value) -> dict:
    stock_num = clean_stock(stock_value, default=0)
    if policy == "ocultar":
        return {"visible": False, "texto": "", "clase": ""}
    if policy == "automatico" and stock_num <= 0:
        return {"visible": False, "texto": "", "clase": ""}
    if stock_num <= 0:
        return {"visible": True, "texto": "Sin stock", "clase": "stock-gray"}
    if stock_num <= 15:
        return {"visible": True, "texto": "Stock bajo", "clase": "stock-red"}
    if stock_num <= 60:
        return {"visible": True, "texto": "Stock medio", "clase": "stock-yellow"}
    return {"visible": True, "texto": "Stock alto", "clase": "stock-green"}


def get_empresa_media_dir(slug: str, media_type: str) -> Path:
    safe_slug = re.sub(r"[^a-z0-9\-]", "-", (slug or "").strip().lower())
    safe_slug = re.sub(r"-+", "-", safe_slug).strip("-")
    return MEDIA_BASE_DIR / safe_slug / media_type


def build_media_url(slug: str, media_type: str, filename: str) -> str:
    safe_slug = re.sub(r"[^a-z0-9\-]", "-", (slug or "").strip().lower())
    safe_slug = re.sub(r"-+", "-", safe_slug).strip("-")
    safe_filename = Path(filename).name
    return f"{MEDIA_URL_PREFIX}/empresas/{safe_slug}/{media_type}/{safe_filename}"


def get_productos_media_dir(slug: str) -> Path:
    return get_empresa_media_dir(slug, PRODUCTOS_MEDIA_TYPE)


def sanitize_codigo_for_filename(codigo: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._\-]", "_", (codigo or "").strip())
    return safe or "producto"


def build_producto_media_url(slug: str, filename: str) -> str:
    return build_media_url(slug, PRODUCTOS_MEDIA_TYPE, filename)


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with open(source, "rb") as src, open(destination, "wb") as dst:
        shutil.copyfileobj(src, dst)


def resolve_producto_imagen_url(producto: models.Producto, empresa_slug: str, migrate_legacy: bool = True) -> str:
    productos_dir = get_productos_media_dir(empresa_slug)
    productos_dir.mkdir(parents=True, exist_ok=True)
    fallback_url = "/static/img/no-image.png"
    codigo_safe = sanitize_codigo_for_filename(producto.codigo)

    existing_name = ""
    if producto.imagen_url:
        existing_name = Path(producto.imagen_url).name
        if existing_name:
            current_path = productos_dir / existing_name
            if current_path.exists():
                return build_producto_media_url(empresa_slug, existing_name)

    for ext in ALLOWED_IMAGE_EXTENSIONS:
        candidate = productos_dir / f"{codigo_safe}{ext}"
        if candidate.exists():
            return build_producto_media_url(empresa_slug, candidate.name)

    legacy_dir = Path("app/static/empresas") / empresa_slug / "productos"
    if legacy_dir.exists():
        for ext in ALLOWED_IMAGE_EXTENSIONS:
            legacy_file = legacy_dir / f"{codigo_safe}{ext}"
            if legacy_file.exists():
                if migrate_legacy:
                    target_name = existing_name if existing_name else legacy_file.name
                    target_path = productos_dir / target_name
                    if not target_path.exists():
                        _copy_file(legacy_file, target_path)
                    return build_producto_media_url(empresa_slug, target_name)
                return f"/static/empresas/{empresa_slug}/productos/{legacy_file.name}"

    return fallback_url


def build_unique_slug(db: Session, base_slug: str) -> str:
    base_slug = (base_slug or "").strip().lower()
    base_slug = re.sub(r"[^a-z0-9\-]", "-", base_slug)
    base_slug = re.sub(r"-+", "-", base_slug).strip("-")
    if not base_slug:
        base_slug = "empresa"

    exists = db.query(models.Empresa).filter(models.Empresa.slug == base_slug).first()
    if not exists:
        return base_slug

    i = 2
    while True:
        candidate = f"{base_slug}-copia-{i}"
        exists = db.query(models.Empresa).filter(models.Empresa.slug == candidate).first()
        if not exists:
            return candidate
        i += 1


def _zip_safe_members(zip_ref: zipfile.ZipFile):
    for member in zip_ref.infolist():
        member_name = member.filename.replace("\\", "/")
        if member_name.endswith("/"):
            continue
        parts = [p for p in Path(member_name).parts if p not in ("", ".", "..")]
        if not parts:
            continue
        yield member, Path(*parts)


def _copy_zip_prefix(zip_ref: zipfile.ZipFile, prefix: str, target_dir: Path):
    normalized_prefix = prefix.rstrip("/") + "/"
    for member, safe_path in _zip_safe_members(zip_ref):
        safe_str = safe_path.as_posix()
        if not safe_str.startswith(normalized_prefix):
            continue
        relative_str = safe_str[len(normalized_prefix):]
        if not relative_str:
            continue
        destination = target_dir / Path(relative_str)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zip_ref.open(member, "r") as src, open(destination, "wb") as dst:
            shutil.copyfileobj(src, dst)


def safe_unique_filename(upload: UploadFile, prefix: str) -> str:
    ext = Path(upload.filename or "").suffix.lower()
    ext = re.sub(r"[^a-z0-9.]", "", ext)
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        ext = ".jpg"
    safe_prefix = re.sub(r"[^a-zA-Z0-9_-]", "-", (prefix or "archivo")).strip("-_") or "archivo"
    return f"{safe_prefix}-{uuid.uuid4().hex}{ext}"


def has_uploaded_file(upload: UploadFile | None) -> bool:
    return bool(upload and getattr(upload, "filename", None))


async def replace_empresa_media(empresa: models.Empresa, media_type: str, upload: UploadFile) -> str:
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return getattr(empresa, f"{media_type}_url", "") or ""
    target_dir = get_empresa_media_dir(empresa.slug, media_type)
    target_dir.mkdir(parents=True, exist_ok=True)

    for old_file in target_dir.iterdir():
        if old_file.is_file():
            old_file.unlink()

    filename = safe_unique_filename(upload, prefix=media_type)
    file_path = target_dir / filename
    with open(file_path, "wb") as f:
        f.write(await upload.read())

    return build_media_url(empresa.slug, media_type, filename)



def get_empresa_gallery_urls(empresa: models.Empresa | None) -> list[str]:
    if not empresa or not empresa.galeria_urls:
        return []
    try:
        data = json.loads(empresa.galeria_urls)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [clean_text(url, default="") for url in data if clean_text(url, default="")][:7]


def managed_gallery_file(empresa: models.Empresa, url: str) -> Path | None:
    """Resolve an app-managed gallery URL without trusting it as a filesystem path."""
    parsed = urlparse(clean_text(url, default=""))
    expected_prefix = f"{MEDIA_URL_PREFIX}/empresas/{empresa.slug}/galeria/"
    if parsed.scheme or parsed.netloc or not parsed.path.startswith(expected_prefix):
        return None
    relative_name = parsed.path.removeprefix(expected_prefix)
    if not relative_name or relative_name != Path(relative_name).name:
        return None
    gallery_dir = get_empresa_media_dir(empresa.slug, "galeria").resolve()
    candidate = (gallery_dir / relative_name).resolve()
    try:
        candidate.relative_to(gallery_dir)
        gallery_dir.relative_to(STORAGE_DIR)
    except ValueError:
        return None
    return candidate


async def append_empresa_gallery_images(empresa: models.Empresa, uploads: list[UploadFile]) -> tuple[list[str], str]:
    current = get_empresa_gallery_urls(empresa)
    available = max(0, 7 - len(current))
    if available <= 0:
        return current, "La galería ya tiene el máximo de 7 fotos."
    target_dir = get_empresa_media_dir(empresa.slug, "galeria")
    target_dir.mkdir(parents=True, exist_ok=True)
    added = 0
    skipped = 0
    for upload in uploads[:available]:
        if not upload or not upload.filename:
            continue
        ext = Path(upload.filename).suffix.lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            skipped += 1
            continue
        filename = safe_unique_filename(upload, prefix="foto")
        with open(target_dir / filename, "wb") as f:
            f.write(await upload.read())
        current.append(build_media_url(empresa.slug, "galeria", filename))
        added += 1
    empresa.galeria_urls = json.dumps(current[:7], ensure_ascii=False)
    if skipped and not added:
        return current, "Formato inválido. Usá JPG, JPEG, PNG o WEBP."
    if skipped:
        return current, f"Se agregaron {added} fotos. Algunas se omitieron por formato inválido."
    return current, f"Se agregaron {added} fotos a la galería." if added else "No se seleccionaron fotos nuevas."


def get_empresa_menu_photo_urls(empresa: models.Empresa | None) -> list[str]:
    if not empresa or not getattr(empresa, "menu_fotos_urls", None):
        return []
    try:
        data = json.loads(empresa.menu_fotos_urls)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [clean_text(url, default="") for url in data if clean_text(url, default="")][:6]


async def append_empresa_menu_images(empresa: models.Empresa, uploads: list[UploadFile]) -> tuple[list[str], str]:
    current = get_empresa_menu_photo_urls(empresa)
    available = max(0, 6 - len(current))
    if available <= 0:
        return current, "La sección Menú / carta ya tiene el máximo recomendado de 6 fotos."
    target_dir = get_empresa_media_dir(empresa.slug, "menu")
    target_dir.mkdir(parents=True, exist_ok=True)
    added = 0
    skipped = 0
    for upload in uploads[:available]:
        if not upload or not upload.filename:
            continue
        ext = Path(upload.filename).suffix.lower()
        if ext not in ALLOWED_MENU_IMAGE_EXTENSIONS:
            skipped += 1
            continue
        filename = safe_unique_filename(upload, prefix="menu")
        with open(target_dir / filename, "wb") as f:
            f.write(await upload.read())
        current.append(build_media_url(empresa.slug, "menu", filename))
        added += 1
    empresa.menu_fotos_urls = json.dumps(current[:6], ensure_ascii=False)
    if skipped and not added:
        return current, "Formato inválido. Usá JPG, JPEG, PNG o WEBP."
    if skipped:
        return current, f"Se agregaron {added} fotos de menú/carta. Algunas se omitieron por formato inválido."
    return current, f"Se agregaron {added} fotos de menú/carta." if added else "No se seleccionaron fotos nuevas de menú/carta."

def get_empresa_logo_url(empresa: models.Empresa | None) -> str:
    if not empresa:
        return ""
    if empresa.logo_url:
        return empresa.logo_url
    legacy = Path(f"app/static/empresas/{empresa.slug}/logo.png")
    if legacy.exists():
        return f"/static/empresas/{empresa.slug}/logo.png"
    return ""


def get_empresa_banner_url(empresa: models.Empresa | None) -> str:
    if not empresa:
        return ""
    if empresa.banner_url:
        return empresa.banner_url
    legacy = Path(f"app/static/empresas/{empresa.slug}/banner.jpg")
    if legacy.exists():
        return f"/static/empresas/{empresa.slug}/banner.jpg"
    return ""


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/", error: str = ""):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "next": next,
            "error": error,
        },
    )


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    username_clean = clean_text(username, default="").lower()
    user = db.query(models.Usuario).filter(models.Usuario.username == username_clean, models.Usuario.activo == True).first()
    if not user or not verify_password(password, user.password_hash):
        return RedirectResponse(url=f"/login?next={quote(next or '/admin')}&error=Credenciales inválidas", status_code=303)

    request.session.clear()
    request.session["user_id"] = user.id
    request.session["role"] = user.rol
    request.session["empresa_id"] = user.empresa_id

    if next and next not in {"/", "/login"}:
        return RedirectResponse(url=next, status_code=303)
    return RedirectResponse(url=get_dashboard_path(user), status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/admin/login")
def admin_login_compat():
    return RedirectResponse(url="/login", status_code=303)


@app.get("/admin/logout")
def admin_logout_compat():
    return RedirectResponse(url="/logout", status_code=303)


@app.get("/_build")
@app.get("/build")
@app.get("/__build")
def build_info():
    return {
        "build": APP_BUILD,
        "render_git_commit": os.getenv("RENDER_GIT_COMMIT", ""),
        "render_service_id": os.getenv("RENDER_SERVICE_ID", ""),
    }


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "build": APP_BUILD,
    }


@app.get("/healthz/{tail:path}")
@app.get("/healthz{tail:path}")
def healthz_fallback(tail: str):
    """
    Fallback útil para URLs mal pegadas, por ejemplo:
    /healthzhttps://.../_build
    """
    tail = tail or ""
    if "build" in tail.lower():
        return RedirectResponse(url="/_build", status_code=307)
    return JSONResponse(
        {
            "ok": True,
            "build": APP_BUILD,
            "note": "Ruta inválida detectada. Probá /healthz o /_build.",
            "tail": tail,
        }
    )


@app.get("/empresa/activar/{slug}")
def activar_empresa(slug: str, request: Request, db: Session = Depends(get_db)):
    """
    Endpoint de compatibilidad:
    redirecciona el panel al contexto de empresa indicado por query string.
    """
    empresa = get_empresa_by_slug(db, slug)
    if not empresa:
        return {"error": "Empresa no encontrada", "slug": slug}

    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return RedirectResponse(url=f"{get_dashboard_path(user)}?empresa={quote(empresa.slug)}", status_code=303)


@app.get("/empresa/activa")
def ver_empresa_activa(
    slug: str | None = Query(default=None),
    db: Session = Depends(get_db)
):
    """
    Devuelve qué empresa está activa ahora.
    """
    empresa = get_empresa_by_slug(db, slug) or get_default_empresa(db)
    if not empresa:
        return {"empresa_activa": None}
    return {"empresa_activa": {"id": empresa.id, "slug": empresa.slug, "nombre": empresa.nombre}}

@app.post("/empresa/actualizar_imagenes")
async def actualizar_imagenes_empresa(
    request: Request,
    empresa_slug: str = Form(...),
    logo: UploadFile = File(None),
    banner: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    auth = require_admin(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    empresa = get_empresa_by_slug(db, empresa_slug)
    if not empresa:
        return panel_redirect(error="Empresa inválida")

    if has_uploaded_file(logo):
        empresa.logo_url = await replace_empresa_media(empresa, media_type="logo", upload=logo)

    if has_uploaded_file(banner):
        empresa.banner_url = await replace_empresa_media(empresa, media_type="banner", upload=banner)

    db.add(empresa)
    db.commit()

    return panel_redirect(empresa_slug=empresa.slug, area="prestador", tab="fotos", msg="Imágenes actualizadas")


@app.post("/empresa/activar_panel")
def activar_empresa_panel(
    request: Request,
    slug: str = Form(...),
    admin_tab: str = Form("prestadores"),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    if isinstance(user, RedirectResponse):
        return user

    if user.rol != "admin":
        return redirect_for_user(user, error="No tenés permisos para cambiar de empresa")

    empresa = get_empresa_by_slug(db, slug)

    if not empresa:
        return redirect_for_user(user, error="Empresa no encontrada")

    return panel_redirect(empresa_slug=empresa.slug, area="prestador", tab=normalize_admin_tab(admin_tab, "prestador"))


@app.post("/empresa/editar_panel")
def editar_empresa_panel(
    request: Request,
    empresa_slug_actual: str = Form(...),
    nombre: str = Form(...),
    admin_tab: str = Form("prestadores"),
    whatsapp: str | None = Form(None),
    telefono: str | None = Form(None),
    instagram: str | None = Form(None),
    facebook: str | None = Form(None),
    web_url: str | None = Form(None),
    direccion: str | None = Form(None),
    maps_url: str | None = Form(None),
    descripcion: str | None = Form(None),
    descripcion_corta: str | None = Form(None),
    subtipo: str | None = Form(None),
    horarios: str | None = Form(None),
    precio_desde: str | None = Form(None),
    capacidad: str | None = Form(None),
    habitaciones: str | None = Form(None),
    banos: str | None = Form(None),
    video_url: str | None = Form(None),
    menu_url: str | None = Form(None),
    promocion: str | None = Form(None),
    guardia: str | None = Form(None),
    fecha: str | None = Form(None),
    organizador: str | None = Form(None),
    lugar_encuentro: str | None = Form(None),
    delivery: str | None = Form(None),
    take_away: str | None = Form(None),
    comer_en_lugar: str | None = Form(None),
    pileta: str | None = Form(None),
    rio: str | None = Form(None),
    mascotas: str | None = Form(None),
    cochera: str | None = Form(None),
    wifi: str | None = Form(None),
    parrilla: str | None = Form(None),
    aire_acondicionado: str | None = Form(None),
    calefaccion: str | None = Form(None),
    subgrupo: str | None = Form(None),
    destacado: str | None = Form(None),
    activo: str = Form("1"),
    theme: str = Form("default"),
    editar_slug: str = Form("0"),
    nuevo_slug: str = Form(""),
    db: Session = Depends(get_db),
):
    auth = require_admin(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    empresa = get_empresa_by_slug(db, empresa_slug_actual)
    if not empresa:
        return panel_redirect(error="Empresa no encontrada.")

    nombre_limpio = clean_text(nombre, default="")
    whatsapp_limpio = clean_text(whatsapp, default="") or None
    if not nombre_limpio:
        return panel_redirect(empresa_slug=empresa.slug, error="El nombre de la empresa no puede estar vacío.")

    slug_original = empresa.slug
    slug_final = slug_original

    if editar_slug == "1":
        nuevo_slug_limpio = clean_text(nuevo_slug, default="").lower()
        nuevo_slug_limpio = re.sub(r"[^a-z0-9\-]", "-", nuevo_slug_limpio)
        nuevo_slug_limpio = re.sub(r"-+", "-", nuevo_slug_limpio).strip("-")

        if not nuevo_slug_limpio:
            return panel_redirect(empresa_slug=slug_original, error="Slug inválido.")

        if nuevo_slug_limpio != slug_original:
            existe = db.query(models.Empresa).filter(models.Empresa.slug == nuevo_slug_limpio).first()
            if existe:
                return panel_redirect(empresa_slug=slug_original, error="Ese slug ya existe.")
            slug_final = nuevo_slug_limpio

    empresa.nombre = nombre_limpio
    optional_text_fields = {
        "whatsapp": whatsapp_limpio,
        "telefono": telefono,
        "instagram": instagram,
        "facebook": normalize_external_url(facebook) or facebook,
        "web_url": normalize_external_url(web_url),
        "direccion": direccion,
        "maps_url": normalize_external_url(maps_url) or maps_url,
        "descripcion": descripcion,
        "descripcion_corta": descripcion_corta,
        "subtipo": subtipo,
        "horarios": horarios,
        "precio_desde": precio_desde,
        "capacidad": capacidad,
        "habitaciones": habitaciones,
        "banos": banos,
        "video_url": video_url,
        "menu_url": normalize_external_url(menu_url),
        "promocion": promocion,
        "guardia": guardia,
        "fecha": fecha,
        "organizador": organizador,
        "lugar_encuentro": lugar_encuentro,
    }
    for attr, raw_value in optional_text_fields.items():
        if raw_value is not None:
            setattr(empresa, attr, clean_text(raw_value, default="") or None)
    if subgrupo is not None or normalize_theme(theme) == "servicios":
        effective_subtype = subtipo if subtipo is not None else empresa.subtipo
        empresa.subgrupo = normalize_service_group_subtype(subgrupo, effective_subtype, theme)
    if destacado is not None:
        empresa.destacado = str(destacado) == "1"
    if activo is not None:
        empresa.activo = str(activo) == "1"
    for attr, raw_value in {
        "delivery": delivery, "take_away": take_away, "comer_en_lugar": comer_en_lugar,
        "pileta": pileta, "rio": rio, "mascotas": mascotas, "cochera": cochera, "wifi": wifi,
        "parrilla": parrilla, "aire_acondicionado": aire_acondicionado, "calefaccion": calefaccion,
    }.items():
        if raw_value is not None:
            setattr(empresa, attr, str(raw_value) == "1")
    empresa.theme = normalize_theme(theme)

    if slug_final != slug_original:
        old_static_dir = Path("app/static/empresas") / slug_original
        new_static_dir = Path("app/static/empresas") / slug_final
        if old_static_dir.exists():
            if new_static_dir.exists():
                shutil.rmtree(new_static_dir)
            old_static_dir.rename(new_static_dir)

        old_storage_dir = MEDIA_BASE_DIR / slug_original
        new_storage_dir = MEDIA_BASE_DIR / slug_final
        if old_storage_dir.exists():
            if new_storage_dir.exists():
                shutil.rmtree(new_storage_dir)
            old_storage_dir.rename(new_storage_dir)

        if empresa.logo_url:
            empresa.logo_url = empresa.logo_url.replace(f"/empresas/{slug_original}/", f"/empresas/{slug_final}/")
        if empresa.banner_url:
            empresa.banner_url = empresa.banner_url.replace(f"/empresas/{slug_original}/", f"/empresas/{slug_final}/")

        productos = db.query(models.Producto).filter(models.Producto.empresa_id == empresa.id).all()
        for p in productos:
            if p.imagen_url:
                p.imagen_url = p.imagen_url.replace(f"/empresas/{slug_original}/", f"/empresas/{slug_final}/")

        empresa.slug = slug_final

    db.add(empresa)
    db.commit()

    return panel_redirect(empresa_slug=empresa.slug, area="prestador", tab=normalize_admin_tab(admin_tab, "prestador"), msg="Empresa actualizada correctamente.")



@app.post("/admin/opiniones/{review_id}/moderar")
def moderar_opinion_admin(
    review_id: int,
    request: Request,
    accion: str = Form(...),
    db: Session = Depends(get_db),
):
    auth = require_admin(request, db)
    if isinstance(auth, RedirectResponse):
        return auth
    review = db.query(models.Review).filter(models.Review.id == review_id).first()
    if not review:
        return panel_redirect(active_tab="opiniones", error="Opinión no encontrada.")
    if accion == "aprobar":
        review.estado = "aprobada"
        review.visible = True
    else:
        review.estado = "rechazada"
        review.visible = False
    db.add(review)
    db.commit()
    return panel_redirect(active_tab="opiniones", msg="Opinión moderada correctamente.")

@app.post("/empresa/politicas_catalogo")
def actualizar_politicas_catalogo(
    request: Request,
    empresa_slug: str = Form(...),
    politica_precio_catalogo: str = Form("automatico"),
    politica_stock_catalogo: str = Form("mostrar"),
    db: Session = Depends(get_db),
):
    auth = require_admin(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    empresa = get_empresa_by_slug(db, empresa_slug)
    if not empresa:
        return panel_redirect(error="Empresa no encontrada.")

    empresa.politica_precio_catalogo = normalize_price_policy(politica_precio_catalogo)
    empresa.politica_stock_catalogo = normalize_stock_policy(politica_stock_catalogo)
    db.add(empresa)
    db.commit()
    return panel_redirect(empresa_slug=empresa.slug, msg="Configuración de visualización actualizada.")

@app.get("/admin/productos", response_class=HTMLResponse)
@app.get("/cliente/productos", response_class=HTMLResponse)
def admin_productos(
    request: Request,
    empresa: str | None = Query(default=None),
    q: str = Query(default=""),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    if isinstance(user, RedirectResponse):
        return user

    empresa = can_access_empresa(user, empresa, db)
    if not empresa:
        return HTMLResponse("<h1>No hay empresa activa</h1>", status_code=400)

    query_db = db.query(models.Producto).filter(models.Producto.empresa_id == empresa.id)
    if q:
        q_like = f"%{q.strip()}%"
        query_db = query_db.filter(
            (models.Producto.codigo.ilike(q_like)) |
            (models.Producto.descripcion.ilike(q_like))
        )

    productos = query_db.order_by(models.Producto.codigo).all()

    return templates.TemplateResponse(
        "admin_productos.html",
        {
            "request": request,
            "empresa": empresa,
            "productos": productos,
            "query": q,
            "is_admin": user.rol == "admin",
        },
    )


@app.get("/admin/productos/{producto_id}/editar", response_class=HTMLResponse)
@app.get("/cliente/productos/{producto_id}/editar", response_class=HTMLResponse)
def editar_producto_view(
    request: Request,
    producto_id: int,
    empresa: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    if isinstance(user, RedirectResponse):
        return user

    producto = (
        db.query(models.Producto)
        .filter(models.Producto.id == producto_id)
        .first()
    )
    if not producto:
        return RedirectResponse(url="/cliente/productos", status_code=303)

    if user.rol == "cliente" and user.empresa_id != producto.empresa_id:
        return RedirectResponse(url="/cliente?error=No autorizado para editar este producto", status_code=303)

    empresa_ctx = get_empresa_by_slug(db, empresa) if empresa else producto.empresa
    if not empresa_ctx:
        empresa_ctx = producto.empresa

    return templates.TemplateResponse(
        "admin_producto_editar.html",
        {
            "request": request,
            "producto": producto,
            "empresa": empresa_ctx,
            "is_admin": user.rol == "admin",
        },
    )


@app.post("/admin/productos/{producto_id}/actualizar")
@app.post("/cliente/productos/{producto_id}/actualizar")
async def actualizar_producto(
    request: Request,
    producto_id: int,
    empresa_slug: str = Form(""),
    codigo: str = Form(...),
    descripcion: str = Form(...),
    categoria: str = Form(""),
    marca: str = Form(""),
    stock: int = Form(0),
    precio: float = Form(...),
    activo: bool = Form(False),
    imagen: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    if isinstance(user, RedirectResponse):
        return user

    producto = db.query(models.Producto).filter(models.Producto.id == producto_id).first()
    if not producto:
        return RedirectResponse(url="/cliente/productos", status_code=303)
    if user.rol == "cliente" and user.empresa_id != producto.empresa_id:
        return RedirectResponse(url="/cliente?error=No autorizado para editar este producto", status_code=303)

    producto.codigo = clean_text(codigo, default=producto.codigo) or producto.codigo
    producto.descripcion = descripcion
    producto.categoria = clean_text(categoria, default="") or None
    producto.marca = clean_text(marca, default="") or None
    producto.stock = stock
    producto.precio = precio
    producto.activo = activo

    # actualizar imagen individual
    if has_uploaded_file(imagen) and Path(imagen.filename).suffix.lower() in ALLOWED_IMAGE_EXTENSIONS:
        empresa = producto.empresa
        img_path = get_productos_media_dir(empresa.slug)
        img_path.mkdir(parents=True, exist_ok=True)
        codigo_safe = sanitize_codigo_for_filename(producto.codigo)

        # borrar imágenes viejas
        for ext in ALLOWED_IMAGE_EXTENSIONS:
            old = img_path / f"{codigo_safe}{ext}"
            if old.exists():
                old.unlink()

        # guardar nueva imagen
        ext = Path(imagen.filename).suffix.lower()
        filename = f"{codigo_safe}{ext}"

        with open(img_path / filename, "wb") as f:
            f.write(await imagen.read())

        producto.imagen_url = build_producto_media_url(empresa.slug, filename)

    db.commit()
    target_empresa = empresa_slug or (producto.empresa.slug if producto.empresa else "")
    products_path = "/admin/productos" if user.rol == "admin" else "/cliente/productos"
    redirect_target = f"{products_path}?empresa={quote(target_empresa)}" if target_empresa else products_path
    return RedirectResponse(url=redirect_target, status_code=303)

@app.get("/admin/borrar_empresa/{empresa_id}")
def borrar_empresa_get(request: Request, empresa_id: int, db: Session = Depends(get_db)):
    auth = require_admin(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    empresa = db.query(models.Empresa).filter(models.Empresa.id == empresa_id).first()
    if not empresa:
        return HTMLResponse("<h1>Empresa no encontrada</h1>", status_code=404)

    slug = empresa.slug

    # borrar de DB
    db.delete(empresa)
    db.commit()

    # borrar carpeta estática
    path = Path(f"app/static/empresas/{slug}")
    if path.exists():
        shutil.rmtree(path)
    media_path = MEDIA_BASE_DIR / slug
    if media_path.exists():
        shutil.rmtree(media_path)

    return HTMLResponse(
        f"<h1>Empresa {slug} eliminada correctamente</h1>"
    )


    


# ---------------------------------------------------
# HOME / DASHBOARDS
# ---------------------------------------------------
def get_public_empresas_by_themes(db: Session, themes: set[str]):
    normalized_themes = {normalize_theme(theme) for theme in themes}
    return (
        db.query(models.Empresa)
        .filter(
            func.lower(models.Empresa.theme).in_(normalized_themes),
            or_(models.Empresa.activo == True, models.Empresa.activo.is_(None)),
        )
        .order_by(models.Empresa.nombre.asc())
        .all()
    )


ACTIVIDADES_SUBGRUPOS = {
    "diurnas": {
        "label": "Actividades diurnas",
        "description": "Caminatas, paseos, recorridos, actividades recreativas y propuestas para disfrutar durante el día.",
        "icon": "☀️",
    },
    "nocturnas": {
        "label": "Actividades nocturnas",
        "description": "Peñas, música en vivo, encuentros, propuestas culturales y actividades para la noche.",
        "icon": "🌙",
    },
    "locales": {
        "label": "Productos locales y artesanos",
        "description": "Artesanos, emprendedores, productores regionales y propuestas locales de Cabalango.",
        "icon": "🧺",
    },
}

SERVICIOS_GRUPOS = {
    "compras": "Almacenes y kioscos",
    "transporte": "Transporte",
    "estacionamiento": "Estacionamiento",
    "salud": "Salud y bienestar",
    "otros": "Otros servicios",
}

SERVICIOS_SUBTIPOS = {
    "proveeduria": ("compras", "Proveeduría"),
    "almacen": ("compras", "Almacén"),
    "minimercado": ("compras", "Minimercado"),
    "kiosco": ("compras", "Kiosco"),
    "regionales": ("compras", "Productos regionales"),
    "fraccionamiento de productos secos": ("compras", "Fraccionamiento de productos secos"),
    "remis": ("transporte", "Remis"),
    "transporte": ("transporte", "Transporte"),
    "playa de estacionamiento": ("estacionamiento", "Playa de estacionamiento"),
    "estacionamiento": ("estacionamiento", "Estacionamiento"),
    "kinesiologia": ("salud", "Kinesiología"),
    "centro de salud": ("salud", "Centro de salud"),
    "farmacia": ("salud", "Farmacia"),
    "lavadero": ("otros", "Lavadero"),
    "lavadero de ropa": ("otros", "Lavadero de ropa"),
}


def service_group_for_subtype(value: str | None) -> str | None:
    subtype = SERVICIOS_SUBTIPOS.get(normalize_taxonomy_key(value))
    return subtype[0] if subtype else None


def normalize_taxonomy_key(value: str | None) -> str:
    value = clean_text(value, default="").lower().replace("_", "-")
    value = "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value).strip().replace("-", " ")


def service_group_key(empresa: models.Empresa) -> str:
    """Read-only compatibility mapping; it never rewrites historical rows."""
    group = normalize_taxonomy_key(empresa.subgrupo)
    aliases = {"salud y bienestar": "salud", "otros servicios": "otros", "comercios": "compras"}
    group = aliases.get(group, group)
    if group in SERVICIOS_GRUPOS:
        return group
    inferred_group = service_group_for_subtype(empresa.subtipo)
    if inferred_group:
        return inferred_group
    return "otros"


def service_card_kicker(empresa: models.Empresa) -> str:
    group = service_group_key(empresa)
    group_label = SERVICIOS_GRUPOS[group]
    subtype_key = normalize_taxonomy_key(empresa.subtipo)
    subtype_label = SERVICIOS_SUBTIPOS.get(subtype_key, (group, clean_text(empresa.subtipo, default="")))[1]
    if not subtype_label or normalize_taxonomy_key(subtype_label) == normalize_taxonomy_key(group_label):
        return group_label
    return f"{group_label} · {subtype_label}"


def normalize_subgrupo_for_theme(value: str | None, theme: str | None) -> str | None:
    if normalize_theme(theme) == "servicios":
        key = normalize_taxonomy_key(value)
        aliases = {"salud y bienestar": "salud", "otros servicios": "otros"}
        key = aliases.get(key, key)
        return key if key in SERVICIOS_GRUPOS else None
    return normalize_actividad_subgrupo(value)


def normalize_service_group_subtype(
    group: str | None, subtype: str | None, theme: str | None
) -> str | None:
    """Known service rubrics own their group; free-form rubrics keep a valid choice."""
    if normalize_theme(theme) == "servicios":
        return service_group_for_subtype(subtype) or normalize_subgrupo_for_theme(group, theme)
    return normalize_subgrupo_for_theme(group, theme)


def normalize_actividad_subgrupo(value: str | None) -> str | None:
    cleaned = clean_text(value, default="").lower()
    return cleaned if cleaned in ACTIVIDADES_SUBGRUPOS else None


def get_public_card_main_image(empresa: models.Empresa | None) -> str:
    """Priority for tourism cards: real place photos first, logo never as main image.

    Return an empty string when there is no real visual asset so public templates can
    render the editorial Cabalango placeholder instead of the legacy product image.
    """
    if not empresa:
        return ""
    gallery = get_empresa_gallery_urls(empresa)
    if gallery:
        return gallery[0]
    return get_empresa_banner_url(empresa) or ""


def alojamiento_initials(nombre: str | None) -> str:
    words = [word for word in re.split(r"\s+", clean_text(nombre, default="")) if word]
    if not words:
        return "🏡"
    return "".join(word[0].upper() for word in words[:3])


def parse_public_number(value) -> int | None:
    text_value = clean_text(value, default="")
    if not text_value:
        return None
    match = re.search(r"\d+", text_value.replace(".", ""))
    return int(match.group(0)) if match else None


def parse_public_price(value) -> int | None:
    text_value = clean_text(value, default="")
    if not text_value:
        return None
    digits = re.sub(r"\D", "", text_value)
    return int(digits) if digits else None


def alojamiento_fact_label(value, singular: str, plural: str) -> str:
    clean_value = clean_text(value, default="")
    if not clean_value:
        return ""
    number = parse_public_number(clean_value)
    label = singular if number == 1 else plural
    if re.fullmatch(r"\d+", clean_value):
        return f"{clean_value} {label}"
    return clean_value if singular in clean_value.lower() or plural in clean_value.lower() else f"{clean_value} {label}"


def build_alojamiento_key_facts(empresa: models.Empresa) -> list[str]:
    facts = []
    for value, singular, plural in [
        (empresa.capacidad, "persona", "personas"),
        (empresa.habitaciones, "habitación", "habitaciones"),
        (empresa.banos, "baño", "baños"),
    ]:
        label = alojamiento_fact_label(value, singular, plural)
        if label:
            facts.append(label)
    return facts


def build_public_card_chips(empresa: models.Empresa, section: str) -> list[str]:
    chips: list[str] = []
    kind = "alojamiento" if section == "alojamientos" else get_prestador_kind(empresa)
    if kind == "alojamiento":
        for attr, label in [("pileta", "Pileta"), ("rio", "Cerca del río"), ("mascotas", "Mascotas"), ("cochera", "Cochera"), ("wifi", "WiFi"), ("parrilla", "Parrilla")]:
            if getattr(empresa, attr, None) is True:
                chips.append(label)
    elif kind == "gastronomia":
        for attr, label in [("delivery", "Delivery"), ("take_away", "Take away"), ("comer_en_lugar", "Comer en el lugar")]:
            if getattr(empresa, attr, None) is True:
                chips.append(label)
        if clean_text(empresa.subtipo, default=""):
            chips.append(empresa.subtipo)
    else:
        for value in [empresa.subtipo, empresa.horarios, empresa.precio_desde]:
            clean_value = clean_text(value, default="")
            if clean_value:
                chips.append(clean_value)
    return chips[:6]


ALOJAMIENTO_FILTER_AMENITIES = [
    ("pileta", "Pileta"),
    ("rio", "Frente/cerca del río"),
    ("mascotas", "Acepta mascotas"),
    ("cochera", "Cochera"),
    ("wifi", "WiFi"),
    ("parrilla", "Parrilla"),
]


def get_alojamiento_filters(request: Request) -> dict:
    params = request.query_params
    filters = {
        "tipo": params.get("tipo", "todos"),
        "capacidad": params.get("capacidad", ""),
        "habitaciones": params.get("habitaciones", ""),
        "precio_max": params.get("precio_max", ""),
        "orden": params.get("orden", "destacados"),
    }
    for key, _label in ALOJAMIENTO_FILTER_AMENITIES:
        filters[key] = params.get(key, "")
    return filters


def filter_alojamientos(empresas: list[models.Empresa], filters: dict) -> list[models.Empresa]:
    results = list(empresas)
    tipo = clean_text(filters.get("tipo"), default="todos").lower()
    if tipo and tipo != "todos":
        results = [e for e in results if tipo in clean_text(e.subtipo or e.theme, default="").lower()]
    capacidad_min = parse_public_number(filters.get("capacidad"))
    if capacidad_min:
        results = [e for e in results if (parse_public_number(e.capacidad) or 0) >= capacidad_min]
    habitaciones_min = parse_public_number(filters.get("habitaciones"))
    if habitaciones_min:
        results = [e for e in results if (parse_public_number(e.habitaciones) or 0) >= habitaciones_min]
    precio_filter = clean_text(filters.get("precio_max"), default="")
    precio_max = parse_public_number(precio_filter)
    if precio_filter == "mas_100000":
        results = [e for e in results if parse_public_price(e.precio_desde) is not None and parse_public_price(e.precio_desde) > 100000]
    elif precio_max:
        results = [e for e in results if parse_public_price(e.precio_desde) is not None and parse_public_price(e.precio_desde) <= precio_max]
    for key, _label in ALOJAMIENTO_FILTER_AMENITIES:
        if filters.get(key) == "1":
            results = [e for e in results if getattr(e, key, None) is True]
    orden = filters.get("orden")
    if orden == "precio_asc":
        results.sort(key=lambda e: parse_public_price(e.precio_desde) if parse_public_price(e.precio_desde) is not None else 10**12)
    elif orden == "precio_desc":
        results.sort(key=lambda e: parse_public_price(e.precio_desde) or -1, reverse=True)
    elif orden == "capacidad_desc":
        results.sort(key=lambda e: parse_public_number(e.capacidad) or -1, reverse=True)
    else:
        results.sort(key=lambda e: (not bool(e.destacado), e.nombre.lower()))
    return results


def portal_section_context(request: Request, db: Session, *, title: str, eyebrow: str, description: str, themes: set[str], section: str, subgrupo: str | None = None):
    empresas = get_public_empresas_by_themes(db, themes)
    alojamiento_filters = get_alojamiento_filters(request) if section == "alojamientos" else {}
    if section == "alojamientos":
        empresas = filter_alojamientos(empresas, alojamiento_filters)
    if section == "actividades" and subgrupo:
        empresas = [empresa for empresa in empresas if (empresa.subgrupo or "").lower() == subgrupo]
    active_service_group = ""
    if section == "servicios":
        requested_group = normalize_taxonomy_key(request.query_params.get("grupo"))
        active_service_group = requested_group if requested_group in SERVICIOS_GRUPOS else ""
        if active_service_group:
            empresas = [empresa for empresa in empresas if service_group_key(empresa) == active_service_group]
    return templates.TemplateResponse(
        "portal_prestadores.html",
        {
            "request": request,
            "title": title,
            "eyebrow": eyebrow,
            "description": description,
            "empresas": empresas,
            "section": section,
            "theme_display_label": theme_display_label,
            "actividad_subgrupos": ACTIVIDADES_SUBGRUPOS if section == "actividades" else {},
            "active_subgrupo": subgrupo if section == "actividades" else None,
            "service_groups": SERVICIOS_GRUPOS if section == "servicios" else {},
            "active_service_group": active_service_group,
            "service_card_kicker": service_card_kicker,
            "get_public_card_main_image": get_public_card_main_image,
            "get_empresa_logo_url": get_empresa_logo_url,
            "build_public_card_chips": build_public_card_chips,
            "build_alojamiento_key_facts": build_alojamiento_key_facts,
            "alojamiento_initials": alojamiento_initials,
            "alojamiento_filters": alojamiento_filters,
            "alojamiento_amenities": ALOJAMIENTO_FILTER_AMENITIES,
        },
    )


def render_destino_home(request: Request, db: Session):
    content = get_destino_content(db)
    fotos = get_public_destino_media(db, "foto")
    videos = get_public_destino_media(db, "video")
    return templates.TemplateResponse(
        "descubri_cabalango.html",
        {
            "request": request,
            "fotos": fotos,
            "videos": videos,
            "categories": DESTINO_MEDIA_CATEGORIES,
            "category_descriptions": DESTINO_MEDIA_CATEGORY_DESCRIPTIONS,
            "content": content,
            "weather": get_cabalango_weather(),
            "active_section": "inicio",
            "agenda_home": build_home_agenda(db),
        },
    )


@app.get("/", response_class=HTMLResponse)
def portal_home(request: Request, db: Session = Depends(get_db)):
    return render_destino_home(request, db)


@app.get("/gastronomia", response_class=HTMLResponse)
def portal_gastronomia(request: Request, db: Session = Depends(get_db)):
    return portal_section_context(
        request,
        db,
        title="Gastronomía en Cabalango",
        eyebrow="Dónde comer",
        description="Sabores locales, casas de comida, bares, restaurantes y opciones para disfrutar en Cabalango.",
        themes={"gastronomia", "comida"},
        section="gastronomia",
    )


@app.get("/alojamientos", response_class=HTMLResponse)
def portal_alojamientos(request: Request, db: Session = Depends(get_db)):
    return portal_section_context(
        request,
        db,
        title="Alojamientos en Cabalango",
        eyebrow="Dónde dormir",
        description="Hoteles, cabañas, casas y hospedajes para planificar tu estadía.",
        themes={"alojamiento"},
        section="alojamientos",
    )


@app.get("/servicios", response_class=HTMLResponse)
def portal_servicios(request: Request, db: Session = Depends(get_db)):
    return portal_section_context(
        request,
        db,
        title="Compras y servicios",
        eyebrow="PARA VECINOS Y VISITANTES",
        description="Todo lo que podés necesitar durante tu estadía: compras, transporte, salud y servicios locales.",
        themes={"servicios"},
        section="servicios",
    )


@app.get("/actividades", response_class=HTMLResponse)
def portal_actividades(request: Request, momento: str = "", categoria: str = "", cuando: str = "", db: Session = Depends(get_db)):
    items = get_public_activities(db, categoria=categoria, momento=momento, cuando=cuando)
    return templates.TemplateResponse("actividades.html", {"request": request, "groups": group_public_agenda(items), "categories": CATEGORIES, "moments": MOMENTS, "filters": {"momento": momento, "categoria": categoria, "cuando": cuando}, "active_section": "actividades"})


@app.get("/actividades/{slug}", response_class=HTMLResponse)
def actividad_detail(request: Request, slug: str, db: Session = Depends(get_db)):
    item = next((i for i in get_public_activities(db) if i.slug == slug), None)
    if not item:
        raise HTTPException(status_code=404, detail="Actividad no encontrada")
    return templates.TemplateResponse("actividad_detalle.html", {"request": request, "item": item, "categories": CATEGORIES, "moments": MOMENTS, "active_section": "actividades"})


def build_home_agenda(db: Session):
    groups = group_public_agenda(get_public_activities(db))
    selected = (groups["today"] + groups["night"])[:4]
    if len(selected) < 4:
        selected += [i for i in groups["activities"] if i.destacado][:4-len(selected)]
    return selected


def parse_local_form_datetime(value: str):
    value = clean_text(value, default="")
    return datetime.fromisoformat(value) if value else None


def unique_agenda_slug(db: Session, title: str, exclude_id=None):
    base = re.sub(r"[^a-z0-9]+", "-", title.lower().translate(str.maketrans("áéíóúñ", "aeioun"))).strip("-") or "actividad"
    slug, suffix = base, 2
    while db.query(models.ActividadAgenda).filter(models.ActividadAgenda.slug == slug, models.ActividadAgenda.id != exclude_id).first():
        slug, suffix = f"{base}-{suffix}", suffix + 1
    return slug


async def save_agenda_image(upload: UploadFile, slug: str):
    if Path(upload.filename or "").suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Formato de imagen inválido")
    target = STORAGE_DIR / "actividades" / slug
    target.mkdir(parents=True, exist_ok=True)
    filename = safe_unique_filename(upload, prefix="principal")
    data = await upload.read()
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("La imagen supera el máximo de 8 MB")
    (target / filename).write_bytes(data)
    return f"{MEDIA_URL_PREFIX}/actividades/{slug}/{filename}"


@app.get("/admin/actividades", response_class=HTMLResponse)
def admin_activities(request: Request, edit: int | None = None, error: str = "", db: Session = Depends(get_db)):
    user = require_admin(request, db)
    if isinstance(user, RedirectResponse): return user
    items = db.query(models.ActividadAgenda).order_by(models.ActividadAgenda.fecha_inicio.desc(), models.ActividadAgenda.titulo).all()
    return templates.TemplateResponse("admin_actividades.html", {"request": request, "items": items, "editing": db.get(models.ActividadAgenda, edit) if edit else None, "categories": CATEGORIES, "moments": MOMENTS, "types": TYPES, "status": derived_status, "error": error})


@app.post("/admin/actividades/guardar")
async def admin_activity_save(request: Request, id: int | None = Form(None), tipo: str = Form(...), titulo: str = Form(...), descripcion_corta: str = Form(""), descripcion: str = Form(""), categoria: str = Form(...), momento: str = Form(...), fecha_inicio: str = Form(""), fecha_fin: str = Form(""), horarios: str = Form(""), lugar: str = Form(""), direccion: str = Form(""), maps_url: str = Form(""), whatsapp: str = Form(""), instagram: str = Form(""), url_externa: str = Form(""), orden: int | None = Form(None), publicado: str | None = Form(None), destacado: str | None = Form(None), imagen: UploadFile | None = File(None), db: Session = Depends(get_db)):
    user = require_admin(request, db)
    if isinstance(user, RedirectResponse): return user
    item = db.get(models.ActividadAgenda, id) if id else models.ActividadAgenda(created_at=utc_now())
    if id and not item: raise HTTPException(404)
    values = {"tipo": tipo, "titulo": titulo.strip(), "descripcion_corta": descripcion_corta.strip(), "descripcion": descripcion.strip(), "categoria": categoria, "momento": momento, "horarios": horarios.strip(), "lugar": lugar.strip(), "direccion": direccion.strip(), "maps_url": maps_url.strip(), "whatsapp": whatsapp.strip(), "instagram": instagram.strip(), "url_externa": url_externa.strip(), "orden": orden, "publicado": bool(publicado), "destacado": bool(destacado)}
    for name, value in values.items():
        setattr(item, name, value if name in {"publicado", "destacado", "orden"} else value or None)
    item.tipo, item.categoria, item.momento = tipo, categoria, momento
    item.fecha_inicio, item.fecha_fin, item.updated_at = parse_local_form_datetime(fecha_inicio), parse_local_form_datetime(fecha_fin), utc_now()
    # Keep published URLs stable when an editor changes a title.
    item.slug = item.slug if id else unique_agenda_slug(db, titulo)
    try:
        validate_activity(item)
        if has_uploaded_file(imagen): item.imagen_url = await save_agenda_image(imagen, item.slug)
    except ValueError as exc:
        # Editing mutates an ORM-managed object before validation. Explicitly
        # discard those changes and leave the request session reusable.
        db.rollback()
        return RedirectResponse(f"/admin/actividades?edit={id or ''}&error={quote(str(exc))}", 303)
    db.add(item); db.commit()
    return RedirectResponse("/admin/actividades", 303)


@app.post("/admin/actividades/{item_id}/duplicar")
def admin_activity_duplicate(request: Request, item_id: int, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    if isinstance(user, RedirectResponse): return user
    source = db.get(models.ActividadAgenda, item_id)
    if not source: raise HTTPException(404)
    copied = {c.name: getattr(source, c.name) for c in models.ActividadAgenda.__table__.columns if c.name not in {"id", "slug", "fecha_inicio", "fecha_fin", "publicado", "created_at", "updated_at"}}
    duplicate = models.ActividadAgenda(**copied, slug=unique_agenda_slug(db, f"{source.titulo}-copia"), fecha_inicio=None, fecha_fin=None, publicado=False, created_at=utc_now(), updated_at=utc_now())
    db.add(duplicate); db.commit()
    return RedirectResponse(f"/admin/actividades?edit={duplicate.id}", 303)


@app.post("/admin/actividades/{item_id}/eliminar")
def admin_activity_delete(request: Request, item_id: int, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    if isinstance(user, RedirectResponse): return user
    item = db.get(models.ActividadAgenda, item_id)
    if item: db.delete(item); db.commit()
    return RedirectResponse("/admin/actividades", 303)


@app.get("/descubri-cabalango", include_in_schema=False)
def redirect_descubri_cabalango():
    return RedirectResponse(url="/", status_code=308)


@app.get("/cabalango", include_in_schema=False)
def redirect_cabalango_legacy():
    return RedirectResponse(url="/", status_code=308)


@app.get("/admin", response_class=HTMLResponse)
def admin_panel(
    request: Request,
    area: str = "",
    empresa: str = "",
    tab: str = "empresa",
    msg: str = "",
    error: str = "",
    lead_q: str = "",
    lead_whatsapp: str = "",
    lead_pdf: str = "",
    lead_cart: str = "",
    lead_status: str = "",
    lead_interest: str = "",
    lead_archived: str = "",
    lead_unmanaged: str = "",
    lead_id: int | None = None,
    db: Session = Depends(get_db)
):
    user = require_admin(request, db)
    if isinstance(user, RedirectResponse):
        return user

    # Ensure nullable tourism/contact columns exist before SQLAlchemy selects Empresa rows.
    # This keeps tabs like Contacto / ubicación from failing on older Render databases.
    ensure_empresa_media_columns()
    ensure_destino_media_table()
    ensure_destino_contenido_table()

    empresas = db.query(models.Empresa).order_by(models.Empresa.nombre).all()
    empresa_activa = get_empresa_by_slug(db, empresa) or get_default_empresa(db)
    import time
    using_default_admin_password = os.getenv("ADMIN_PASSWORD", "").strip() in {"", "admin123"}
    active_tab = normalize_admin_tab(tab)
    admin_area = clean_text(area, default="").lower()
    if admin_area not in {"prestador", "portal"}:
        admin_area = "portal" if active_tab in ADMIN_PORTAL_TABS else "prestador"
    active_tab = normalize_admin_tab(active_tab, admin_area)

    lead_whatsapp_filter = parse_bool_query_flag(lead_whatsapp)
    lead_pdf_filter = parse_bool_query_flag(lead_pdf)
    lead_cart_filter = parse_bool_query_flag(lead_cart)
    lead_archived_filter = parse_bool_query_flag(lead_archived) is True
    lead_unmanaged_filter = parse_bool_query_flag(lead_unmanaged) is True
    lead_status_filter = normalize_lead_status(lead_status) if clean_text(lead_status, default="") else ""
    if lead_unmanaged_filter:
        lead_status_filter = "nuevo"
        lead_archived_filter = False
    lead_interest_filter = clean_text(lead_interest, default="").lower()
    if lead_interest_filter not in {"frio", "interesado", "caliente"}:
        lead_interest_filter = ""
    leads_rows = []
    leads_kpis = []
    lead_selected = None
    lead_selected_summary = None
    lead_timeline = []

    if empresa_activa:
        leads_rows = list_catalog_leads_for_admin(
            db=db,
            empresa_id=empresa_activa.id,
            search_query=lead_q,
            whatsapp_filter=lead_whatsapp_filter,
            pdf_filter=lead_pdf_filter,
            cart_filter=lead_cart_filter,
            status_filter=lead_status_filter,
            interest_filter=lead_interest_filter,
            include_archived=lead_archived_filter,
        )
        leads_kpis = build_leads_kpis(
            list_catalog_leads_for_admin(
                db=db,
                empresa_id=empresa_activa.id,
                include_archived=False,
            )
        )

        if lead_id:
            lead_selected = (
                db.query(models.CatalogLead)
                .filter(
                    models.CatalogLead.id == lead_id,
                    models.CatalogLead.empresa_catalogo_id == empresa_activa.id,
                    models.CatalogLead.deleted_at.is_(None),
                )
                .first()
            )

        if lead_selected:
            lead_events = (
                db.query(models.CatalogLeadEvent)
                .filter(
                    models.CatalogLeadEvent.lead_id == lead_selected.id,
                    models.CatalogLeadEvent.empresa_catalogo_id == empresa_activa.id,
                )
                .order_by(models.CatalogLeadEvent.created_at.desc(), models.CatalogLeadEvent.id.desc())
                .limit(200)
                .all()
            )
            lead_selected_summary = get_lead_summary_from_events(lead_events)
            lead_timeline = build_lead_timeline_rows(lead_events)


    response = templates.TemplateResponse(
        "upload.html",
        {
            "request": request,
            "msg": msg,
            "error": error,
            "empresas": empresas,
            "empresa_activa": empresa_activa,
            "empresa_query": empresa_activa.slug if empresa_activa else "",
            "empresa_logo_url": get_empresa_logo_url(empresa_activa),
            "empresa_banner_url": get_empresa_banner_url(empresa_activa),
            "galeria_urls": get_empresa_gallery_urls(empresa_activa) if empresa_activa else [],
            "menu_fotos_urls": get_empresa_menu_photo_urls(empresa_activa) if empresa_activa else [],
            "pending_reviews": db.query(models.Review).filter(models.Review.estado == "pendiente").order_by(models.Review.created_at.desc()).limit(30).all(),
            "time": int(time.time()),
            "using_default_admin_password": using_default_admin_password,
            "admin_username": os.getenv("ADMIN_USER", "admin"),
            "app_build": APP_BUILD,
            "active_tab": active_tab,
            "admin_area": admin_area,
            "leads_rows": leads_rows,
            "lead_q": lead_q,
            "lead_q_url": quote(lead_q or ""),
            "lead_whatsapp": lead_whatsapp_filter,
            "lead_pdf": lead_pdf_filter,
            "lead_cart": lead_cart_filter,
            "lead_status": lead_status_filter,
            "lead_interest": lead_interest_filter,
            "lead_archived": lead_archived_filter,
            "lead_unmanaged": lead_unmanaged_filter,
            "lead_selected": lead_selected,
            "lead_selected_summary": lead_selected_summary,
            "lead_timeline": lead_timeline,
            "lead_status_labels": LEAD_STATUS_LABELS,
            "leads_kpis": leads_kpis if empresa_activa else [],
            "destino_content": get_destino_content(db),
            "destino_media": db.query(models.DestinoMedia).order_by(models.DestinoMedia.orden.asc(), models.DestinoMedia.created_at.desc()).all(),
            "destino_categories": DESTINO_MEDIA_CATEGORIES,
            "servicios_grupos": SERVICIOS_GRUPOS,
            "servicios_subtipos": [item[1] for item in SERVICIOS_SUBTIPOS.values() if item[1] not in {"Transporte", "Estacionamiento", "Lavadero"}] + ["Otro"],
            "servicio_grupo_activo": service_group_key(empresa_activa) if empresa_activa and normalize_theme(empresa_activa.theme) == "servicios" else "",
            "prestador_section_label": theme_display_label(empresa_activa.theme) if empresa_activa else "",
            "prestador_taxonomy_label": service_card_kicker(empresa_activa) if empresa_activa and normalize_theme(empresa_activa.theme) == "servicios" else clean_text(empresa_activa.subtipo, default="") if empresa_activa else "",
            "servicio_subtipo_grupos": {label: group for group, label in SERVICIOS_SUBTIPOS.values()},
        },
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/mi-ficha", response_class=HTMLResponse)
@app.get("/cliente", response_class=HTMLResponse)
def cliente_panel(
    request: Request,
    msg: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    if isinstance(user, RedirectResponse):
        return user

    empresa_activa = resolve_empresa_for_user(user, db, None)
    if not empresa_activa:
        return HTMLResponse("<h1>Usuario sin empresa asignada</h1>", status_code=403)

    import time
    catalogo_public_url = str(request.url_for("prestador_publico", slug=empresa_activa.slug))
    whatsapp_message = f"Hola, te comparto nuestra ficha turística en Cabalango: {catalogo_public_url}"
    whatsapp_share_url = f"https://wa.me/?text={quote(whatsapp_message, safe='')}"
    response = templates.TemplateResponse(
        "cliente_panel.html",
        {
            "request": request,
            "msg": msg,
            "error": error,
            "empresa_activa": empresa_activa,
            "empresa_query": empresa_activa.slug,
            "empresa_logo_url": get_empresa_logo_url(empresa_activa),
            "empresa_banner_url": get_empresa_banner_url(empresa_activa),
            "galeria_urls": get_empresa_gallery_urls(empresa_activa),
            "menu_fotos_urls": get_empresa_menu_photo_urls(empresa_activa),
            "prestador_kind": get_prestador_kind(empresa_activa),
            "prestador_section_label": theme_display_label(empresa_activa.theme),
            "portal_section_url": "/" + public_section_for_theme(empresa_activa.theme) if public_section_for_theme(empresa_activa.theme) != "default" else "/",
            "catalogo_public_url": catalogo_public_url,
            "whatsapp_share_url": whatsapp_share_url,
            "time": int(time.time()),
            "app_build": APP_BUILD,
            "is_admin_view": user.rol == "admin",
        },
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response



@app.post("/cliente/empresa/actualizar")
def cliente_actualizar_empresa(
    request: Request,
    nombre: str = Form(...),
    whatsapp: str = Form(""),
    telefono: str = Form(""),
    instagram: str = Form(""),
    facebook: str = Form(""),
    web_url: str = Form(""),
    direccion: str = Form(""),
    maps_url: str = Form(""),
    subgrupo: str = Form(""),
    descripcion: str = Form(""),
    horarios: str = Form(""),
    precio_desde: str = Form(""),
    capacidad: str = Form(""),
    habitaciones: str = Form(""),
    video_url: str = Form(""),
    menu_url: str = Form(""),
    delivery: str = Form("0"),
    take_away: str = Form("0"),
    comer_en_lugar: str = Form("0"),
    pileta: str = Form("0"),
    rio: str = Form("0"),
    mascotas: str = Form("0"),
    cochera: str = Form("0"),
    wifi: str = Form("0"),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    if isinstance(user, RedirectResponse):
        return user
    empresa = resolve_empresa_for_user(user, db, None)
    if not empresa:
        return redirect_for_user(user, error="Empresa no encontrada")

    nombre_limpio = clean_text(nombre, default="")
    if not nombre_limpio:
        return redirect_for_user(user, empresa_slug=empresa.slug, error="El nombre no puede estar vacío")

    empresa.nombre = nombre_limpio
    empresa.whatsapp = clean_text(whatsapp, default="") or None
    empresa.telefono = clean_text(telefono, default="") or None
    empresa.instagram = clean_text(instagram, default="") or None
    empresa.facebook = normalize_external_url(facebook) or (clean_text(facebook, default="") or None)
    empresa.web_url = normalize_external_url(web_url)
    empresa.direccion = clean_text(direccion, default="") or None
    empresa.maps_url = normalize_external_url(maps_url) or (clean_text(maps_url, default="") or None)
    empresa.subgrupo = normalize_subgrupo_for_theme(subgrupo, empresa.theme)
    empresa.descripcion = clean_text(descripcion, default="") or None
    empresa.horarios = clean_text(horarios, default="") or None
    empresa.precio_desde = clean_text(precio_desde, default="") or None
    empresa.capacidad = clean_text(capacidad, default="") or None
    empresa.habitaciones = clean_text(habitaciones, default="") or None
    empresa.video_url = clean_text(video_url, default="") or None
    empresa.menu_url = normalize_external_url(menu_url) if "menu_url" in locals() else empresa.menu_url
    for attr, raw_value in {
        "delivery": delivery, "take_away": take_away, "comer_en_lugar": comer_en_lugar,
        "pileta": pileta, "rio": rio, "mascotas": mascotas, "cochera": cochera, "wifi": wifi,
    }.items():
        setattr(empresa, attr, str(raw_value) == "1")
    db.add(empresa)
    db.commit()
    return redirect_for_user(user, empresa_slug=empresa.slug, msg="Ficha actualizada")


@app.post("/cliente/empresa/imagenes")
async def cliente_actualizar_imagenes_empresa(
    request: Request,
    logo: UploadFile = File(None),
    banner: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    if isinstance(user, RedirectResponse):
        return user
    empresa = resolve_empresa_for_user(user, db, None)
    if not empresa:
        return redirect_for_user(user, error="Empresa no encontrada")
    if has_uploaded_file(logo):
        empresa.logo_url = await replace_empresa_media(empresa, media_type="logo", upload=logo)
    if has_uploaded_file(banner):
        empresa.banner_url = await replace_empresa_media(empresa, media_type="banner", upload=banner)
    db.add(empresa)
    db.commit()
    return redirect_for_user(user, empresa_slug=empresa.slug, msg="Fotos principales actualizadas")




@app.post("/admin/cabalango/contenido")
def actualizar_destino_contenido(
    request: Request,
    introduccion: str = Form(""),
    historia: str = Form(""),
    ubicacion: str = Form(""),
    naturaleza: str = Form(""),
    recomendaciones: str = Form(""),
    vida_local: str = Form(""),
    video_url: str = Form(""),
    visible: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_admin(request, db)
    if isinstance(user, RedirectResponse):
        return user
    content = get_destino_content(db)
    content.introduccion = clean_text(introduccion, default="") or None
    content.historia = clean_text(historia, default="") or None
    content.ubicacion = clean_text(ubicacion, default="") or None
    content.naturaleza = clean_text(naturaleza, default="") or None
    content.recomendaciones = clean_text(recomendaciones, default="") or None
    content.vida_local = clean_text(vida_local, default="") or None
    content.video_url = normalize_external_url(video_url) or (clean_text(video_url, default="") or None)
    content.visible = str(visible) == "1"
    content.updated_at = utc_now()
    db.add(content)
    db.commit()
    return panel_redirect(area="portal", tab="cabalango", msg="Contenido editorial actualizado")

@app.post("/admin/cabalango/media")
async def crear_destino_media(
    request: Request,
    tipo: str = Form("foto"),
    categoria: str = Form("rio_naturaleza"),
    titulo: str = Form(""),
    descripcion: str = Form(""),
    video_url: str = Form(""),
    destacado: str = Form(""),
    visible: str = Form("1"),
    orden: int = Form(0),
    fotos: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    user = require_admin(request, db)
    if isinstance(user, RedirectResponse):
        return user
    ensure_destino_media_table()
    tipo_clean = normalize_destino_tipo(tipo)
    categoria_clean = normalize_destino_categoria(categoria)
    created = 0
    if tipo_clean == "video":
        url = clean_text(video_url, default="")
        if not url:
            return panel_redirect(area="portal", tab="cabalango", error="Cargá un link de video.", path="/admin")
        db.add(models.DestinoMedia(tipo="video", categoria="videos", titulo=clean_text(titulo, default=""), descripcion=clean_text(descripcion, default=""), video_url=url, destacado=bool(destacado), visible=bool(visible), orden=orden))
        created = 1
    else:
        for upload in fotos or []:
            if not has_uploaded_file(upload):
                continue
            if Path(upload.filename).suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
                continue
            image_url = await save_destino_image(upload)
            db.add(models.DestinoMedia(tipo="foto", categoria=categoria_clean, titulo=clean_text(titulo, default=""), descripcion=clean_text(descripcion, default=""), image_path=image_url, destacado=bool(destacado), visible=bool(visible), orden=orden))
            created += 1
    db.commit()
    msg = f"Contenido del destino agregado ({created})." if created else "No se cargó contenido nuevo."
    return panel_redirect(area="portal", tab="cabalango", msg=msg)

@app.post("/admin/cabalango/media/{media_id}/toggle")
def toggle_destino_media(media_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    if isinstance(user, RedirectResponse):
        return user
    item = db.query(models.DestinoMedia).filter(models.DestinoMedia.id == media_id).first()
    if item:
        item.visible = not bool(item.visible)
        db.add(item)
        db.commit()
    return panel_redirect(area="portal", tab="cabalango", msg="Contenido actualizado")

@app.post("/empresa/galeria")
async def actualizar_galeria_empresa_admin(
    request: Request,
    empresa_slug: str = Form(...),
    fotos: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    user = require_admin(request, db)
    if isinstance(user, RedirectResponse):
        return user
    empresa = get_empresa_by_slug(db, empresa_slug)
    if not empresa:
        return panel_redirect(error="Prestador no encontrado")
    _, message = await append_empresa_gallery_images(empresa, fotos or [])
    db.add(empresa)
    db.commit()
    return panel_redirect(empresa_slug=empresa.slug, area="prestador", tab="fotos", msg=message, path="/admin")


@app.post("/empresa/{empresa_id}/galeria/eliminar")
def eliminar_foto_galeria_empresa_admin(
    empresa_id: int,
    request: Request,
    foto_indice: int = Form(...),
    db: Session = Depends(get_db),
):
    user = require_admin(request, db)
    if isinstance(user, RedirectResponse):
        return user
    empresa = db.query(models.Empresa).filter(models.Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Prestador no encontrado")
    gallery = get_empresa_gallery_urls(empresa)
    if foto_indice < 0 or foto_indice >= len(gallery):
        raise HTTPException(status_code=400, detail="La foto no pertenece a este prestador")

    removed_url = gallery.pop(foto_indice)
    managed_file = managed_gallery_file(empresa, removed_url)
    empresa.galeria_urls = json.dumps(gallery, ensure_ascii=False)
    try:
        db.add(empresa)
        db.commit()
    except Exception:
        db.rollback()
        raise
    if managed_file and managed_file.is_file():
        try:
            managed_file.unlink()
        except OSError:
            # The database reference is already clean; a storage cleanup failure
            # must not turn a valid admin action into a server error.
            pass
    return panel_redirect(
        empresa_slug=empresa.slug,
        area="prestador",
        tab="fotos",
        msg="Foto eliminada de la galería",
        path="/admin",
    )

@app.post("/cliente/empresa/galeria")
async def cliente_actualizar_galeria_empresa(
    request: Request,
    fotos: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    if isinstance(user, RedirectResponse):
        return user
    empresa = resolve_empresa_for_user(user, db, None)
    if not empresa:
        return redirect_for_user(user, error="Prestador no encontrado")
    _, message = await append_empresa_gallery_images(empresa, fotos or [])
    db.add(empresa)
    db.commit()
    return redirect_for_user(user, empresa_slug=empresa.slug, msg=message)


@app.post("/empresa/menu-fotos")
async def actualizar_menu_fotos_empresa_admin(
    request: Request,
    empresa_slug: str = Form(...),
    fotos: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    user = require_admin(request, db)
    if isinstance(user, RedirectResponse):
        return user
    empresa = get_empresa_by_slug(db, empresa_slug)
    if not empresa:
        return panel_redirect(error="Prestador no encontrado")
    if get_prestador_kind(empresa) != "gastronomia":
        return panel_redirect(empresa_slug=empresa.slug, error="Las fotos de menú/carta solo aplican a gastronomía.", path="/admin")
    _, message = await append_empresa_menu_images(empresa, fotos or [])
    db.add(empresa)
    db.commit()
    return panel_redirect(empresa_slug=empresa.slug, msg=message, path="/admin")


@app.post("/cliente/empresa/menu-fotos")
async def cliente_actualizar_menu_fotos_empresa(
    request: Request,
    fotos: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    if isinstance(user, RedirectResponse):
        return user
    empresa = resolve_empresa_for_user(user, db, None)
    if not empresa:
        return redirect_for_user(user, error="Prestador no encontrado")
    if get_prestador_kind(empresa) != "gastronomia":
        return redirect_for_user(user, empresa_slug=empresa.slug, error="Las fotos de menú/carta solo aplican a gastronomía.")
    _, message = await append_empresa_menu_images(empresa, fotos or [])
    db.add(empresa)
    db.commit()
    return redirect_for_user(user, empresa_slug=empresa.slug, msg=message)

@app.post("/admin/leads/{lead_id}/status")
def admin_update_lead_status(
    request: Request,
    lead_id: int,
    empresa: str = Form(""),
    status: str = Form("nuevo"),
    db: Session = Depends(get_db),
):
    user = require_admin(request, db)
    if isinstance(user, RedirectResponse):
        return user

    empresa_obj = get_empresa_by_slug(db, empresa) or get_default_empresa(db)
    if not empresa_obj:
        return panel_redirect(error="No hay empresa activa", path="/admin")

    lead = (
        db.query(models.CatalogLead)
        .filter(
            models.CatalogLead.id == lead_id,
            models.CatalogLead.empresa_catalogo_id == empresa_obj.id,
            models.CatalogLead.deleted_at.is_(None),
        )
        .first()
    )
    if not lead:
        return panel_redirect(empresa_slug=empresa_obj.slug, error="Lead no encontrado", path="/admin")

    new_status = normalize_lead_status(status)
    lead.estado = new_status
    lead.archived_at = utc_now() if new_status == "archivado" else None
    db.add(lead)
    db.commit()
    return RedirectResponse(
        url=f"/admin?empresa={quote(empresa_obj.slug)}&tab=leads&lead_id={lead_id}&msg={quote('Estado del lead actualizado')}",
        status_code=303,
    )


@app.post("/admin/leads/{lead_id}/notes")
def admin_update_lead_notes(
    request: Request,
    lead_id: int,
    empresa: str = Form(""),
    notas: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_admin(request, db)
    if isinstance(user, RedirectResponse):
        return user

    empresa_obj = get_empresa_by_slug(db, empresa) or get_default_empresa(db)
    if not empresa_obj:
        return panel_redirect(error="No hay empresa activa", path="/admin")

    lead = (
        db.query(models.CatalogLead)
        .filter(
            models.CatalogLead.id == lead_id,
            models.CatalogLead.empresa_catalogo_id == empresa_obj.id,
            models.CatalogLead.deleted_at.is_(None),
        )
        .first()
    )
    if not lead:
        return panel_redirect(empresa_slug=empresa_obj.slug, error="Lead no encontrado", path="/admin")

    lead.notas_internas = clean_text(notas, default="")
    db.add(lead)
    db.commit()
    return RedirectResponse(
        url=f"/admin?empresa={quote(empresa_obj.slug)}&tab=leads&lead_id={lead_id}&msg={quote('Notas internas guardadas')}",
        status_code=303,
    )


@app.post("/admin/leads/{lead_id}/archive")
def admin_archive_lead(
    request: Request,
    lead_id: int,
    empresa: str = Form(""),
    db: Session = Depends(get_db),
):
    return admin_update_lead_status(
        request=request,
        lead_id=lead_id,
        empresa=empresa,
        status="archivado",
        db=db,
    )


@app.post("/admin/leads/{lead_id}/quick-action")
def admin_quick_action_lead(
    request: Request,
    lead_id: int,
    empresa: str = Form(""),
    action: str = Form(""),
    db: Session = Depends(get_db),
):
    normalized_action = clean_text(action, default="").lower()
    if normalized_action == "contactado":
        return admin_update_lead_status(
            request=request,
            lead_id=lead_id,
            empresa=empresa,
            status="contactado",
            db=db,
        )
    if normalized_action == "oportunidad":
        return admin_update_lead_status(
            request=request,
            lead_id=lead_id,
            empresa=empresa,
            status="oportunidad",
            db=db,
        )
    if normalized_action == "archivar":
        return admin_archive_lead(
            request=request,
            lead_id=lead_id,
            empresa=empresa,
            db=db,
        )
    empresa_slug = (get_empresa_by_slug(db, empresa) or get_default_empresa(db))
    return panel_redirect(
        empresa_slug=empresa_slug.slug if empresa_slug else "",
        error="Acción rápida inválida",
        path="/admin",
    )


@app.post("/admin/leads/{lead_id}/delete")
def admin_delete_lead(
    request: Request,
    lead_id: int,
    empresa: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_admin(request, db)
    if isinstance(user, RedirectResponse):
        return user

    empresa_obj = get_empresa_by_slug(db, empresa) or get_default_empresa(db)
    if not empresa_obj:
        return panel_redirect(error="No hay empresa activa", path="/admin")

    lead = (
        db.query(models.CatalogLead)
        .filter(
            models.CatalogLead.id == lead_id,
            models.CatalogLead.empresa_catalogo_id == empresa_obj.id,
            models.CatalogLead.deleted_at.is_(None),
        )
        .first()
    )
    if not lead:
        return panel_redirect(empresa_slug=empresa_obj.slug, error="Lead no encontrado", path="/admin")

    lead.deleted_at = utc_now()
    lead.estado = "archivado"
    lead.archived_at = lead.archived_at or utc_now()
    db.add(lead)
    db.commit()
    return RedirectResponse(
        url=f"/admin?empresa={quote(empresa_obj.slug)}&tab=leads&msg={quote('Lead eliminado')}",
        status_code=303,
    )


@app.get("/panel")
def panel_alias():
    return RedirectResponse(url="/mi-ficha", status_code=303)

# ---------------------------------------------------
# CREAR EMPRESA
# ---------------------------------------------------
@app.post("/empresa/crear_panel")
async def crear_empresa_panel(
    request: Request,
    nombre: str = Form(...),
    slug: str = Form(...),
    whatsapp: str = Form(""),
    telefono: str = Form(""),
    instagram: str = Form(""),
    facebook: str = Form(""),
    web_url: str = Form(""),
    direccion: str = Form(""),
    maps_url: str = Form(""),
    descripcion: str = Form(""),
    horarios: str = Form(""),
    video_url: str = Form(""),
    subgrupo: str = Form(""),
    subtipo: str = Form(""),
    destacado: str = Form("0"),
    activo: str = Form("1"),
    theme: str = Form("default"),
    logo: UploadFile = File(None),
    banner: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    auth = require_admin(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    nombre = nombre.strip()
    slug = slug.strip().lower()
    slug = re.sub(r"[^a-z0-9\-]", "-", slug)
    slug = re.sub(r"-+", "-", slug)

    if not nombre or not slug:
        return RedirectResponse(url="/?error=Datos incompletos", status_code=303)

    existe = db.query(models.Empresa).filter(models.Empresa.slug == slug).first()
    if existe:
        return RedirectResponse(url="/?error=La empresa ya existe", status_code=303)

    empresa = models.Empresa(
        nombre=nombre,
        slug=slug,
        whatsapp=clean_text(whatsapp, default="") or None,
        telefono=clean_text(telefono, default="") or None,
        instagram=clean_text(instagram, default="") or None,
        facebook=normalize_external_url(facebook) or (clean_text(facebook, default="") or None),
        web_url=normalize_external_url(web_url),
        direccion=clean_text(direccion, default="") or None,
        maps_url=normalize_external_url(maps_url) or (clean_text(maps_url, default="") or None),
        descripcion=clean_text(descripcion, default="") or None,
        horarios=clean_text(horarios, default="") or None,
        video_url=clean_text(video_url, default="") or None,
        subgrupo=normalize_service_group_subtype(subgrupo, subtipo, theme),
        subtipo=clean_text(subtipo, default="") or None,
        destacado=str(destacado) == "1",
        activo=str(activo) == "1",
        politica_precio_catalogo="automatico",
        politica_stock_catalogo="mostrar",
        theme=normalize_theme(theme),
    )
    db.add(empresa)
    db.commit()
    db.refresh(empresa)

    get_productos_media_dir(empresa.slug).mkdir(parents=True, exist_ok=True)

    if has_uploaded_file(logo):
        empresa.logo_url = await replace_empresa_media(empresa, media_type="logo", upload=logo)

    if has_uploaded_file(banner):
        empresa.banner_url = await replace_empresa_media(empresa, media_type="banner", upload=banner)

    db.add(empresa)
    db.commit()

    return panel_redirect(empresa_slug=empresa.slug, msg="Empresa creada correctamente")


@app.post("/admin/usuarios/crear")
def crear_usuario_cliente(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    rol: str = Form("cliente"),
    empresa_slug: str = Form(""),
    db: Session = Depends(get_db),
):
    auth = require_admin(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    username_clean = clean_text(username, default="").lower()
    if not username_clean or len(password) < 6:
        return panel_redirect(error="Usuario inválido o contraseña muy corta (mínimo 6).")

    if db.query(models.Usuario).filter(models.Usuario.username == username_clean).first():
        return panel_redirect(error="Ese usuario ya existe.")

    role_clean = "admin" if rol == "admin" else "cliente"
    empresa_id = None
    if role_clean == "cliente":
        empresa = get_empresa_by_slug(db, empresa_slug)
        if not empresa:
            return panel_redirect(error="Para cliente debés seleccionar empresa.")
        empresa_id = empresa.id

    user = models.Usuario(
        username=username_clean,
        password_hash=hash_password(password),
        rol=role_clean,
        activo=True,
        empresa_id=empresa_id,
    )
    db.add(user)
    db.commit()
    return panel_redirect(
        empresa_slug=empresa_slug or None,
        msg=f"Usuario '{username_clean}' creado con rol {role_clean}."
    )


@app.post("/delete_all_products")
def delete_all_products(
    request: Request,
    empresa_slug: str = Form(...),
    db: Session = Depends(get_db)
):
    auth = require_admin(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    empresa = get_empresa_by_slug(db, empresa_slug)
    if not empresa:
        return panel_redirect(error="Empresa inválida.")

    db.query(models.Producto).filter(models.Producto.empresa_id == empresa.id).delete()
    db.commit()

    return panel_redirect(area="portal", tab="tecnico", msg=f"Se borraron todos los productos de {empresa.nombre}.")

# ---------------------------------------------------
# SUBIR EXCEL
# ---------------------------------------------------
@app.post("/upload_excel")
def upload_excel(
    request: Request,
    empresa_slug: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    if isinstance(user, RedirectResponse):
        return user

    try:
        empresa = can_access_empresa(user, empresa_slug, db)
        if not empresa:
            return redirect_for_user(user, error="Empresa inválida. Seleccioná una empresa primero.")

        filename = (file.filename or "").lower()
        if not filename.endswith((".xlsx", ".xls")):
            return panel_redirect(empresa_slug=empresa.slug, error="Formato inválido. Subí un archivo Excel (.xlsx o .xls).")

        df = pd.read_excel(file.file)
        df.columns = [c.strip().lower() for c in df.columns]

        required = ["codigo", "descripcion", "precio"]
        for col in required:
            if col not in df.columns:
                return redirect_for_user(user, empresa_slug=empresa.slug, error=f"Falta columna obligatoria: {col}")

        nuevos = 0
        actualizados = 0

        for _, row in df.iterrows():
            codigo = clean_text(row.get("codigo", ""))
            if not codigo:
                continue

            categoria = clean_text(row.get("categoria", ""), default="") or None
            marca = clean_text(row.get("marca", ""), default="") or None
            stock = clean_stock(row.get("stock", 0), default=0)
            precio = clean_price(row.get("precio", 0), default=0.0)
            descripcion = clean_text(row.get("descripcion", ""), default="")

            existe = db.query(models.Producto).filter(
                models.Producto.codigo == codigo,
                models.Producto.empresa_id == empresa.id
            ).first()

            if existe:
                existe.descripcion = descripcion or existe.descripcion
                existe.precio = precio
                existe.categoria = categoria
                existe.marca = marca
                existe.stock = stock
                actualizados += 1
            else:
                producto = models.Producto(
                    codigo=codigo,
                    descripcion=descripcion or codigo,
                    categoria=categoria,
                    marca=marca,
                    precio=precio,
                    stock=stock,
                    empresa_id=empresa.id
                )
                db.add(producto)
                nuevos += 1

        db.commit()

        return redirect_for_user(
            user,
            empresa_slug=empresa.slug,
            msg=f"Productos cargados. Nuevos: {nuevos}, Actualizados: {actualizados}."
        )

    except Exception as e:
        print("Error Excel:", e)
        return redirect_for_user(user, empresa_slug=empresa_slug, error="Error al procesar el Excel.")


# ---------------------------------------------------
# SUBIR ZIP
# ---------------------------------------------------
@app.post("/upload_zip")
def upload_zip(
    request: Request,
    empresa_slug: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    if isinstance(user, RedirectResponse):
        return user

    try:
        empresa = can_access_empresa(user, empresa_slug, db)
        if not empresa:
            return redirect_for_user(user, error="Empresa inválida.")

        images_dir = get_productos_media_dir(empresa.slug)
        images_dir.mkdir(parents=True, exist_ok=True)
        copied = 0

        with zipfile.ZipFile(file.file, "r") as zip_ref:
            for member, safe_path in _zip_safe_members(zip_ref):
                ext = safe_path.suffix.lower()
                if ext not in ALLOWED_IMAGE_EXTENSIONS:
                    continue

                code_raw = clean_text(safe_path.stem, default="")
                code_name = sanitize_codigo_for_filename(code_raw)
                filename = f"{code_name}{ext}"
                destination = images_dir / filename
                with zip_ref.open(member, "r") as src, open(destination, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                producto = (
                    db.query(models.Producto)
                    .filter(
                        models.Producto.empresa_id == empresa.id,
                        models.Producto.codigo == code_raw
                    )
                    .first()
                )
                if producto:
                    producto.imagen_url = build_producto_media_url(empresa.slug, filename)
                copied += 1

        db.commit()
        return redirect_for_user(user, empresa_slug=empresa.slug, msg=f"Imágenes cargadas correctamente ({copied} archivos).")

    except Exception as e:
        print("Error ZIP:", e)
        return redirect_for_user(user, empresa_slug=empresa_slug, error="Error al procesar el ZIP.")


@app.get("/admin/empresa/exportar")
def exportar_empresa_completa(
    request: Request,
    empresa: str | None = Query(default=None),
    db: Session = Depends(get_db)
):
    auth = require_admin(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    empresa_obj = get_empresa_by_slug(db, empresa)
    if not empresa_obj:
        return JSONResponse({"error": "Seleccioná una empresa válida para exportar"}, status_code=400)

    productos = db.query(models.Producto).filter(models.Producto.empresa_id == empresa_obj.id).all()
    payload = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "empresa": {
            "nombre": empresa_obj.nombre,
            "slug": empresa_obj.slug,
            "whatsapp": empresa_obj.whatsapp,
            "logo_url": empresa_obj.logo_url,
            "banner_url": empresa_obj.banner_url,
            "politica_precio_catalogo": normalize_price_policy(empresa_obj.politica_precio_catalogo),
            "politica_stock_catalogo": normalize_stock_policy(empresa_obj.politica_stock_catalogo),
            "theme": normalize_theme(empresa_obj.theme),
        },
        "productos": [
            {
                "codigo": p.codigo,
                "descripcion": p.descripcion,
                "categoria": p.categoria,
                "marca": p.marca,
                "precio": float(p.precio or 0),
                "stock": int(p.stock or 0),
                "activo": bool(p.activo),
                "imagen_url": p.imagen_url,
            }
            for p in productos
        ],
    }

    memory_file = BytesIO()
    static_empresa_dir = Path("app/static/empresas") / empresa_obj.slug
    storage_empresa_dir = MEDIA_BASE_DIR / empresa_obj.slug

    with zipfile.ZipFile(memory_file, mode="w", compression=zipfile.ZIP_DEFLATED) as zipf:
        zipf.writestr("empresa.json", json.dumps(payload, ensure_ascii=False, indent=2))

        if static_empresa_dir.exists():
            for file_path in static_empresa_dir.rglob("*"):
                if file_path.is_file():
                    arcname = Path("static_empresas") / file_path.relative_to(static_empresa_dir)
                    zipf.write(file_path, arcname.as_posix())

        if storage_empresa_dir.exists():
            for file_path in storage_empresa_dir.rglob("*"):
                if file_path.is_file():
                    arcname = Path("storage_empresas") / file_path.relative_to(storage_empresa_dir)
                    zipf.write(file_path, arcname.as_posix())

    memory_file.seek(0)
    filename = f"empresa_{empresa_obj.slug}_backup.zip"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(memory_file, media_type="application/zip", headers=headers)


@app.post("/admin/empresa/importar")
def importar_empresa_completa(
    request: Request,
    import_mode: str = Form("duplicate"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    auth = require_admin(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    mode = (import_mode or "duplicate").strip().lower()
    if mode not in {"duplicate", "replace"}:
        mode = "duplicate"

    try:
        zip_bytes = file.file.read()
        with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zip_ref:
            if "empresa.json" not in zip_ref.namelist():
                return panel_redirect(area="portal", tab="configuracion", error="ZIP inválido: falta empresa.json.")

            payload = json.loads(zip_ref.read("empresa.json").decode("utf-8"))
            empresa_data = payload.get("empresa", {}) or {}
            productos_data = payload.get("productos", []) or []

            source_slug = clean_text(empresa_data.get("slug", ""), default="")
            source_slug = re.sub(r"[^a-z0-9\-]", "-", source_slug.lower())
            source_slug = re.sub(r"-+", "-", source_slug).strip("-")
            if not source_slug:
                return panel_redirect(area="portal", tab="configuracion", error="ZIP inválido: slug de empresa vacío.")

            existing = get_empresa_by_slug(db, source_slug)

            if mode == "replace":
                target_slug = source_slug
                if existing:
                    target_empresa = existing
                    db.query(models.Producto).filter(models.Producto.empresa_id == target_empresa.id).delete()
                    static_target = Path("app/static/empresas") / target_slug
                    if static_target.exists():
                        shutil.rmtree(static_target)
                    storage_target = MEDIA_BASE_DIR / target_slug
                    if storage_target.exists():
                        shutil.rmtree(storage_target)
                else:
                    target_empresa = models.Empresa(
                        nombre=clean_text(empresa_data.get("nombre", source_slug), default=source_slug),
                        slug=target_slug,
                        whatsapp=clean_text(empresa_data.get("whatsapp", ""), default="") or None,
                        politica_precio_catalogo=normalize_price_policy(empresa_data.get("politica_precio_catalogo")),
                        politica_stock_catalogo=normalize_stock_policy(empresa_data.get("politica_stock_catalogo")),
                        theme=normalize_theme(empresa_data.get("theme")),
                    )
                    db.add(target_empresa)
                    db.flush()
            else:
                target_slug = build_unique_slug(db, source_slug)
                target_empresa = models.Empresa(
                    nombre=clean_text(empresa_data.get("nombre", source_slug), default=source_slug),
                    slug=target_slug,
                    whatsapp=clean_text(empresa_data.get("whatsapp", ""), default="") or None,
                    politica_precio_catalogo=normalize_price_policy(empresa_data.get("politica_precio_catalogo")),
                    politica_stock_catalogo=normalize_stock_policy(empresa_data.get("politica_stock_catalogo")),
                    theme=normalize_theme(empresa_data.get("theme")),
                )
                db.add(target_empresa)
                db.flush()

            target_empresa.nombre = clean_text(empresa_data.get("nombre", target_empresa.nombre), default=target_empresa.nombre)
            target_empresa.whatsapp = clean_text(empresa_data.get("whatsapp", target_empresa.whatsapp or ""), default="") or None
            target_empresa.politica_precio_catalogo = normalize_price_policy(
                empresa_data.get("politica_precio_catalogo", target_empresa.politica_precio_catalogo)
            )
            target_empresa.politica_stock_catalogo = normalize_stock_policy(
                empresa_data.get("politica_stock_catalogo", target_empresa.politica_stock_catalogo)
            )
            target_empresa.theme = normalize_theme(empresa_data.get("theme", target_empresa.theme))
            target_empresa.logo_url = build_media_url(target_slug, "logo", "logo.png")
            target_empresa.banner_url = build_media_url(target_slug, "banner", "banner.jpg")

            for p in productos_data:
                codigo = clean_text(p.get("codigo", ""), default="")
                if not codigo:
                    continue
                codigo_safe = sanitize_codigo_for_filename(codigo)
                imported_url = clean_text(p.get("imagen_url", ""), default="") or None
                normalized_imagen_url = None
                if imported_url:
                    imported_name = Path(imported_url).name
                    if imported_name:
                        normalized_imagen_url = build_producto_media_url(target_slug, imported_name)
                if not normalized_imagen_url:
                    normalized_imagen_url = build_producto_media_url(target_slug, f"{codigo_safe}.jpg")
                db.add(models.Producto(
                    empresa_id=target_empresa.id,
                    codigo=codigo,
                    descripcion=clean_text(p.get("descripcion", codigo), default=codigo),
                    categoria=clean_text(p.get("categoria", ""), default="") or None,
                    marca=clean_text(p.get("marca", ""), default="") or None,
                    precio=clean_price(p.get("precio", 0), default=0.0),
                    stock=clean_stock(p.get("stock", 0), default=0),
                    activo=bool(p.get("activo", True)),
                    imagen_url=normalized_imagen_url,
                ))

            static_target_dir = Path("app/static/empresas") / target_slug
            storage_target_dir = MEDIA_BASE_DIR / target_slug
            _copy_zip_prefix(zip_ref, "static_empresas", static_target_dir)
            _copy_zip_prefix(zip_ref, "storage_empresas", storage_target_dir)

            legacy_productos_dir = static_target_dir / "productos"
            persistent_productos_dir = get_productos_media_dir(target_slug)
            if legacy_productos_dir.exists():
                persistent_productos_dir.mkdir(parents=True, exist_ok=True)
                for legacy_file in legacy_productos_dir.rglob("*"):
                    if not legacy_file.is_file():
                        continue
                    if legacy_file.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
                        continue
                    destination = persistent_productos_dir / legacy_file.name
                    if not destination.exists():
                        _copy_file(legacy_file, destination)

            db.add(target_empresa)
            db.commit()

            action = "reemplazada" if mode == "replace" else "importada"
            return panel_redirect(
                area="portal",
                tab="configuracion",
                msg=f"Empresa {action} correctamente con slug '{target_slug}'."
            )

    except zipfile.BadZipFile:
        return panel_redirect(area="portal", tab="configuracion", error="Archivo ZIP inválido.")
    except Exception as e:
        db.rollback()
        print("Error importando empresa:", e)
        return panel_redirect(area="portal", tab="configuracion", error="Error al importar la empresa.")

# ---------------------------------------------------
# CATÁLOGO
# ---------------------------------------------------
@app.get("/catalogo/{slug}/acceso", response_class=HTMLResponse)
def catalogo_acceso(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
):
    empresa = db.query(models.Empresa).filter(models.Empresa.slug == slug).first()
    if not empresa:
        return HTMLResponse("<h1>Prestador no encontrado</h1><p>La ficha turística solicitada no existe.</p>", status_code=404)
    return RedirectResponse(url=f"/prestador/{empresa.slug}", status_code=308)


@app.post("/catalogo/{slug}/acceso")
def catalogo_acceso_submit(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
):
    empresa_obj = db.query(models.Empresa).filter(models.Empresa.slug == slug).first()
    if not empresa_obj:
        return HTMLResponse("<h1>Prestador no encontrado</h1><p>La ficha turística solicitada no existe.</p>", status_code=404)
    return RedirectResponse(url=f"/prestador/{empresa_obj.slug}", status_code=308)


def get_prestador_kind(empresa: models.Empresa) -> str:
    theme = public_section_for_theme(empresa.theme)
    if theme in {"gastronomia", "alojamiento", "servicios", "actividades"}:
        return theme
    return "general"



def get_review_copy(kind: str) -> dict[str, str]:
    copies = {
        "alojamiento": {
            "title": "Opiniones de huéspedes",
            "subtitle": "Experiencias publicadas para ayudar a nuevos visitantes a decidir con confianza.",
        },
        "gastronomia": {
            "title": "Opiniones de clientes",
            "subtitle": "Experiencias de personas que visitaron o compraron en este lugar.",
        },
        "servicios": {
            "title": "Opiniones de usuarios",
            "subtitle": "Comentarios de vecinos y visitantes sobre este servicio.",
        },
        "actividades": {
            "title": "Opiniones de participantes",
            "subtitle": "Experiencias de personas que participaron de esta actividad o propuesta local.",
        },
    }
    return copies.get(kind, {
        "title": "Opiniones de visitantes",
        "subtitle": "Experiencias publicadas para ayudar a nuevos visitantes a decidir con confianza.",
    })

def get_feature_rows(empresa: models.Empresa, feature_names: list[tuple[str, str]]):
    rows = []
    for attr, label in feature_names:
        value = getattr(empresa, attr, None)
        rows.append({"label": label, "enabled": value is True, "prepared": value is None})
    return rows


def _append_text_fact(rows: list[dict], label: str, value: str | None):
    clean_value = clean_text(value, default="")
    if clean_value:
        rows.append({"label": label, "value": clean_value, "enabled": True, "prepared": False})


def _append_bool_fact(rows: list[dict], label: str, value):
    if value is True:
        rows.append({"label": label, "value": "Sí", "enabled": True, "prepared": False})
    elif value is None:
        rows.append({"label": label, "value": "Consultar", "enabled": False, "prepared": True})


def build_prestador_quick_facts(empresa: models.Empresa, kind: str) -> list[dict]:
    rows: list[dict] = []
    if kind == "alojamiento":
        _append_text_fact(rows, "Precio desde", empresa.precio_desde)
        _append_text_fact(rows, "Capacidad", empresa.capacidad)
        _append_text_fact(rows, "Habitaciones", empresa.habitaciones)
        _append_text_fact(rows, "Baños", empresa.banos)
        for attr, label in [("pileta", "Pileta"), ("rio", "Frente al río / cerca del río"), ("mascotas", "Mascotas"), ("cochera", "Cochera"), ("wifi", "WiFi"), ("parrilla", "Parrilla")]:
            _append_bool_fact(rows, label, getattr(empresa, attr, None))
    elif kind == "gastronomia":
        for attr, label in [("delivery", "Delivery"), ("take_away", "Take away"), ("comer_en_lugar", "Comer en el lugar")]:
            _append_bool_fact(rows, label, getattr(empresa, attr, None))
        _append_text_fact(rows, "Tipo de lugar", empresa.subtipo)
        _append_text_fact(rows, "Horarios", empresa.horarios)
        _append_text_fact(rows, "Especialidad", empresa.promocion)
    elif kind == "servicios":
        _append_text_fact(rows, "Tipo de servicio", empresa.subtipo)
        _append_text_fact(rows, "Horarios", empresa.horarios)
        _append_text_fact(rows, "Dirección", empresa.direccion)
        _append_text_fact(rows, "Teléfono / WhatsApp", empresa.telefono or empresa.whatsapp)
        _append_text_fact(rows, "Guardia / urgencia", empresa.guardia)
    elif kind == "actividades":
        subgrupo_label = ACTIVIDADES_SUBGRUPOS.get(empresa.subgrupo or "", {}).get("label", empresa.subgrupo)
        _append_text_fact(rows, "Subgrupo", subgrupo_label)
        _append_text_fact(rows, "Fecha", empresa.fecha)
        _append_text_fact(rows, "Horario", empresa.horarios)
        _append_text_fact(rows, "Lugar de encuentro", empresa.lugar_encuentro)
        _append_text_fact(rows, "Organizador", empresa.organizador)
        _append_text_fact(rows, "Precio", empresa.precio_desde)
    else:
        _append_text_fact(rows, "Tipo", empresa.subtipo)
        _append_text_fact(rows, "Horarios", empresa.horarios)
        _append_text_fact(rows, "Dirección", empresa.direccion)
    return rows[:12]


def build_public_reviews(empresa: models.Empresa, db: Session) -> tuple[list[dict], float | None, int]:
    reviews = (
        db.query(models.Review)
        .filter(
            models.Review.prestador_id == empresa.id,
            models.Review.estado == "aprobada",
            models.Review.visible == True,
        )
        .order_by(models.Review.created_at.desc())
        .limit(6)
        .all()
    )
    public_reviews = [
        {
            "nombre": review.nombre[:80],
            "comentario": review.comentario[:360],
            "rating": review.rating,
            "fecha": review.fecha,
        }
        for review in reviews
    ]
    stats = (
        db.query(func.avg(models.Review.rating), func.count(models.Review.id))
        .filter(
            models.Review.prestador_id == empresa.id,
            models.Review.estado == "aprobada",
            models.Review.visible == True,
        )
        .first()
    )
    avg = float(stats[0]) if stats and stats[0] is not None else None
    count = int(stats[1] or 0) if stats else 0
    return public_reviews, avg, count


@app.get("/prestador/{slug}", response_class=HTMLResponse)
def prestador_publico(slug: str, request: Request, db: Session = Depends(get_db)):
    empresa = db.query(models.Empresa).filter(models.Empresa.slug == slug).first()
    if not empresa:
        return HTMLResponse("<h1>Prestador no encontrado</h1>", status_code=404)

    kind = get_prestador_kind(empresa)
    galeria_urls = get_empresa_gallery_urls(empresa)
    menu_fotos_urls = get_empresa_menu_photo_urls(empresa)
    menu_url = normalize_external_url(empresa.menu_url)
    show_menu_section = kind == "gastronomia" and bool(menu_url or menu_fotos_urls or clean_text(empresa.promocion, default=""))
    public_reviews, review_avg, review_count = build_public_reviews(empresa, db)
    empresa_banner_url = get_empresa_banner_url(empresa)
    empresa_logo_url = get_empresa_logo_url(empresa)
    fallback_tiles = [url for url in [empresa_banner_url] if url]
    gallery_tiles = (galeria_urls[1:5] if galeria_urls else fallback_tiles[:2])
    main_photo_url = galeria_urls[0] if galeria_urls else (empresa_banner_url or "/static/img/no-image.jpg")
    has_real_photos = bool(galeria_urls or empresa_banner_url)

    return templates.TemplateResponse(
        "prestador.html",
        {
            "request": request,
            "empresa": empresa,
            "kind": kind,
            "quick_facts": build_prestador_quick_facts(empresa, kind),
            "public_reviews": public_reviews,
            "review_avg": review_avg,
            "review_count": review_count,
            "review_submitted": request.query_params.get("review") == "gracias",
            "review_copy": get_review_copy(kind),
            "menu_url": menu_url,
            "menu_fotos_urls": menu_fotos_urls,
            "show_menu_section": show_menu_section,
            "maps_url": normalize_external_url(empresa.maps_url),
            "instagram_contact": normalize_instagram_contact(empresa.instagram),
            "facebook_url": normalize_external_url(empresa.facebook),
            "web_url": normalize_external_url(empresa.web_url),
            "whatsapp_url": normalize_whatsapp_url(empresa.whatsapp),
            "empresa_logo_url": empresa_logo_url,
            "empresa_banner_url": empresa_banner_url,
            "galeria_urls": galeria_urls,
            "gallery_tiles": gallery_tiles,
            "main_photo_url": main_photo_url,
            "has_real_photos": has_real_photos,
            "theme_display_label": theme_display_label,
            "actividad_subgrupos": ACTIVIDADES_SUBGRUPOS if kind == "actividades" else {},
            "service_card_kicker": service_card_kicker,
        },
    )



@app.post("/prestador/{slug}/opiniones")
def crear_opinion_publica(
    slug: str,
    nombre: str = Form(...),
    rating: int = Form(...),
    comentario: str = Form(...),
    contacto: str | None = Form(None),
    tipo_visitante: str | None = Form(None),
    db: Session = Depends(get_db),
):
    empresa = db.query(models.Empresa).filter(models.Empresa.slug == slug).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Prestador no encontrado")
    nombre_limpio = clean_text(nombre, default="")[:80]
    comentario_limpio = clean_text(comentario, default="")[:1000]
    if not nombre_limpio or not comentario_limpio or rating < 1 or rating > 5:
        return RedirectResponse(url=f"/prestador/{slug}?review=error#opiniones", status_code=303)
    review = models.Review(
        prestador_id=empresa.id,
        nombre=nombre_limpio,
        contacto=clean_text(contacto, default="")[:120] or None,
        tipo_visitante=clean_text(tipo_visitante, default="")[:80] or None,
        rating=rating,
        comentario=comentario_limpio,
        fecha=datetime.now(timezone.utc).date().isoformat(),
        estado="pendiente",
        visible=False,
    )
    db.add(review)
    db.commit()
    return RedirectResponse(url=f"/prestador/{slug}?review=gracias#opiniones", status_code=303)

@app.get("/catalogo/{slug}", response_class=HTMLResponse)
def catalogo(
    slug: str,
    request: Request,
    q: str = "",
    categoria: str = "",
    marca: str = "",
    orden: str = "",
    db: Session = Depends(get_db)
):
    empresa = db.query(models.Empresa).filter(models.Empresa.slug == slug).first()
    if not empresa:
        return HTMLResponse("<h1>Prestador no encontrado</h1><p>La ficha turística solicitada no existe.</p>", status_code=404)
    return RedirectResponse(url=f"/prestador/{empresa.slug}", status_code=308)


@app.get("/legacy/catalogo/{slug}", response_class=HTMLResponse)
def legacy_catalogo(
    slug: str,
    request: Request,
    q: str = "",
    categoria: str = "",
    marca: str = "",
    orden: str = "",
    db: Session = Depends(get_db)
):


    empresa = db.query(models.Empresa).filter(models.Empresa.slug == slug).first()
    if not empresa:
        return HTMLResponse("<h1>Empresa no encontrada</h1>", status_code=404)
    lead = get_active_catalog_lead(request, slug, empresa.id, db)
    if not lead:
        return RedirectResponse(url=f"/catalogo/{slug}/acceso", status_code=303)

    query_db = db.query(models.Producto).filter(
        models.Producto.empresa_id == empresa.id,
        models.Producto.activo == True
    )


    if q:
        query_db = query_db.filter(models.Producto.descripcion.ilike(f"%{q}%"))
        
    if categoria:
        query_db = query_db.filter(models.Producto.categoria == categoria)
        
    if marca:
        query_db = query_db.filter(models.Producto.marca == marca)

    
    
    # ORDEN
    if orden == "precio-asc":
        query_db = query_db.order_by(models.Producto.precio.asc())
    elif orden == "precio-desc":
        query_db = query_db.order_by(models.Producto.precio.desc())
    elif orden == "codigo-asc":
         query_db = query_db.order_by(models.Producto.codigo.asc())
    elif orden == "marca-asc":
        query_db = query_db.order_by(models.Producto.marca.asc())

    

    productos = query_db.all()
    price_policy = normalize_price_policy(empresa.politica_precio_catalogo)
    stock_policy = normalize_stock_policy(empresa.politica_stock_catalogo)

    changed_image_urls = False
    for p in productos:
        resolved_url = resolve_producto_imagen_url(p, empresa.slug, migrate_legacy=True)
        if p.imagen_url != resolved_url:
            p.imagen_url = resolved_url
            changed_image_urls = True
        price_display = resolve_price_display(price_policy, p.precio)
        stock_display = resolve_stock_display(stock_policy, p.stock)
        p.catalog_price_numeric = price_display["mostrar_numerico"]
        p.catalog_price_text = price_display["texto"]
        p.catalog_stock_visible = stock_display["visible"]
        p.catalog_stock_text = stock_display["texto"]
        p.catalog_stock_class = stock_display["clase"]

    if changed_image_urls:
        db.commit()



    # TODAS las categorías de la empresa (sin filtros)
    categorias = (
        db.query(models.Producto.categoria)
        .filter(
            models.Producto.empresa_id == empresa.id,
            models.Producto.categoria.isnot(None)
        )
        .distinct()
        .order_by(models.Producto.categoria)
        .all()
    )

    categorias = [c[0] for c in categorias]

    marcas = (
        db.query(models.Producto.marca)
        .filter(
            models.Producto.empresa_id == empresa.id,
            models.Producto.marca.isnot(None)
        )
        .distinct()
        .order_by(models.Producto.marca)
        .all()
    )

    marcas = [m[0] for m in marcas]



    productos_json = [
        {
            "id": p.id,
            "codigo": p.codigo,
            "descripcion": p.descripcion,
            "precio": round(float(p.precio), 2),
            "precio_mostrable": bool(getattr(p, "catalog_price_numeric", False)),
            "precio_texto": getattr(p, "catalog_price_text", "Consultar"),
            "categoria": p.categoria,
            "marca": p.marca,
            "stock": p.stock,
            "stock_visible": bool(getattr(p, "catalog_stock_visible", False)),
            "stock_texto": getattr(p, "catalog_stock_text", ""),
            "stock_clase": getattr(p, "catalog_stock_class", ""),
            "imagen_url": p.imagen_url,
        }
        for p in productos
    ]

    # Export estático para descarga directa (más compatible con navegadores móviles)
    export_path = Path(f"app/static/empresas/{empresa.slug}")
    export_path.mkdir(parents=True, exist_ok=True)
    lista_precios_path = export_path / "lista_precios.json"
    lista_precios_xlsx_path = export_path / "lista_precios.xlsx"

    lista_payload = {
            "empresa": {
                "id": empresa.id,
                "slug": empresa.slug,
                "nombre": empresa.nombre,
                "whatsapp": empresa.whatsapp,
                "politica_precio_catalogo": price_policy,
                "politica_stock_catalogo": stock_policy,
                "theme": normalize_theme(empresa.theme),
            },
        "total_productos": len(productos_json),
        "productos": productos_json,
    }

    with open(lista_precios_path, "w", encoding="utf-8") as f:
        json.dump(lista_payload, f, ensure_ascii=False, indent=2)

    # Export en el mismo formato de subida (Excel)
    df_export = pd.DataFrame(
        [
            {
                "codigo": p.codigo,
                "descripcion": p.descripcion,
                "precio": round(float(p.precio), 2),
                "categoria": p.categoria or "",
                "marca": p.marca or "",
                "stock": p.stock if p.stock is not None else 0,
            }
            for p in productos
        ]
    )
    df_export.to_excel(lista_precios_xlsx_path, index=False)

    import time

    response = templates.TemplateResponse(
        "catalogo.html",
        {
            "request": request,
            "productos": productos,
            "productos_json": productos_json,
            "price_policy": price_policy,
            "stock_policy": stock_policy,
            "empresa": empresa,
            "categorias": categorias,
            "categoria_actual": categoria,
            "marcas": marcas,
            "marca_actual": marca,
            "orden_actual": orden,
            "query": q,
            "ts_download": int(time.time()),
            "app_build": APP_BUILD,
            "empresa_logo_url": get_empresa_logo_url(empresa),
            "empresa_banner_url": get_empresa_banner_url(empresa),
            "galeria_urls": get_empresa_gallery_urls(empresa),
            "lead_data": {
                "nombre": lead.nombre,
                "empresa": lead.empresa,
                "email": lead.email,
                "telefono": lead.telefono or "",
            },
        },
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.post("/catalogo/{slug}/track")
def track_catalog_event(
    slug: str,
    request: Request,
    payload: CatalogEventPayload,
    db: Session = Depends(get_db),
):
    empresa = db.query(models.Empresa).filter(models.Empresa.slug == slug).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    lead = get_active_catalog_lead(request, slug, empresa.id, db)
    if not lead:
        raise HTTPException(status_code=401, detail="Lead no identificado para esta sesión")

    event_type = clean_text(payload.event_type, default="")
    if event_type not in EVENT_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de evento inválido")

    register_catalog_event(
        db=db,
        lead=lead,
        empresa_id=empresa.id,
        event_type=event_type,
        product_code=payload.product_code,
        search_term=payload.search_term,
        metadata=payload.metadata or {},
    )
    return {"ok": True}


@app.get("/catalogo/{slug}/lista_precio.json")
@app.get("/catalogo/{slug}/lista_precios.json")
def descargar_lista_precios_json(slug: str, db: Session = Depends(get_db)):
    empresa = db.query(models.Empresa).filter(models.Empresa.slug == slug).first()
    if not empresa:
        return JSONResponse({"error": "Empresa no encontrada", "slug": slug}, status_code=404)

    productos = (
        db.query(models.Producto)
        .filter(
            models.Producto.empresa_id == empresa.id,
            models.Producto.activo == True
        )
        .order_by(models.Producto.codigo.asc())
        .all()
    )

    data = {
        "empresa": {
            "id": empresa.id,
            "slug": empresa.slug,
            "nombre": empresa.nombre,
            "whatsapp": empresa.whatsapp,
        },
        "total_productos": len(productos),
        "productos": [
            {
                "codigo": p.codigo,
                "descripcion": p.descripcion,
                "categoria": p.categoria,
                "marca": p.marca,
                "precio": round(float(p.precio), 2),
                "stock": p.stock,
                "activo": p.activo,
            }
            for p in productos
        ],
    }

    filename = f"lista_precio_{empresa.slug}.json"
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/catalogo/{slug}/lista_precios.xlsx")
def descargar_lista_precios_xlsx(slug: str, db: Session = Depends(get_db)):
    empresa = db.query(models.Empresa).filter(models.Empresa.slug == slug).first()
    if not empresa:
        return HTMLResponse("<h1>Empresa no encontrada</h1>", status_code=404)

    productos = (
        db.query(models.Producto)
        .filter(
            models.Producto.empresa_id == empresa.id,
            models.Producto.activo == True
        )
        .order_by(models.Producto.codigo.asc())
        .all()
    )

    df = pd.DataFrame([
        {
            "codigo": p.codigo,
            "descripcion": clean_text(p.descripcion),
            "precio": clean_price(p.precio, default=0.0),
            "categoria": clean_text(p.categoria),
            "marca": clean_text(p.marca),
            "stock": clean_stock(p.stock, default=0),
        }
        for p in productos
    ])

    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    filename = f"lista_precios_{empresa.slug}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )



# ---------------------------------------------------
# PDF
# ---------------------------------------------------
@app.post("/pedido/pdf")
async def generar_pdf(data: dict):

    empresa = data.get("empresa", "Pedido")
    items: List[dict] = data.get("items", [])
    buyer: dict = data.get("buyer", {}) or {}

    buyer_nombre = str(buyer.get("nombre", "")).strip()
    buyer_comercio = str(buyer.get("comercio", "")).strip()
    buyer_telefono = str(buyer.get("telefono", "")).strip()
    buyer_direccion = str(buyer.get("direccion", "")).strip()
    buyer_cuit = str(buyer.get("cuit", "")).strip()
    buyer_email = str(buyer.get("email", "")).strip()
    buyer_obs = str(buyer.get("observaciones", "")).strip()

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    y = A4[1] - 40
    x = 40
    bottom_limit = 55

    def draw_line(text: str, font: str = "Helvetica", size: int = 11, indent: int = 0, line_gap: int = 17):
        nonlocal y
        if y <= bottom_limit:
            c.showPage()
            y = A4[1] - 40
        c.setFont(font, size)
        c.drawString(x + indent, y, text)
        y -= line_gap

    draw_line(empresa, font="Helvetica-Bold", size=18, line_gap=30)

    draw_line("Datos del comprador", font="Helvetica-Bold", size=12, line_gap=18)
    draw_line(f"Nombre y apellido: {buyer_nombre or '-'}")
    draw_line(f"Comercio / empresa: {buyer_comercio or '-'}")
    draw_line(f"Teléfono: {buyer_telefono or '-'}")
    draw_line(f"Dirección: {buyer_direccion or '-'}")
    if buyer_cuit:
        draw_line(f"CUIT: {buyer_cuit}")
    if buyer_email:
        draw_line(f"Email: {buyer_email}")
    if buyer_obs:
        draw_line(f"Observaciones: {buyer_obs}")

    y -= 5
    draw_line("Detalle del pedido", font="Helvetica-Bold", size=12, line_gap=18)

    total = 0.0
    has_consult_price = False
    for item in items:
        cantidad = float(item.get("cantidad", 0))
        precio = float(item.get("precio", 0))
        precio_texto = clean_text(item.get("precio_texto", ""), default="")
        precio_mostrable = bool(item.get("precio_mostrable", True))
        subtotal = precio * cantidad
        codigo = item.get("codigo", "")
        descripcion = item.get("descripcion", "")
        draw_line(f'{int(cantidad)}x {codigo} - {descripcion}')
        if precio_mostrable:
            draw_line(f'${precio:.2f} c/u · Subtotal: ${subtotal:.2f}', indent=15, line_gap=19)
            total += subtotal
        else:
            has_consult_price = True
            draw_line(f'Precio: {precio_texto or "Consultar"}', indent=15, line_gap=19)

    y -= 5
    if has_consult_price:
        draw_line("TOTAL ESTIMADO: Consultar", font="Helvetica-Bold", size=14, line_gap=20)
    else:
        draw_line(f"TOTAL ESTIMADO: ${total:.2f}", font="Helvetica-Bold", size=14, line_gap=20)

    c.save()
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=pedido.pdf"}
    )

# ---------------------------------------------------
# DEBUG
# ---------------------------------------------------
@app.get("/debug/empresas")
def listar_empresas(request: Request, db: Session = Depends(get_db)):
    auth = require_admin(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    return [
        {
            "id": e.id,
            "nombre": e.nombre,
            "slug": e.slug,
            "whatsapp": e.whatsapp
        }
        for e in db.query(models.Empresa).all()
    ]

@app.post("/empresa/borrar/{empresa_id}")
def borrar_empresa(request: Request, empresa_id: int, db: Session = Depends(get_db)):
    auth = require_admin(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    empresa = db.query(models.Empresa).filter(models.Empresa.id == empresa_id).first()
    if not empresa:
        return {"error": "Empresa no encontrada"}

    # borrar carpeta física
    empresa_path = Path(f"app/static/empresas/{empresa.slug}")
    if empresa_path.exists():
        shutil.rmtree(empresa_path)
    empresa_media_path = MEDIA_BASE_DIR / empresa.slug
    if empresa_media_path.exists():
        shutil.rmtree(empresa_media_path)

    # borrar DB (productos se borran por cascade)
    db.delete(empresa)
    db.commit()

    return {"status": "ok"}



# ---------------------------------------------------
# DEBUG: LISTAR ARCHIVOS DE IMAGEN DE UNA EMPRESA
# ---------------------------------------------------
@app.get("/debug/imagenes/{slug}")
def debug_imagenes(request: Request, slug: str, db: Session = Depends(get_db)):
    auth = require_admin(request, db)
    if isinstance(auth, RedirectResponse):
        return auth

    slug = (slug or "").strip().lower()
    path = get_productos_media_dir(slug)
    if not path.exists():
        return {"error": "Carpeta no existe", "path": str(path)}

    files = sorted([p.name for p in path.iterdir() if p.is_file()])
    # devolvemos solo los primeros 200 para no explotar la respuesta
    return {"path": str(path), "count": len(files), "files": files[:200]}
