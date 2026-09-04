from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.agenda import CABALANGO_TZ, derive_promotion_label, derived_status, get_home_agenda_events, get_public_activities, group_public_agenda, is_home_eligible, is_publicly_visible, local_datetime, prepare_home_agenda_events, prepare_public_agenda, default_event_schedule, validate_activity
from app.database import Base
from app.models import ActividadAgenda


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


def make_item(db, slug, tipo="evento", publicado=True, start=None, end=None, **kwargs):
    item = ActividadAgenda(tipo=tipo, titulo=slug, slug=slug, categoria=kwargs.pop("categoria", "cultura"), momento=kwargs.pop("momento", "dia"), publicado=publicado, fecha_inicio=start, fecha_fin=end, **kwargs)
    validate_activity(item); db.add(item); db.commit(); return item


def test_visibility_groups_status_and_timezone(db):
    now = datetime(2026, 8, 10, 20, 0, tzinfo=CABALANGO_TZ)
    today = make_item(db, "hoy", start=datetime(2026,8,10,19), end=datetime(2026,8,10,22))
    future = make_item(db, "futuro", start=datetime(2026,8,11,10), end=datetime(2026,8,11,12))
    expired = make_item(db, "vencido", start=datetime(2026,8,9,10), end=datetime(2026,8,9,12))
    draft = make_item(db, "borrador", publicado=False, start=datetime(2026,8,11,10), end=datetime(2026,8,11,12))
    activity = make_item(db, "yoga", tipo="actividad", start=None, end=None, destacado=True)
    make_item(db, "oculta", tipo="actividad", publicado=False, start=None, end=None)
    public = get_public_activities(db, now=now); slugs = {i.slug for i in public}
    assert slugs == {"hoy", "futuro", "yoga"}
    groups = group_public_agenda(public, now=now)
    assert today in groups["today"] and future in groups["upcoming"] and activity in groups["activities"]
    assert derived_status(today, now) == "En curso"
    assert derived_status(future, now) == "Próximo"
    assert derived_status(expired, now) == "Finalizado"
    assert derived_status(draft, now) == "Borrador"
    assert now.utcoffset().total_seconds() == -3 * 3600


@pytest.mark.parametrize(("estado", "publicado", "expected"), [
    ("cancelado", False, "Cancelado"),
    ("realizado", False, "Realizado"),
    ("borrador", True, "Borrador"),
    ("programado", False, "Borrador"),
])
def test_persisted_status_precedes_editorial_publication(estado, publicado, expected):
    item = ActividadAgenda(
        tipo="evento", titulo="Estado", slug=f"estado-{estado}-{publicado}",
        categoria="otros", momento="dia", publicado=publicado, estado=estado,
        fecha_inicio=datetime(2026, 8, 11, 10), fecha_fin=datetime(2026, 8, 11, 12),
    )
    assert derived_status(item, datetime(2026, 8, 10, 12, tzinfo=CABALANGO_TZ)) == expected


def test_invalid_event_range_is_rejected():
    item = ActividadAgenda(tipo="evento", titulo="Mal", slug="mal", categoria="otros", momento="dia", publicado=True, fecha_inicio=datetime(2026,8,10,20), fecha_fin=datetime(2026,8,10,19))
    with pytest.raises(ValueError, match="anterior"):
        validate_activity(item)


@pytest.mark.parametrize(("start", "end"), [
    (None, None),
    (datetime(2026, 9, 10, 18), None),
    (datetime(2026, 9, 10, 18), datetime(2026, 9, 10, 22)),
])
def test_event_draft_accepts_unconfirmed_dates(start, end):
    item = ActividadAgenda(
        tipo="evento", titulo="A confirmar", slug="a-confirmar", categoria="otros",
        momento="dia", estado="borrador", fecha_inicio=start, fecha_fin=end,
    )
    validate_activity(item)


@pytest.mark.parametrize("estado", ["programado", "reprogramado"])
def test_active_event_states_still_require_both_dates(estado):
    item = ActividadAgenda(
        tipo="evento", titulo="Sin fecha", slug=f"sin-fecha-{estado}", categoria="otros",
        momento="dia", estado=estado,
    )
    with pytest.raises(ValueError, match="requieren fecha"):
        validate_activity(item)


