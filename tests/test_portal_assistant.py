import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, run_startup_db_maintenance


ROOT = Path(__file__).parents[1]
PARTIAL = ROOT / "app/templates/partials/portal_assistant.html"


def test_assistant_partial_and_single_nav_include_exist():
    assert PARTIAL.exists()
    nav = (ROOT / "app/templates/partials/portal_nav.html").read_text(encoding="utf-8")
    assert "show_portal_assistant|default(true)" in nav
    assert nav.count('partials/portal_assistant.html') == 1


def test_detail_templates_disable_assistant_before_nav_include():
    for template_name, nav_include in (
        ("prestador.html", '{% include "partials/portal_nav.html" %}'),
        ("actividad_detalle.html", "{% include 'partials/portal_nav.html' %}"),
    ):
        markup = (ROOT / f"app/templates/{template_name}").read_text(encoding="utf-8")
        assistant_setting = "{% set show_portal_assistant = false %}"
        assert assistant_setting in markup
        assert markup.index(assistant_setting) < markup.index(nav_include)


def test_assistant_renders_on_public_surfaces_only():
    run_startup_db_maintenance()
    client = TestClient(app)
    for route in ("/", "/gastronomia", "/alojamientos", "/servicios", "/actividades", "/agenda"):
        response = client.get(route)
        assert response.status_code == 200
        assert response.text.count('id="cabalango-assistant"') == 1
    assert 'id="cabalango-assistant"' not in client.get("/login").text
    admin_response = client.get("/admin", follow_redirects=False)
    assert admin_response.status_code in (302, 303, 307)
    assert 'id="cabalango-assistant"' not in admin_response.text


def test_assistant_accessible_shell_and_exact_navigation():
    markup = PARTIAL.read_text(encoding="utf-8")
    assert 'aria-haspopup="dialog"' in markup
    assert 'aria-controls="cabalango-assistant"' in markup
    assert 'aria-expanded="false"' in markup
    assert re.search(r'id="cabalango-assistant"[\s\S]*?role="dialog"[\s\S]*?aria-labelledby="cabalango-assistant-title"[\s\S]*?hidden', markup)
    root = re.search(r'<section id="assistant-view-root"[\s\S]*?</section>', markup).group()
    options = re.findall(r'<(?:button|a)[^>]*>([^<]+)</(?:button|a)>', root)
    assert options == [
        "Dónde comer", "Alojamientos", "Qué hacer", "Compras y servicios",
        "Qué hay hoy", "Salud y emergencias", "Seguridad", "Cómo llegar",
    ]
    buttons = re.findall(r'<button type="button" data-assistant-target="([^"]+)" aria-controls="([^"]+)">([^<]+)</button>', root)
    assert buttons == [
        ("gastronomy", "assistant-view-gastronomy", "Dónde comer"),
        ("accommodation", "assistant-view-accommodation", "Alojamientos"),
        ("activities", "assistant-view-activities", "Qué hacer"),
        ("services", "assistant-view-services", "Compras y servicios"),
        ("agenda", "assistant-view-agenda", "Qué hay hoy"),
        ("health", "assistant-view-health", "Salud y emergencias"),
    ]
    assert re.findall(r'<a href="([^"]+)">([^<]+)</a>', root) == [
        ("/#destination-dialog-seguridad", "Seguridad"), ("/como-llegar", "Cómo llegar")
    ]
    assert "<input" not in markup and "<textarea" not in markup


def test_assistant_has_all_server_rendered_views_and_back_controls():
    markup = PARTIAL.read_text(encoding="utf-8")
    views = re.findall(r'<section id="assistant-view-([^"]+)" data-assistant-view="([^"]+)"( hidden)?>', markup)
    assert views == [
        ("root", "root", ""),
        ("gastronomy", "gastronomy", " hidden"),
        ("accommodation", "accommodation", " hidden"),
        ("activities", "activities", " hidden"),
        ("services", "services", " hidden"),
        ("agenda", "agenda", " hidden"),
        ("health", "health", " hidden"),
    ]
    assert len(re.findall(r"\sdata-assistant-back(?:\s|>)", markup)) == 6
    assert len(re.findall(r'<h3 id="assistant-[^"]+-title" tabindex="-1">', markup)) == 6


