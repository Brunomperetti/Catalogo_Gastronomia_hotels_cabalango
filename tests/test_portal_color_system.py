from pathlib import Path


def test_portal_global_color_system_is_present():
    css = Path("app/static/css/portal.css").read_text(encoding="utf-8")

    assert "Cabalango global color system 2026" in css
    for color in (
        "#F7F3EA",
        "#F2E9D8",
        "#3A3F2D",
        "#59663F",
        "#8A9B68",
        "#D8CFBE",
        "#78AABD",
    ):
        assert color in css