def test_published_home_enabled_draft_is_never_eligible_or_visible():
    item = ActividadAgenda(
        tipo="evento", titulo="Borrador", slug="borrador-oculto", categoria="otros",
        momento="dia", estado="borrador", publicado=True, mostrar_en_home=True,
    )
    now = datetime(2026, 9, 1, 12, tzinfo=CABALANGO_TZ)
    assert not is_publicly_visible(item, now)
    assert not is_home_eligible(item, now)


def test_today_filter_intersects_full_day(db):
    now = datetime(2026,8,10,12,tzinfo=CABALANGO_TZ)
    spanning = make_item(db,"continuado",start=datetime(2026,8,9,23),end=datetime(2026,8,10,14))
    assert spanning in get_public_activities(db, cuando="hoy", now=now)


def test_public_moment_filters_expand_day_only_for_permanent_activities(db):
    now = datetime(2026, 8, 10, 12, tzinfo=CABALANGO_TZ)
    activities = {
        moment: make_item(
            db, f"actividad-{moment}", tipo="actividad", start=None, end=None,
            momento=moment,
        )
        for moment in ("dia", "atardecer", "todo_el_dia", "noche")
    }
    events = {
        moment: make_item(
            db, f"evento-{moment}", momento=moment,
            start=datetime(2026, 8, 11, 10), end=datetime(2026, 8, 11, 12),
        )
        for moment in ("dia", "atardecer", "todo_el_dia")
    }

    daytime = set(get_public_activities(db, momento="dia", now=now))
    assert {activities[moment] for moment in ("dia", "atardecer", "todo_el_dia")} <= daytime
    assert activities["noche"] not in daytime
    assert events["dia"] in daytime
    assert events["atardecer"] not in daytime
    assert events["todo_el_dia"] not in daytime

    nighttime = set(get_public_activities(db, momento="noche", now=now))
    assert activities["noche"] in nighttime
    assert all(activities[moment] not in nighttime for moment in ("dia", "atardecer", "todo_el_dia"))


def test_seasonal_activity_visibility_status_and_grouping(db):
    now = datetime(2026, 8, 10, 20, 0, tzinfo=CABALANGO_TZ)
    permanent = make_item(db, "permanente", tipo="actividad", start=None, end=None)
    future = make_item(db, "temporada-futura", tipo="actividad", start=datetime(2026, 9, 1), end=datetime(2026, 9, 30))
    current = make_item(db, "temporada-vigente", tipo="actividad", start=datetime(2026, 8, 1), end=datetime(2026, 8, 31), momento="noche")
    expired = make_item(db, "temporada-vencida", tipo="actividad", start=datetime(2026, 7, 1), end=datetime(2026, 7, 31))
    only_start = make_item(db, "desde-agosto", tipo="actividad", start=datetime(2026, 8, 1), end=None)
    only_end = make_item(db, "hasta-agosto", tipo="actividad", start=None, end=datetime(2026, 8, 31))

    public = get_public_activities(db, now=now)
    assert {item.slug for item in public} == {"permanente", "temporada-vigente", "desde-agosto", "hasta-agosto"}
    assert derived_status(permanent, now) == "Publicada"
    assert derived_status(future, now) == "Próxima"
    assert derived_status(current, now) == "Publicada"
    assert derived_status(expired, now) == "Finalizada"

    groups = group_public_agenda(public, now=now)
    assert current in groups["activities"]
    assert current not in groups["today"]
    assert current not in groups["night"]


def test_activity_with_invalid_validity_range_is_rejected():
    item = ActividadAgenda(tipo="actividad", titulo="Temporada inválida", slug="temporada-invalida", categoria="otros", momento="dia", publicado=True, fecha_inicio=datetime(2026, 8, 10, 20), fecha_fin=datetime(2026, 8, 10, 19))
    with pytest.raises(ValueError, match="anterior"):
        validate_activity(item)


def scheduled_event(**kwargs):
    values = dict(tipo="evento", titulo="Programado", slug="programado", categoria="cultura", momento="dia",
                  publicado=True, estado="programado", mostrar_en_home=True,
                  fecha_inicio=datetime(2026, 11, 21, 18), fecha_fin=datetime(2026, 11, 21, 22),
                  publicar_desde=datetime(2026, 11, 7, 18), destacar_home_desde=datetime(2026, 11, 14, 18),
                  ocultar_desde=datetime(2026, 11, 21, 22))
    values.update(kwargs)
    return ActividadAgenda(**values)


