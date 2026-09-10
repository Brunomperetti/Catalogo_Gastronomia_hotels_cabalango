import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, run_startup_db_maintenance


ROOT = Path(__file__).parents[1]
PARTIAL = ROOT / "app/templates/partials/portal_assistant.html"


def test_assistant_partial_and_single_nav_include_exist():
    assert PARTIAL.exists()
    nav = (ROOT / "app/templates/partials/portal_nav.html").read_text(encoding="utf-8")
    assert nav.count('partials/portal_assistant.html') == 1


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
    expected = [
        ("/gastronomia", "Dónde comer"),
        ("/alojamientos", "Alojamientos"),
        ("/actividades", "Qué hacer"),
        ("/servicios", "Compras y servicios"),
        ("/agenda", "Qué hay hoy"),
        ("/descubri-cabalango", "Salud y emergencias"),
        ("/descubri-cabalango", "Seguridad"),
        ("/como-llegar", "Cómo llegar"),
    ]
    options = re.findall(r'<a href="([^"]+)">([^<]+)</a>', markup)
    assert options == expected
    assert "<input" not in markup and "<textarea" not in markup


def test_assistant_assets_are_isolated_and_static_only():
    css = (ROOT / "app/static/css/portal-assistant.css").read_text(encoding="utf-8")
    script = (ROOT / "app/static/js/portal-assistant.js").read_text(encoding="utf-8")
    for requirement in ("position: fixed", "@media (max-width: 600px)", "max-height: 78dvh", "safe-area-inset-bottom", "prefers-reduced-motion"):
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
    for requirement in ('aria-expanded', 'Escape', 'hidden', 'trigger.focus()'):
        assert requirement in script
    for forbidden in ("fetch(", "localStorage", "sessionStorage", "WebSocket", "EventSource"):
        assert forbidden not in script
