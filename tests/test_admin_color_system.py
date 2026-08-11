from pathlib import Path


def test_admin_sky_and_brown_color_tokens_are_centralized():
    css = Path("app/static/css/admin.css").read_text(encoding="utf-8")

    for token in (
        "--admin-brown-deep: #38251F;",
        "--admin-brown: #533A30;",
        "--admin-sky-light: #DCEFF4;",
        "--admin-sky: #A8D6E2;",
        "--admin-sky-dark: #4D91A5;",
        "--admin-sky-action: #36768A;",
        "--admin-success: #526B3F;",
        "--admin-border: #533A30;",
        "--admin-border-strong: #38251F;",
    ):
        assert token in css

    assert "--admin-river" not in css


def test_admin_uses_brown_borders_and_sky_interaction_states():
    css = Path("app/static/css/admin.css").read_text(encoding="utf-8")

    assert "border: 1px solid var(--admin-border) !important;" in css
    assert "border: 1px solid var(--admin-border-strong) !important;" in css
    assert "background: var(--admin-sky) !important;" in css
    assert "background: var(--admin-sky-action) !important;" in css
    assert "box-shadow: 0 0 0 3px var(--admin-focus-ring) !important;" in css
    assert ".provider-status.is-active" in css
    assert "background: var(--admin-success-surface)" in css
