from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app import models

CABALANGO_TZ = ZoneInfo("America/Argentina/Cordoba")
CATEGORIES = {
    "naturaleza": "Naturaleza", "bienestar": "Bienestar", "cultura": "Cultura",
    "entretenimiento": "Entretenimiento", "familiar": "Para chicos", "deporte": "Deporte",
    "artesania": "Artesanía", "musica": "Música", "otros": "Otros",
}
MOMENTS = {"dia": "Día", "atardecer": "Atardecer", "noche": "Noche", "todo_el_dia": "Todo el día"}
TYPES = {"actividad": "Actividad permanente", "evento": "Evento con fecha"}
PERSISTED_STATES = {
    "borrador": "Borrador", "programado": "Programado", "reprogramado": "Reprogramado",
    "cancelado": "Cancelado", "realizado": "Realizado",
}


def now_cabalango() -> datetime:
    return datetime.now(CABALANGO_TZ)


def local_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=CABALANGO_TZ) if value.tzinfo is None else value.astimezone(CABALANGO_TZ)


def validate_activity(item: models.ActividadAgenda) -> None:
    # SQLAlchemy column defaults are normally applied at INSERT time; make the
    # domain validator useful for brand-new, not-yet-flushed instances too.
    if item.estado is None:
        item.estado = "programado"
    if item.prioridad_home is None:
        item.prioridad_home = 0
    if item.tipo not in TYPES:
        raise ValueError("Tipo inválido")
    if item.categoria not in CATEGORIES or item.momento not in MOMENTS:
        raise ValueError("Categoría o momento inválido")
    if item.tipo == "evento":
        if not item.fecha_inicio or not item.fecha_fin:
            raise ValueError("Los eventos requieren fecha y hora de inicio y finalización")
    if item.fecha_inicio and item.fecha_fin and local_datetime(item.fecha_fin) < local_datetime(item.fecha_inicio):
        raise ValueError("La finalización no puede ser anterior al inicio")
    if item.estado not in PERSISTED_STATES:
        raise ValueError("Estado inválido")
    if not 0 <= item.prioridad_home <= 100:
        raise ValueError("La prioridad en portada debe estar entre 0 y 100")
    end = local_datetime(item.fecha_fin)
    start = local_datetime(item.fecha_inicio)
    if end and item.publicar_desde and local_datetime(item.publicar_desde) > end:
        raise ValueError("La publicación no puede comenzar después de la finalización")
    if end and item.destacar_home_desde and local_datetime(item.destacar_home_desde) > end:
        raise ValueError("La promoción en portada no puede comenzar después de la finalización")
    if start and item.ocultar_desde and local_datetime(item.ocultar_desde) < start:
        raise ValueError("La actividad no puede ocultarse antes de comenzar")


def publication_window_for_event(fecha_inicio: datetime, fecha_fin: datetime) -> dict[str, datetime]:
    """Return Cabalango-local editorial suggestions; it does not mutate an event."""
    start, end = local_datetime(fecha_inicio), local_datetime(fecha_fin)
    return {
        "publicar_desde": start - timedelta(days=14),
        "destacar_home_desde": start - timedelta(days=7),
        "ocultar_desde": end,
    }


def is_publicly_visible(item: models.ActividadAgenda, now: datetime) -> bool:
    now = local_datetime(now)
    if not item.publicado:
        return False
    if item.tipo == "actividad":
        return ((not item.fecha_inicio or now >= local_datetime(item.fecha_inicio))
                and (not item.fecha_fin or now <= local_datetime(item.fecha_fin)))
    if item.tipo != "evento" or item.estado in {"borrador", "cancelado", "realizado"} or not item.fecha_fin:
        return False
    return ((not item.publicar_desde or now >= local_datetime(item.publicar_desde))
            and (not item.ocultar_desde or now <= local_datetime(item.ocultar_desde))
            and now <= local_datetime(item.fecha_fin))


