from datetime import datetime, time
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


def now_cabalango() -> datetime:
    return datetime.now(CABALANGO_TZ)


def local_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=CABALANGO_TZ) if value.tzinfo is None else value.astimezone(CABALANGO_TZ)


def validate_activity(item: models.ActividadAgenda) -> None:
    if item.tipo not in TYPES:
        raise ValueError("Tipo inválido")
    if item.categoria not in CATEGORIES or item.momento not in MOMENTS:
        raise ValueError("Categoría o momento inválido")
    if item.tipo == "evento":
        if not item.fecha_inicio or not item.fecha_fin:
            raise ValueError("Los eventos requieren fecha y hora de inicio y finalización")
    if item.fecha_inicio and item.fecha_fin and local_datetime(item.fecha_fin) < local_datetime(item.fecha_inicio):
        raise ValueError("La finalización no puede ser anterior al inicio")


def derived_status(item: models.ActividadAgenda, now: datetime | None = None) -> str:
    now = local_datetime(now or now_cabalango())
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
    if now < local_datetime(item.fecha_inicio):
        return "Próximo"
    return "En curso"


def get_public_activities(db: Session, *, categoria="", momento="", cuando="", now=None):
    now = local_datetime(now or now_cabalango())
    items = db.query(models.ActividadAgenda).filter(models.ActividadAgenda.publicado.is_(True)).all()
    items = [
        item for item in items
        if (
            item.tipo == "evento" and item.fecha_fin and local_datetime(item.fecha_fin) >= now
        ) or (
            item.tipo == "actividad"
            and (not item.fecha_inicio or now >= local_datetime(item.fecha_inicio))
            and (not item.fecha_fin or now <= local_datetime(item.fecha_fin))
        )
    ]
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