def test_assistant_submenus_use_exact_public_urls():
    markup = PARTIAL.read_text(encoding="utf-8")

    def urls(view):
        section = re.search(rf'<section id="assistant-view-{view}"[\s\S]*?</section>', markup).group()
        return re.findall(r'<a href="([^"]+)">', section)

    assert urls("gastronomy") == [
        "/gastronomia?filtro=restaurantes", "/gastronomia?filtro=parrillas",
        "/gastronomia?filtro=casas_comida", "/gastronomia?filtro=bares",
        "/gastronomia?filtro=cafeterias", "/gastronomia?filtro=rotiserias",
        "/gastronomia?filtro=food_trucks", "/gastronomia?filtro=otros", "/gastronomia",
    ]
    assert urls("accommodation") == [
        "/alojamientos?tipo=cabaña", "/alojamientos?tipo=casa", "/alojamientos?tipo=hotel",
        "/alojamientos?tipo=departamento", "/alojamientos?tipo=complejo",
        "/alojamientos?tipo=hospedaje", "/alojamientos",
    ]
    assert urls("activities") == [
        "/actividades?categoria=naturaleza", "/actividades?categoria=bienestar",
        "/actividades?categoria=cultura", "/actividades?categoria=entretenimiento",
        "/actividades?categoria=familiar", "/actividades?categoria=deporte",
        "/actividades?categoria=artesania", "/actividades?categoria=musica",
        "/actividades?categoria=otros", "/actividades",
    ]
    assert urls("services") == [
        "/servicios?filtro=almacenes", "/servicios?filtro=panaderias",
        "/servicios?filtro=locales", "/servicios?filtro=transporte",
        "/servicios?filtro=estacionamiento", "/servicios?filtro=farmacia",
        "/servicios?filtro=lavanderia", "/servicios?filtro=otros", "/servicios",
    ]
    assert urls("agenda") == ["/agenda?cuando=hoy", "/agenda"]
    assert urls("health") == [
        "/servicios?filtro=farmacia", "/#destination-dialog-salud-emergencias",
    ]


def test_assistant_assets_are_isolated_and_static_only():
    css = (ROOT / "app/static/css/portal-assistant.css").read_text(encoding="utf-8")
    script = (ROOT / "app/static/js/portal-assistant.js").read_text(encoding="utf-8")
    for requirement in ("position: fixed", "@media (max-width: 600px)", "@media (max-width: 340px)", "max-height: 78dvh", "safe-area-inset-bottom", "prefers-reduced-motion"):
        assert requirement in css
    for portal_token in (
        "--assistant-surface: var(--portal-card",
        "--assistant-text: var(--portal-graphite",
        "--assistant-muted: var(--portal-muted",
        "--assistant-accent: var(--portal-olive",
        "--assistant-border: var(--portal-line",
        "var(--portal-font-sans",
    ):
        assert portal_token in css
    font_declarations = re.findall(r"font:\s*([^;]+)", css)
    assert font_declarations
    assert all('var(--portal-font-sans, "Manrope", Inter, system-ui, sans-serif)' in declaration for declaration in font_declarations)
    for requirement in ('aria-expanded', 'Escape', 'hidden', 'trigger.focus()', 'data-assistant-target', 'data-assistant-view', 'data-assistant-back', 'showView', 'scrollTop', 'focus'):
        assert requirement in script
    for forbidden in ("fetch(", "innerHTML", "insertAdjacentHTML", "localStorage", "sessionStorage", "history.pushState", "history.replaceState", "WebSocket", "EventSource"):
        assert forbidden not in script
    partial = PARTIAL.read_text(encoding="utf-8")
    assert partial.count("images/asistente-cabalango-zorro.png") == 2
    assert partial.count("20260911-assistant-navigation-1") == 2