def test_model_defaults_constraints_and_timezone_fields(db):
    item = ActividadAgenda(tipo="actividad", titulo="Default", slug="default", categoria="otros", momento="dia")
    db.add(item); db.commit(); db.refresh(item)
    assert (item.oficial, item.estado, item.mostrar_en_home, item.prioridad_home) == (False, "programado", False, 0)
    aware = datetime(2026, 11, 7, 18, tzinfo=CABALANGO_TZ)
    item.publicar_desde = aware; item.prioridad_home = 100; db.commit()
    assert local_datetime(item.publicar_desde) == aware
    item.estado = "HOY"; db.add(item)
    with pytest.raises(IntegrityError):
        db.commit()


def test_default_event_schedule_uses_cabalango_time():
    start = datetime(2026, 11, 21, 18, tzinfo=CABALANGO_TZ)
    end = datetime(2026, 11, 21, 22, tzinfo=CABALANGO_TZ)
    assert default_event_schedule(start, end) == {
        "publicar_desde": None,
        "destacar_home_desde": datetime(2026, 11, 14, 18, tzinfo=CABALANGO_TZ),
        "ocultar_desde": end,
    }


@pytest.mark.parametrize(("changes", "now", "expected"), [
    ({}, datetime(2026, 11, 7, 17, 59), False),
    ({}, datetime(2026, 11, 7, 18), True),
    ({}, datetime(2026, 11, 20, 12), True),
    ({}, datetime(2026, 11, 21, 22, 1), False),
    ({"publicado": False}, datetime(2026, 11, 20), False),
    ({"estado": "cancelado"}, datetime(2026, 11, 20), False),
    ({"estado": "borrador"}, datetime(2026, 11, 20), False),
    ({"estado": "realizado"}, datetime(2026, 11, 20), False),
    ({"estado": "reprogramado"}, datetime(2026, 11, 20), True),
])
def test_scheduled_public_visibility(changes, now, expected):
    assert is_publicly_visible(scheduled_event(**changes), now.replace(tzinfo=CABALANGO_TZ)) is expected


def test_legacy_null_windows_remain_visible():
    item = scheduled_event(publicar_desde=None, ocultar_desde=None)
    assert is_publicly_visible(item, datetime(2026, 11, 20, tzinfo=CABALANGO_TZ))


@pytest.mark.parametrize(("changes", "now", "expected"), [
    ({"mostrar_en_home": False}, datetime(2026, 11, 20), False),
    ({}, datetime(2026, 11, 14, 17, 59), False),
    ({}, datetime(2026, 11, 14, 18), True),
    ({"estado": "cancelado"}, datetime(2026, 11, 20), False),
    ({"estado": "realizado"}, datetime(2026, 11, 20), False),
    ({"publicado": False}, datetime(2026, 11, 20), False),
    ({}, datetime(2026, 11, 21, 22, 1), False),
])
def test_home_eligibility(changes, now, expected):
    assert is_home_eligible(scheduled_event(**changes), now.replace(tzinfo=CABALANGO_TZ)) is expected


@pytest.mark.parametrize(("start", "end", "now", "label"), [
    ((10, 10), (10, 22), (10, 12), "EN CURSO"),
    ((10, 18), (10, 22), (10, 12), "HOY EN CABALANGO"),
    ((11, 18), (11, 22), (10, 12), "MAÑANA"),
    ((15, 18), (15, 22), (10, 12), "ESTA SEMANA"),
    ((20, 18), (20, 22), (10, 12), "PRÓXIMAMENTE"),
    ((30, 18), (30, 22), (10, 12), None),
])
def test_promotion_labels(start, end, now, label):
    dt = lambda parts: datetime(2026, 11, *parts, tzinfo=CABALANGO_TZ)
    assert derive_promotion_label(scheduled_event(fecha_inicio=dt(start), fecha_fin=dt(end)), dt(now)) == label


def add_home_event(db, slug, start, end, **kwargs):
    item = scheduled_event(
        titulo=slug.replace("-", " ").title(), slug=slug,
        fecha_inicio=start.replace(tzinfo=None), fecha_fin=end.replace(tzinfo=None),
        destacar_home_desde=kwargs.pop("destacar_home_desde", datetime(2026, 8, 1)),
        ocultar_desde=kwargs.pop("ocultar_desde", end.replace(tzinfo=None)), **kwargs,
    )
    db.add(item)
    db.commit()
    return item


