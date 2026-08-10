from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agenda import CABALANGO_TZ, derived_status, get_public_activities, group_public_agenda, validate_activity
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


def test_invalid_event_range_is_rejected():
    item = ActividadAgenda(tipo="evento", titulo="Mal", slug="mal", categoria="otros", momento="dia", publicado=True, fecha_inicio=datetime(2026,8,10,20), fecha_fin=datetime(2026,8,10,19))
    with pytest.raises(ValueError, match="anterior"):
        validate_activity(item)


def test_today_filter_intersects_full_day(db):
    now = datetime(2026,8,10,12,tzinfo=CABALANGO_TZ)
    spanning = make_item(db,"continuado",start=datetime(2026,8,9,23),end=datetime(2026,8,10,14))
    assert spanning in get_public_activities(db, cuando="hoy", now=now)
