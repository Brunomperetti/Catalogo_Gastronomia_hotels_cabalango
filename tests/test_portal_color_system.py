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