def test_home_selection_uses_exact_window_and_excludes_ineligible_states(db):
    start = datetime(2026, 9, 1, 14, tzinfo=CABALANGO_TZ)
    end = datetime(2026, 9, 1, 18, tzinfo=CABALANGO_TZ)
    add_home_event(db, "ventana-exacta", start, end, destacar_home_desde=datetime(2026, 8, 25, 14))
    for slug, changes in (
        ("sin-home", {"mostrar_en_home": False}), ("sin-publicar", {"publicado": False}),
        ("borrador", {"estado": "borrador"}), ("cancelado", {"estado": "cancelado"}),
        ("realizado", {"estado": "realizado"}),
        ("ocultado", {"ocultar_desde": datetime(2026, 8, 25, 13)}),
    ):
        add_home_event(db, slug, start, end, **changes)

    selected = lambda at: [item.slug for item in get_home_agenda_events(db, now=at)]
    assert "ventana-exacta" not in selected(datetime(2026, 8, 25, 13, 59, tzinfo=CABALANGO_TZ))
    assert selected(datetime(2026, 8, 25, 14, tzinfo=CABALANGO_TZ)) == ["ventana-exacta"]
    assert selected(end) == ["ventana-exacta"]
    assert "ventana-exacta" not in selected(datetime(2026, 9, 1, 18, 1, tzinfo=CABALANGO_TZ))


def test_home_ranking_prioritizes_urgency_then_priority_and_limits_to_three(db):
    now = datetime(2026, 8, 10, 12, tzinfo=CABALANGO_TZ)
    add_home_event(db, "lejano-prioridad-100", now.replace(day=20, hour=18), now.replace(day=20, hour=20), prioridad_home=100)
    add_home_event(db, "hoy-prioridad-10", now.replace(hour=18), now.replace(hour=20), prioridad_home=10)
    add_home_event(db, "semana-prioridad-20", now.replace(day=15, hour=18), now.replace(day=15, hour=20), prioridad_home=20)
    add_home_event(db, "semana-prioridad-90", now.replace(day=15, hour=19), now.replace(day=15, hour=21), prioridad_home=90)
    add_home_event(db, "manana", now.replace(day=11, hour=18), now.replace(day=11, hour=20))

    selected = get_home_agenda_events(db, now=now)
    cards = prepare_home_agenda_events(selected, now=now)
    expected = ["hoy-prioridad-10", "manana", "semana-prioridad-90"]
    assert [item.slug for item in selected] == expected
    assert [card["item"].slug for card in cards] == expected
    assert len(selected) == 3


def test_distant_event_without_embargo_is_public_and_prepared(db):
    now = datetime(2026, 9, 1, 12, tzinfo=CABALANGO_TZ)
    distant = make_item(
        db, "diciembre", start=datetime(2026, 12, 12, 18),
        end=datetime(2026, 12, 12, 22), publicar_desde=None,
    )

    assert is_publicly_visible(distant, now)
    public = get_public_activities(db, now=now)
    assert distant in public
    assert [card["item"] for card in prepare_public_agenda(public, now=now)["events"]] == [distant]


def test_manual_agenda_embargo_starts_at_explicit_datetime():
    item = scheduled_event(
        fecha_inicio=datetime(2026, 12, 12, 18),
        fecha_fin=datetime(2026, 12, 12, 22),
        publicar_desde=datetime(2026, 12, 1, 0),
        ocultar_desde=datetime(2026, 12, 12, 22),
    )

    assert not is_publicly_visible(item, datetime(2026, 9, 1, tzinfo=CABALANGO_TZ))
    assert is_publicly_visible(item, datetime(2026, 12, 1, tzinfo=CABALANGO_TZ))


def test_public_agenda_has_no_default_limit_and_keeps_chronological_order():
    events = [
        scheduled_event(
            titulo=f"Evento {index}", slug=f"evento-{index}",
            fecha_inicio=datetime(2026, 12, 1 + index, 18),
            fecha_fin=datetime(2026, 12, 1 + index, 22),
        )
        for index in reversed(range(9))
    ]

    agenda = prepare_public_agenda(events, now=datetime(2026, 9, 1, tzinfo=CABALANGO_TZ))

    assert [card["item"].slug for card in agenda["events"]] == [f"evento-{index}" for index in range(9)]
    assert agenda["has_more_events"] is False
    limited = prepare_public_agenda(events, now=datetime(2026, 9, 1, tzinfo=CABALANGO_TZ), limit=3)
    assert len(limited["events"]) == 3
    assert limited["has_more_events"] is True
