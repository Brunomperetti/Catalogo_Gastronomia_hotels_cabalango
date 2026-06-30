from types import SimpleNamespace
from pathlib import Path

from jinja2 import Environment


class UrlForStub:
    def __call__(self, endpoint, **kwargs):
        if endpoint == "static":
            return f"/static/{kwargs.get('path', '')}"
        return "/"


def render_prestador(theme="alojamiento", galeria_urls=None):
    template_src = Path("app/templates/prestador.html").read_text(encoding="utf-8")
    template = Environment().from_string(template_src)
    empresa = SimpleNamespace(
        nombre="Cabañas Demo",
        slug="cabanas-demo",
        theme=theme,
        whatsapp="5493510000000",
        telefono="",
        instagram="",
        facebook="",
        web_url="",
        direccion="Ruta demo 123",
        maps_url="https://maps.example/demo",
        subgrupo="",
        subtipo="Cabaña",
        descripcion_corta="Vista al río",
        descripcion="Alojamiento turístico en Cabalango.",
        horarios="Check-in 14 hs",
        precio_desde="$ 50.000",
        capacidad="4 personas",
        habitaciones="2",
        banos="1",
        video_url="",
        menu_url="",
        promocion="",
        guardia="",
        fecha="",
        organizador="",
        lugar_encuentro="",
    )
    galeria_urls = galeria_urls or []
    return template.render(
        request=SimpleNamespace(url_for=UrlForStub()),
        url_for=UrlForStub(),
        empresa=empresa,
        kind=theme,
        quick_facts=[{"label": "Capacidad", "value": "4 personas", "enabled": True, "prepared": False}],
        empresa_logo_url="/static/images/logo.png",
        empresa_banner_url="/static/images/banner.jpg",
        galeria_urls=galeria_urls,
        gallery_tiles=galeria_urls[1:5] or ["/static/images/banner.jpg"],
        main_photo_url=galeria_urls[0] if galeria_urls else "/static/images/banner.jpg",
        theme_display_label=lambda value: "Alojamientos" if value == "alojamiento" else "Gastronomía",
        actividad_subgrupos={},
    )


def test_prestador_template_is_tourism_first_for_alojamiento():
    html = render_prestador("alojamiento", ["/media/empresas/demo/galeria/foto-1.webp"])

    assert "Consultar por WhatsApp" in html
    assert "Ver todas las fotos" in html
    assert "Lo que más consultan los viajeros" in html
    assert "Descargar lista de precios" not in html
    assert "Productos / platos publicados" not in html


def test_prestador_template_empty_gallery_does_not_break():
    html = render_prestador("alojamiento", [])

    assert "Todavía no hay fotos cargadas" in html
    assert "Compatibilidad catálogo viejo" in html
