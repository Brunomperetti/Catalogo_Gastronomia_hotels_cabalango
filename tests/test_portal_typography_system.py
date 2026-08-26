from pathlib import Path


PUBLIC_TEMPLATES = (
    "descubri_cabalango.html",
    "portal_home.html",
    "portal_prestadores.html",
    "prestador.html",
)


def _template(name: str) -> str:
    return Path("app/templates", name).read_text(encoding="utf-8")


def _typography_layer() -> str:
    css = Path("app/static/css/portal.css").read_text(encoding="utf-8")
    return css.split("/* Cabalango global color system 2026 */", 1)[1]


def test_public_templates_load_the_approved_font_families_once():
    for name in PUBLIC_TEMPLATES:
        template = _template(name)

        assert template.count("fonts.googleapis.com/css2?") == 1
        assert "family=Manrope:wght@400;500;600;700;800" in template
        assert "family=Newsreader:ital,opsz,wght@" in template
        assert "display=swap" in template
        assert "Cormorant+Garamond" not in template
        assert 'rel="preconnect" href="https://fonts.googleapis.com"' in template
        assert 'rel="preconnect" href="https://fonts.gstatic.com" crossorigin' in template
        expected_version = "?v=20260826-weather-full-redesign-7" if name == "descubri_cabalango.html" else "?v=20260814-provider-lightbox-sizing-1" if name == "prestador.html" else "?v=20260810-commerce-services-1"
        assert expected_version in template


def test_portal_typography_tokens_and_base_face_are_consolidated():
    typography = _typography_layer()

    assert '--portal-font-display: "Newsreader", Georgia, "Times New Roman", serif;' in typography
    assert '--portal-font-sans: "Manrope", Inter, system-ui' in typography
    assert ".portal-body {" in typography
    assert "font-family: var(--portal-font-sans);" in typography
    assert "font-synthesis: none;" in typography


def test_editorial_and_functional_components_use_their_respective_tokens():
    typography = _typography_layer()

    assert ".portal-hero h1," in typography
    assert ".destination-weather-card h3," in typography
    assert ".prestador-card h2," in typography
    assert "font-family: var(--portal-font-display);" in typography
    assert ".portal-topnav a," in typography
    assert ".portal-button," in typography
    assert ".portal-kicker," in typography
    assert ".weather-temp," in typography
    assert "font-family: var(--portal-font-sans);" in typography
    assert 'font-feature-settings: "tnum" 1, "lnum" 1;' in typography


def test_public_hero_and_editorial_title_scales_are_bounded():
    typography = _typography_layer()

    assert "--portal-title-hero: clamp(2.25rem, 6vw, 4.5rem);" in typography
    assert "--portal-title-editorial: clamp(2.125rem, 4.5vw, 4rem);" in typography
    assert "font-size: var(--portal-title-hero);" in typography
    assert "font-size: var(--portal-title-editorial);" in typography
    assert "max-width: 15ch;" in typography
    assert "max-width: 18ch;" in typography


def test_public_portal_has_no_active_cormorant_reference():
    css = Path("app/static/css/portal.css").read_text(encoding="utf-8")

    assert "Cormorant Garamond" not in css
    for name in PUBLIC_TEMPLATES:
        assert "Cormorant Garamond" not in _template(name)
