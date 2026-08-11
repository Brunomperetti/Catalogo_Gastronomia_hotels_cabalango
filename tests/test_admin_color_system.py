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
        "--admin-border: #B8DCE5;",
        "--admin-border-strong: #8FC6D4;",
        "--admin-focus-ring: rgba(77, 145, 165, .34);",
    ):
        assert token in css

    for removed_token in ("--admin-success", "--admin-olive", "--admin-river"):
        assert removed_token not in css

    for removed_green in ("#526B3F", "#65704B", "#EEF0E5", "#B8C0A5"):
        assert removed_green not in css


def test_admin_uses_sky_borders_and_interaction_states():
    css = Path("app/static/css/admin.css").read_text(encoding="utf-8")

    assert "border: 1px solid var(--admin-border) !important;" in css
    assert "border: 1px solid var(--admin-border-strong) !important;" in css
    assert "background: var(--admin-sky) !important;" in css
    assert "background: var(--admin-sky-action) !important;" in css
    assert "box-shadow: 0 0 0 3px var(--admin-focus-ring) !important;" in css

    active_tabs = css[css.index(".admin-tab.is-active,"):css.index(".admin-tab--warning")]
    assert "background: var(--admin-sky) !important;" in active_tabs

    inputs = css[css.index(".input-custom,"):css.index(".input-custom::placeholder")]
    assert "border: 1px solid var(--admin-border) !important;" in inputs

    positive_badge = css[css.index(".provider-status.is-active"):css.index(".provider-status.is-inactive")]
    assert "background: var(--admin-sky-light)" in positive_badge
    assert "border: 1px solid var(--admin-sky)" in positive_badge
