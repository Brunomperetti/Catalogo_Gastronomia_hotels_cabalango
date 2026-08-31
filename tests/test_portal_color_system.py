import re
from pathlib import Path


def test_portal_global_color_system_is_present():
    css = Path("app/static/css/portal.css").read_text(encoding="utf-8")

    assert css.count("Cabalango global color system 2026") == 1
    assert "Cabalango editorial refinement" not in css
    color_system = css.split("/* Cabalango global color system 2026 */", 1)[1]

    for color in (
        "#F4F0E6",
        "#FAF7F0",
        "#ECE6DA",
        "#49372D",
        "#514B43",
        "#766F65",
        "#65704B",
        "#505A3B",
        "#789BA5",
        "#D8D0C2",
    ):
        assert color in color_system

    assert not all(color in color_system for color in ("#F7F3EA", "#59663F"))


def test_weather_uses_the_reduced_editorial_palette_and_balanced_grid():
    css = Path("app/static/css/portal.css").read_text(encoding="utf-8")
    color_system = css.split("/* Cabalango global color system 2026 */", 1)[1]

    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in color_system
    assert ".weather-summary span," in color_system
    assert "color: var(--portal-muted);" in color_system
    assert ".season-grid span { color: var(--portal-primary); }" in color_system
    assert "background: rgba(170, 177, 154, .20);" in color_system


def test_provider_profile_uses_editorial_colors_and_legible_promotion():
    css = Path("app/static/css/portal.css").read_text(encoding="utf-8")
    color_system = css.split("/* Cabalango global color system 2026 */", 1)[1]

    assert "main.prestador-page .quick-facts-grid > div > span" in color_system
    assert "main.prestador-page .prestador-detail-grid .promo-highlight > strong" in color_system
    assert "main.prestador-page .prestador-detail-grid .promo-highlight > small" in color_system
    assert ".prestador-promo" not in color_system
    assert "background: var(--portal-surface) !important;" in color_system
    assert "color: var(--portal-heading) !important;" in color_system
    assert "color: var(--portal-muted) !important;" in color_system
    assert "color: var(--portal-primary) !important;" in color_system


def test_public_templates_invalidate_cached_portal_styles():
    default_version = "?v=20260810-commerce-services-1"

    for template_path in Path("app/templates").glob("*.html"):
        template = template_path.read_text(encoding="utf-8")
        if "path='css/portal.css'" in template:
            expected_version = "?v=20260826-weather-refresh-15" if template_path.name == "descubri_cabalango.html" else "?v=20260821-travel-guide-3" if template_path.name == "como_llegar.html" else "?v=20260831-provider-promo-contrast-1" if template_path.name == "prestador.html" else "?v=20260818-agenda-official-1" if template_path.name == "actividades.html" else "?v=20260831-activity-gallery-polish-2" if template_path.name == "actividad_detalle.html" else default_version
            assert expected_version in template


def test_public_secondary_buttons_use_approved_outline_system():
    css = Path("app/static/css/portal.css").read_text(encoding="utf-8")
    color_system = css.split("/* Cabalango global color system 2026 */", 1)[1]

    assert ".portal-button-secondary:visited" in color_system
    assert ".portal-button-secondary:hover" in color_system
    assert "background: transparent !important;" in color_system
    assert "border: 1px solid var(--portal-primary) !important;" in color_system
    assert "color: var(--portal-primary) !important;" in color_system
    assert "background: var(--portal-primary) !important;" in color_system
    assert "color: var(--portal-white) !important;" in color_system


def test_public_ctas_have_semantic_primary_and_secondary_classes():
    templates = {
        path.name: path.read_text(encoding="utf-8")
        for path in Path("app/templates").glob("*.html")
    }

    for label in ("Cómo llegar", "Ver fotos"):
        assert f'portal-button-secondary"' in templates["prestador.html"].split(label, 1)[0].rsplit("<", 1)[1]

    for label in ("Dónde comer", "Qué hacer", "Gastronomía", "Qué hacer"):
        matching_markup = [
            tag
            for markup in templates.values()
            for tag in re.findall(r"<a\b[^>]*>[^<]*" + re.escape(label), markup)
        ]
        assert any("portal-button-secondary" in tag for tag in matching_markup)

    primary_contexts = (
        (templates["prestador.html"], "Consultar por WhatsApp"),
        (templates["descubri_cabalango.html"], "Explorar Cabalango"),
    )
    for template, label in primary_contexts:
        tag = template.split(label, 1)[0].rsplit("<", 1)[1]
        assert 'class="portal-button"' in tag
        assert "portal-button-secondary" not in tag
