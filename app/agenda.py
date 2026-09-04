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
    if item.tipo == "evento" and item.estado != "borrador":
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


def default_event_schedule(fecha_inicio: datetime, fecha_fin: datetime) -> dict[str, datetime | None]:
    """Return Cabalango-local editorial defaults; it does not mutate an event."""
    start, end = local_datetime(fecha_inicio), local_datetime(fecha_fin)
    return {
        "publicar_desde": None,
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


_HOME_LABEL_ORDER = {
    "EN CURSO": 0,
    "HOY EN CABALANGO": 1,
    "MAÑANA": 2,
    "ESTA SEMANA": 3,
    "PRÓXIMAMENTE": 4,
    None: 5,
}


def get_home_agenda_events(db: Session, now=None, limit=3):
    """Return the eligible events for Home in editorial urgency order."""
    now = local_datetime(now or now_cabalango())
    candidates = db.query(models.ActividadAgenda).filter(
        models.ActividadAgenda.tipo == "evento",
        models.ActividadAgenda.publicado.is_(True),
        models.ActividadAgenda.mostrar_en_home.is_(True),
    ).all()
    eligible = [item for item in candidates if is_home_eligible(item, now)]
    eligible.sort(key=lambda item: (
        _HOME_LABEL_ORDER[derive_promotion_label(item, now)],
        -(item.prioridad_home or 0),
        local_datetime(item.fecha_inicio) or datetime.max.replace(tzinfo=CABALANGO_TZ),
        not bool(item.oficial),
        not bool(item.destacado),
        item.titulo.casefold(),
    ))
    return eligible[:max(0, limit)]


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
        if momento == "dia":
            daytime_activity_moments = {"dia", "atardecer", "todo_el_dia"}
            items = [
                i for i in items
                if (
                    i.tipo == "actividad" and i.momento in daytime_activity_moments
                ) or (
                    i.tipo != "actividad" and i.momento == momento
                )
            ]
        else:
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


_MONTHS = ("ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC")


def prepare_event_card(item, now):
    """Build presentation data for one event without changing collection order."""
    start, end = local_datetime(item.fecha_inicio), local_datetime(item.fecha_fin)
    if start.date() == end.date():
        date_label = f"{start.day} {_MONTHS[start.month - 1]}"
    elif start.month == end.month:
        date_label = f"{start.day}–{end.day} {_MONTHS[start.month - 1]}"
    else:
        date_label = f"{start.day} {_MONTHS[start.month - 1]} — {end.day} {_MONTHS[end.month - 1]}"

    schedule = item.horarios.strip() if item.horarios and item.horarios.strip() else None
    if not schedule and start.time() != time.min and end.time() != time.min:
        schedule = f"{start:%H:%M}–{end:%H:%M} hs"
    return {
        "item": item,
        "label": derive_promotion_label(item, now),
        "date_label": date_label,
        "datetime": start.isoformat(),
        "schedule": schedule,
    }


def prepare_home_agenda_events(items, now=None):
    """Build compact Home cards from events already selected by the domain."""
    now = local_datetime(now or now_cabalango())
    cards = [prepare_event_card(item, now) for item in items[:3]]
    for card in cards:
        card["category"] = CATEGORIES.get(card["item"].categoria, card["item"].categoria)
    return cards


def prepare_public_agenda(items, now=None, limit=None):
    """Build display-only data for the public agenda without duplicating visibility rules."""
    now = local_datetime(now or now_cabalango())
    events = sorted(
        (item for item in items if item.tipo == "evento"),
        key=lambda item: (
            local_datetime(item.fecha_inicio), not bool(item.oficial),
            not bool(item.destacado), item.orden is None, item.orden or 0,
            item.titulo.casefold(),
        ),
    )
    selected_events = events if limit is None else events[:max(0, limit)]
    cards = [prepare_event_card(item, now) for item in selected_events]

    activities = sorted(
        (item for item in items if item.tipo == "actividad"),
        key=lambda item: (not item.destacado, item.orden is None, item.orden or 0, item.titulo.casefold()),
    )
    return {
        "events": cards,
        "activities": activities,
        "has_more_events": limit is not None and len(events) > max(0, limit),
    }
