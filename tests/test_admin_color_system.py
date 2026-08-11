from pathlib import Path


def test_admin_river_color_tokens_are_centralized():
    css = Path("app/static/css/admin.css").read_text(encoding="utf-8")

    for token in (
        "--admin-text-deep: #3B2D27;",
        "--admin-river-light: #C4D5D7;",
        "--admin-river: #7FA2A9;",
        "--admin-river-dark: #5F8189;",
        "--admin-success: #65704B;",
    ):
        assert token in css
