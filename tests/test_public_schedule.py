import pytest

from app.main import build_public_schedule_lines


@pytest.mark.parametrize(
    ("schedule", "expected"),
    [
        ("Días: Lunes, Martes, Miércoles, Jueves, Viernes, Sábado, Domingo", ["Todos los días"]),
        ("Días: Lunes a domingo", ["Todos los días"]),
        ("Días: Lunes, Martes, Miércoles, Jueves, Viernes, Sábado", ["Lunes a sábado"]),
        ("Días: Lunes, Martes, Miércoles, Jueves, Viernes", ["Lunes a viernes"]),
        ("Días: Lunes, Miércoles, Viernes", ["Lunes, Miércoles, Viernes"]),
        ("Todo el año: Sí", ["Abierto todo el año"]),
        ("Todo el año: No", ["Temporada limitada"]),
        ("Horarios: 9 hs | 18 hs | 20:30 hs", ["9:00", "18:00", "20:30"]),
        ("Horarios: de 9 a 13 y de 17 a 21", ["9:00 a 13:00 y 17:00 a 21:00"]),
    ],
)
def test_public_schedule_safe_normalizations(schedule, expected):
    assert build_public_schedule_lines(schedule) == expected


def test_lavadero_rita_reuses_confirmed_saturday_hours():
    schedule = (
        "Días: Lunes, Martes, Miércoles, Jueves, Viernes, Sábado |\n"
        "Horarios: Lunes a viernes de 9 a 13 y de 17 a 21. sábados el mismo horario |\n"
        "Todo el año: Sí"
    )

    assert build_public_schedule_lines(schedule) == [
        "Lunes a sábado",
        "9:00 a 13:00 y 17:00 a 21:00",
        "Abierto todo el año",
    ]


def test_repeated_saturday_hours_are_not_inferred_without_supporting_days():
    schedule = (
        "Días: Lunes, Martes, Miércoles, Jueves, Viernes | "
        "Horarios: Lunes a viernes de 9 a 13. sábados el mismo horario"
    )

    assert build_public_schedule_lines(schedule) == [
        "Lunes a viernes",
        "Lunes a viernes 9:00 a 13:00. sábados el mismo horario",
    ]


def test_camping_schedule_is_preserved():
    schedule = (
        "Todos los días | Invierno: 10:00 a 18:00 | "
        "Verano: 9:00 a 20:30 | Abierto todo el año"
    )

    assert build_public_schedule_lines(schedule) == [
        "Todos los días",
        "Invierno: 10:00 a 18:00",
        "Verano: 9:00 a 20:30",
        "Abierto todo el año",
    ]


def test_already_normalized_schedule_is_idempotent():
    schedule = "Lunes a sábado | 9:00 a 13:00 y 17:00 a 21:00 | Abierto todo el año"

    lines = build_public_schedule_lines(schedule)

    assert lines == ["Lunes a sábado", "9:00 a 13:00 y 17:00 a 21:00", "Abierto todo el año"]
    assert build_public_schedule_lines(" | ".join(lines)) == lines