def is_home_eligible(item: models.ActividadAgenda, now: datetime) -> bool:
    now = local_datetime(now)
    return bool(
        item.tipo == "evento" and item.publicado and item.mostrar_en_home
        and item.estado not in {"borrador", "cancelado", "realizado"}
        and item.destacar_home_desde and now >= local_datetime(item.destacar_home_desde)
        and item.fecha_fin and now <= local_datetime(item.fecha_fin)
        and (not item.ocultar_desde or now <= local_datetime(item.ocultar_desde))
    )


def derive_promotion_label(item: models.ActividadAgenda, now: datetime) -> str | None:
    now = local_datetime(now)
    if item.tipo != "evento" or item.estado in {"borrador", "cancelado", "realizado"}:
        return None
    start, end = local_datetime(item.fecha_inicio), local_datetime(item.fecha_fin)
    if not start or not end or now > end:
        return None
    if start <= now <= end:
        return "EN CURSO"
    days = (start.date() - now.date()).days
    if days == 0:
        return "HOY EN CABALANGO"
    if days == 1:
        return "MAÑANA"
    if 2 <= days <= 7:
        return "ESTA SEMANA"
    if 8 <= days <= 14:
        return "PRÓXIMAMENTE"
    return None


def derived_status(item: models.ActividadAgenda, now: datetime | None = None) -> str:
    now = local_datetime(now or now_cabalango())
    if item.estado == "cancelado":
        return "Cancelado"
    if item.estado == "realizado":
        return "Realizado"
    if item.estado == "borrador":
        return "Borrador"
    if not item.publicado:
        return "Borrador"
    if item.tipo == "actividad":
        if item.fecha_inicio and now < local_datetime(item.fecha_inicio):
            return "Próxima"
        if item.fecha_fin and now > local_datetime(item.fecha_fin):
            return "Finalizada"
        return "Publicada"
    if now > local_datetime(item.fecha_fin):
        return "Finalizado"
    if item.estado == "reprogramado":
        return "Reprogramado"
    if now < local_datetime(item.fecha_inicio):
        return "Próximo"
    return "En curso"


def get_public_activities(db: Session, *, categoria="", momento="", cuando="", now=None):
    now = local_datetime(now or now_cabalango())
    items = db.query(models.ActividadAgenda).filter(models.ActividadAgenda.publicado.is_(True)).all()
    items = [item for item in items if is_publicly_visible(item, now)]
    if categoria in CATEGORIES:
        items = [i for i in items if i.categoria == categoria]
    if momento in MOMENTS:
        items = [i for i in items if i.momento == momento]
    if cuando == "hoy":
        start, end = datetime.combine(now.date(), time.min, CABALANGO_TZ), datetime.combine(now.date(), time.max, CABALANGO_TZ)
        items = [i for i in items if i.tipo == "evento" and local_datetime(i.fecha_inicio) <= end and local_datetime(i.fecha_fin) >= start]
    return items


def group_public_agenda(items, now=None):
    now = local_datetime(now or now_cabalango())
    start, end = datetime.combine(now.date(), time.min, CABALANGO_TZ), datetime.combine(now.date(), time.max, CABALANGO_TZ)
    events = [i for i in items if i.tipo == "evento"]
    today = sorted([i for i in events if local_datetime(i.fecha_inicio) <= end and local_datetime(i.fecha_fin) >= start], key=lambda i: local_datetime(i.fecha_inicio))
    night = [i for i in today if i.momento == "noche"]
    today_regular = [i for i in today if i not in night]
    upcoming = sorted([i for i in events if local_datetime(i.fecha_inicio) > end], key=lambda i: local_datetime(i.fecha_inicio))[:6]
    permanent = sorted([i for i in items if i.tipo == "actividad"], key=lambda i: (not i.destacado, i.orden is None, i.orden or 0, i.titulo.casefold()))
    return {"today": today_regular, "night": night, "upcoming": upcoming, "activities": permanent}
