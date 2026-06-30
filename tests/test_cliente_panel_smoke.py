from types import SimpleNamespace
from pathlib import Path

from jinja2 import Environment


def test_cliente_panel_simplified_copy_without_technical_imports():
    template_src = Path("app/templates/cliente_panel.html").read_text(encoding="utf-8")
    template = Environment().from_string(template_src)
    empresa = SimpleNamespace(
        nombre="Demo Cabalango",
        slug="demo-cabalango",
        activo=True,
        logo_url="",
        banner_url="",
        whatsapp="",
        telefono="",
        instagram="",
        direccion="",
        maps_url="",
        descripcion="",
        horarios="",
        precio_desde="",
        capacidad="",
        habitaciones="",
        video_url="",
        subgrupo="",
        delivery=False,
        take_away=False,
        comer_en_lugar=False,
        pileta=False,
        rio=False,
        mascotas=False,
        cochera=False,
        wifi=False,
    )

    html = template.render(
        empresa_activa=empresa,
        prestador_section_label="Gastronomía",
        prestador_kind="gastronomia",
        portal_section_url="/gastronomia",
        empresa_logo_url="/static/images/logo.png",
        catalogo_public_url="http://testserver/prestador/demo-cabalango",
        galeria_urls=[],
        msg="",
        error="",
        time=0,
        is_admin_view=False,
    )

    assert "Mi ficha en el portal" in html
    assert "Fotos y video" in html
    assert "Vista previa" in html
    assert "Subir Excel" not in html
    assert "Subir ZIP" not in html
    assert "Leads" not in html
    assert "Backup" not in html
