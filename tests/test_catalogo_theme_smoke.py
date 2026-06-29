from pathlib import Path

from jinja2 import Environment


def test_catalogo_theme_class_rendered_for_comida():
    template_src = Path('app/templates/catalogo.html').read_text(encoding='utf-8')
    template = Environment().from_string(template_src)

    html = template.render(
        empresa={'theme': 'comida', 'nombre': 'Demo', 'slug': 'demo', 'whatsapp': '000'},
        empresa_banner_url='',
        empresa_logo_url='',
        app_build='test',
        ts_download='0',
        categorias=[],
        productos_json=[],
        lead_data={},
        url_for=lambda *_args, **_kwargs: "/static/mock.css",
    )

    assert 'catalog-theme-comida' in html
