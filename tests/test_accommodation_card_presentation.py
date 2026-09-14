from pathlib import Path
from types import SimpleNamespace

import pytest

from app import main


def accommodation(**values):
    defaults = {
        "nombre": "Alojamiento", "slug": "alojamiento", "theme": "alojamiento",
        "subtipo": "Cabaña", "capacidad": None, "habitaciones": None, "banos": None,
        "alojamiento_modalidad": None, "alojamiento_detalle_unidades": None,
        "alojamiento_habitaciones_unidades": None, "precio_desde": None,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_individual_card_summary_is_compact_and_omits_empty_fields():
    full = accommodation(capacidad="4", habitaciones="1", banos="1")
    partial = accommodation(capacidad="4", habitaciones=None, banos="")

    assert main.build_accommodation_card_summary(full) == "4 personas · 1 habitación · 1 baño"
    assert main.build_accommodation_card_summary(partial) == "4 personas"
    assert "· ·" not in main.build_accommodation_card_summary(partial)


def test_complex_summary_reuses_safe_unit_facts():
    company = accommodation(
        alojamiento_modalidad="complejo",
        alojamiento_detalle_unidades="Cabañas para 2–8 personas",
        alojamiento_habitaciones_unidades="[1, 2, 3]",
        habitaciones="20",
    )

    assert main.build_accommodation_card_summary(company) == (
        "Cabañas para 2–8 personas · 1, 2 y 3 habitaciones según unidad"
    )
    assert "20 habitaciones" not in main.build_accommodation_card_summary(company)


def test_camping_summary_keeps_its_specific_capacity_treatment():
    assert main.build_accommodation_card_summary(
        accommodation(subtipo="Camping", capacidad="400", habitaciones="12")
    ) == "Hasta 400 personas"


@pytest.mark.parametrize(("raw", "value", "kind"), [
    (None, "A consultar", "consult"),
    ("   ", "A consultar", "consult"),
    ("Consultar Precio", "A consultar", "consult"),
    ("Precio a consultar", "A consultar", "consult"),
    ("Entre $25000 y $35000 por persona", "$25.000–$35.000 por persona", "range"),
    ("20000 por persona", "Desde $20.000 por persona", "from"),
    ("Desde $25000 por persona", "Desde $25.000 por persona", "from"),
    ("10.000 por persona", "Desde $10.000 por persona", "from"),
])
def test_card_rate_normalizes_only_clear_peso_patterns(raw, value, kind):
    rate = main.build_accommodation_card_rate(accommodation(precio_desde=raw))
    assert rate["value"] == value
    assert rate["kind"] == kind
    assert "Desde Desde" not in rate["value"]
    assert "Desde Consultar" not in rate["value"]


def test_card_rate_extracts_a_recognized_month_as_discreet_note():
    rate = main.build_accommodation_card_rate(
        accommodation(precio_desde="$25.000 por persona (septiembre)")
    )
    assert rate == {
        "value": "Desde $25.000 por persona",
        "note": "Valor informado para septiembre",
        "kind": "from",
    }


def test_card_rate_preserves_foreign_currency_and_unknown_text():
    assert main.build_accommodation_card_rate(
        accommodation(precio_desde="USD 50 por noche")
    )["value"] == "USD 50 por noche"
    assert main.build_accommodation_card_rate(
        accommodation(precio_desde="Consultar disponibilidad y tarifa especial")
    )["value"] == "Consultar disponibilidad y tarifa especial"


def test_template_keeps_rate_footer_actions_and_three_amenities_contract():
    template = Path("app/templates/partials/alojamiento_card.html").read_text(encoding="utf-8")
    assert "build_accommodation_card_summary(empresa)" in template
    assert "build_accommodation_card_rate(empresa)" in template
    assert '<div class="accommodation-card-rate"' in template
    assert "card_rate.value" in template
    assert template.index("accommodation-card-rate") < template.index("accommodation-card-actions")
    assert "card_chips[:3]" in template
    assert "accommodation-more-amenities" in template
    assert "Consultar por WhatsApp" in template


def test_mobile_resets_editorial_minimum_heights():
    css = Path("app/static/css/portal.css").read_text(encoding="utf-8")
    mobile = css.split("@media (max-width: 679px)", 1)[1].split("@media (prefers-reduced-motion", 1)[0]
    assert (
        ".accommodation-card-summary, .accommodation-amenities, .accommodation-card-rate "
        "{ min-block-size: 0; }"
    ) in mobile
