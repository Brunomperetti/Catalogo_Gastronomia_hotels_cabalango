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
    assert "border-color: var(--admin-border-strong) !important;" in css
    assert "box-shadow: 0 0 0 3px var(--admin-focus-ring) !important;" in css

    active_tabs = css[css.index(".admin-tab.is-active,"):css.index(".admin-tab--warning")]
    assert "background: rgba(168, 214, 226, .22) !important;" in active_tabs
    assert "border-color: var(--admin-border-strong) !important;" in active_tabs
    assert "color: var(--admin-brown-deep) !important;" in active_tabs
    assert "background: var(--admin-brown-deep)" not in active_tabs
    assert "background: var(--admin-sky)" not in active_tabs

    inputs = css[css.index(".input-custom,"):css.index(".input-custom::placeholder")]
    assert "border: 1px solid var(--admin-border) !important;" in inputs

    positive_badge = css[css.index(".provider-status.is-active"):css.index(".provider-status.is-inactive")]
    assert "background: rgba(168, 214, 226, .18)" in positive_badge
    assert "border: 1px solid var(--admin-border-strong)" in positive_badge


def test_admin_primary_actions_use_deep_brown_and_light_text():
    css = Path("app/static/css/admin.css").read_text(encoding="utf-8")

    primary_actions = css[css.index(".btn-primary-custom,"):css.index(".btn-primary-custom:hover,")]
    assert "background: var(--admin-brown-deep) !important;" in primary_actions
    assert "border: 1px solid var(--admin-brown-deep) !important;" in primary_actions
    assert "color: var(--admin-white) !important;" in primary_actions

    primary_hover = css[css.index(".btn-primary-custom:hover,"):css.index(".btn-primary-custom:focus-visible,", css.index(".btn-primary-custom:focus-visible,") + 1)]
    assert "background: var(--admin-brown) !important;" in primary_hover
    assert "color: var(--admin-white) !important;" in primary_hover


def test_all_admin_action_button_families_use_brown_not_sky_fills():
    css = Path("app/static/css/admin.css").read_text(encoding="utf-8")

    primary_actions = css[css.index(".btn-primary-custom,"):css.index(".btn-primary-custom:hover,")]
    secondary_actions = css[css.index(".btn-secondary-custom,"):css.index(".btn-secondary-custom:hover,")]
    file_action = css[css.index('.input-file-custom::file-selector-button,'):css.index('.input-file-custom::file-selector-button:hover,')]

    for action_rules in (primary_actions, secondary_actions, file_action):
        assert "background: var(--admin-brown-deep) !important;" in action_rules
        assert "color: var(--admin-white) !important;" in action_rules
        assert "background: var(--admin-sky)" not in action_rules
        assert "background: var(--admin-sky-light)" not in action_rules


def test_large_active_navigation_surfaces_use_a_translucent_sky_selection():
    css = Path("app/static/css/admin.css").read_text(encoding="utf-8")

    active_area = css[css.index(".admin-area-link.is-active,"):css.index(".admin-area-link__copy")]
    assert "background: rgba(168, 214, 226, .22);" in active_area
    assert "border-color: var(--admin-border-strong);" in active_area
    assert "color: var(--admin-brown-deep) !important;" in active_area
    assert "background: var(--admin-brown-deep)" not in active_area
    assert "background: var(--admin-sky)" not in active_area
    assert "background: linear-gradient" not in css


def test_inactive_admin_navigation_uses_visible_sky_borders_and_subtle_hover():
    css = Path("app/static/css/admin.css").read_text(encoding="utf-8")

    inactive_tabs = css[css.index(".admin-tab,"):css.index(".admin-tab:hover,")]
    assert "background: var(--admin-surface) !important;" in inactive_tabs
    assert "border: 1px solid var(--admin-border) !important;" in inactive_tabs

    tab_hover = css[css.index(".admin-tab:hover,"):css.index(".admin-tab.is-active,")]
    assert "background: rgba(168, 214, 226, .12) !important;" in tab_hover
    assert "background: var(--admin-sky)" not in tab_hover

    active_tabs = css[css.index(".admin-tab.is-active,"):css.index(".admin-tab--warning")]
    assert "background: rgba(168, 214, 226, .22) !important;" in active_tabs
    assert "border-color: var(--admin-border-strong) !important;" in active_tabs
    assert "background: var(--admin-brown-deep)" not in active_tabs
    assert "background: var(--admin-sky)" not in active_tabs

    inactive_area = css[css.index(".admin-area-link,\n"):css.index(".admin-area-link:hover")]
    assert "background: var(--admin-surface);" in inactive_area
    assert "border: 1px solid var(--admin-border);" in inactive_area

    area_hover = css[css.index(".admin-area-link:hover"):css.index(".admin-area-link:focus-visible")]
    assert "background: rgba(168, 214, 226, .12);" in area_hover
    assert "background: var(--admin-sky)" not in area_hover

    active_area = css[css.index(".admin-area-link.is-active,"):css.index(".admin-area-link__copy")]
    assert "background: rgba(168, 214, 226, .22);" in active_area
    assert "border-color: var(--admin-border-strong);" in active_area
    assert "background: var(--admin-brown-deep)" not in active_area
