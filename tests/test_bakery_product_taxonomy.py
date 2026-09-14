from pathlib import Path
from types import SimpleNamespace

from app.main import (
    BAKERY_PRODUCT_CATEGORIES,
    COMMERCE_PRODUCT_TAXONOMY_VERSION,
    PROVIDER_PRODUCT_CATEGORIES,
    SERVICIOS_CATEGORIAS_ADMIN,
    build_commerce_card_product_facts,
    build_provider_products,
    get_provider_product_categories,
    normalize_commerce_product_categories,
    parse_commerce_product_categories,
    serialize_commerce_product_categories,
)


def provider(subtype="Panadería", products=None):
    return SimpleNamespace(
        theme="servicios",
        subgrupo="compras",
        subtipo=subtype,
        compras_productos_disponibles=(
            serialize_commerce_product_categories(products) if products is not None else None
        ),
    )


def test_bakery_uses_specific_catalog_and_general_commerces_keep_their_catalog():
    bakery_labels = dict(get_provider_product_categories(provider())).values()
    for label in (
        "Pan dulce", "Pastelitos", "Masitas / masas secas", "Criollos",
        "Chipá", "Facturas", "Pan casero / artesanal",
    ):
        assert label in bakery_labels
    for label in ("Carne vacuna", "Pollo", "Gas envasado", "Hielo", "Artículos de limpieza"):
        assert label not in bakery_labels

    assert get_provider_product_categories(provider("Almacén")) == PROVIDER_PRODUCT_CATEGORIES
    assert get_provider_product_categories(provider("Proveeduría")) == PROVIDER_PRODUCT_CATEGORIES


def test_bakery_values_round_trip_deduplicate_and_reject_unknown_values():
    encoded = serialize_commerce_product_categories([
        "Criollos", "criollos", "Chipá", "Pan dulce", "producto inexistente",
    ])
    assert parse_commerce_product_categories(encoded) == ["criollos", "chipa", "pan dulce"]
    assert normalize_commerce_product_categories(["desconocido"]) == []


def test_bakery_public_products_are_selected_only_and_follow_editorial_order():
    bakery = provider("Panadería", ["pan dulce", "pastelitos", "criollos", "panificados", "chipa"])
    expected = ["Criollos", "Chipá", "Pastelitos", "Pan dulce"]
    assert [item["label"] for item in build_provider_products(bakery, "servicios")] == expected
    assert build_commerce_card_product_facts(bakery) == ["Criollos", "Chipá", "Pastelitos", "+1 producto"]
    assert "Panificados" not in [item["label"] for item in build_provider_products(bakery, "servicios")]


def test_historical_general_selection_remains_valid_for_admin_persistence():
    raw = serialize_commerce_product_categories(["panificados"])
    assert raw == '["panificados"]'
    assert parse_commerce_product_categories(raw) == ["panificados"]
    assert "panificados" not in dict(BAKERY_PRODUCT_CATEGORIES)


def test_admin_javascript_switches_catalog_and_preserves_explicit_selections():
    template = Path("app/templates/upload.html").read_text(encoding="utf-8")
    assert "categorySelect.value === 'panaderias'" in template
    assert "PRODUCTOS DE PANADERÍA" in template
    assert "Selecciones anteriores" in template
    assert "selectedProducts.delete(key)" in template
    assert "syncProductInputs()" in template
    assert "compras_productos_disponibles" in template
    assert "const categoryConfig = serviceAdminCategories[categorySelect.value];" in template
    assert "const isCommerce = categoryConfig?.subgrupo === 'compras';" in template
    assert "products.hidden = !isCommerce;" in template
    assert "products.disabled = !isCommerce;" in template
    assert "presentMarker.disabled = !isCommerce;" in template
    assert "if (!isCommerce)" in template
    assert "products.querySelector('.commerce-products-inputs').replaceChildren();" in template
    assert "selectedProducts.clear" not in template


def test_bakery_admin_category_is_a_commerce_category():
    assert SERVICIOS_CATEGORIAS_ADMIN["panaderias"]["subgrupo"] == "compras"


def test_taxonomy_extension_does_not_change_intake_backfill_version():
    assert COMMERCE_PRODUCT_TAXONOMY_VERSION == 2
