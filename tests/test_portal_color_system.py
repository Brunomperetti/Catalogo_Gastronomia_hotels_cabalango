from pathlib import Path


def test_portal_global_color_system_is_present():
    css = Path("app/static/css/portal.css").read_text(encoding="utf-8")

    assert "Cabalango global color system 2026" in css
    for color in (
        "#F6F1E7",
        "#FBF8F2",
        "#EFE7D8",
        "#3F4633",
        "#5A4636",
        "#6E7B52",
        "#A8B39A",
        "#6FA7BE",
        "#B97A56",
        "#D8CCB8",
    ):
        assert color in css

    color_system = css.split("/* Cabalango global color system 2026 */", 1)[1]
    assert not all(color in color_system for color in ("#F7F3EA", "#59663F"))
