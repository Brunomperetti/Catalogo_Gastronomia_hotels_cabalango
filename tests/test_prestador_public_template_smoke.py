from types import SimpleNamespace
import re

from jinja2 import Environment, FileSystemLoader


class UrlForStub:
    def __call__(self, endpoint, **kwargs):
        if endpoint == "static":
            return f"/static/{kwargs.get('path', '')}"
        return "/"


def render_prestador(theme="alojamiento", galeria_urls=None):
    template = Environment(loader=FileSystemLoader("app/templates")).get_template("prestador.html")
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
        rating_promedio=None,
        rating_cantidad=None,
        reviews_destacadas="",
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
        public_reviews=[],
        maps_url=empresa.maps_url,
        instagram_contact={"label": empresa.instagram, "url": None},
        facebook_url=None,
        web_url=None,
        whatsapp_url="https://wa.me/5493510000000",
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
    assert "Opiniones de huéspedes" in html
    assert "Lo que más consultan los viajeros" in html
    assert "Descargar lista de precios" not in html
    assert "Productos / platos publicados" not in html


def test_prestador_template_empty_gallery_does_not_break():
    html = render_prestador("alojamiento", [])

    assert "Todavía no hay fotos cargadas" in html
    assert "Compatibilidad catálogo viejo" not in html
    assert "Abrir catálogo heredado" not in html


def test_public_gallery_renders_one_photo_without_mutating_empresa():
    photo = "/media/empresas/demo/galeria/vertical.webp"
    html = render_prestador("alojamiento", [photo])

    assert 'class="public-gallery public-gallery--count-1"' in html
    assert html.count('class="public-gallery__item ') == 1
    assert f'src="{photo}"' in html
    assert 'data-gallery-open="0"' in html
    assert "Cabañas Demo" in html


def test_public_gallery_is_only_in_photos_section_and_hero_is_restored():
    html = render_prestador("alojamiento", ["/media/empresas/demo/galeria/foto-1.webp"])
    hero = re.search(
        r'<section class="tourism-hero">(.*?)<div class="tourism-heading-card provider-identity">',
        html,
        re.DOTALL,
    ).group(1)
    photos_section = re.search(
        r'<section class="portal-card photos-summary-card" id="fotos">(.*?)</section>',
        html,
        re.DOTALL,
    ).group(1)

    assert 'class="tourism-gallery ' in hero
    assert 'class="tourism-gallery-main ' in hero
    assert 'class="tourism-gallery-side"' in hero
    assert "public-gallery" not in hero
    assert "Fotos del lugar" in photos_section
    assert 'class="public-gallery public-gallery--count-1"' in photos_section
    assert html.count('class="public-gallery ') == 1
    assert html.count('id="fotos"') == 1


def test_public_gallery_limits_preview_and_exposes_every_lightbox_url():
    photos = [f"/media/empresas/demo/galeria/foto-{number}.webp" for number in range(1, 7)]
    html = render_prestador("alojamiento", photos)

    assert 'class="public-gallery public-gallery--count-4"' in html
    assert html.count('class="public-gallery__item ') == 4
    assert "+2 fotos" in html
    assert "Ver todas las fotos" in html
    assert html.count("/media/empresas/demo/galeria/foto-6.webp") == 1
    for photo in photos:
        assert photo in html


def test_public_gallery_has_accessible_lightbox_controls():
    html = render_prestador("alojamiento", ["/one.webp", "/two.webp"])

    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-label="Cerrar galería"' in html
    assert 'aria-label="Foto anterior"' in html
    assert 'aria-label="Foto siguiente"' in html
    assert "ArrowLeft" in html and "ArrowRight" in html and "Escape" in html


def test_prestador_template_uses_normalized_external_contact_links():
    template = Environment(loader=FileSystemLoader("app/templates")).get_template("prestador.html")
    empresa = SimpleNamespace(
        nombre="Cabañas Demo", slug="cabanas-demo", theme="alojamiento", whatsapp="5493510000000",
        telefono="3541000000", instagram="@cabanas_demo", facebook="facebook.com/cabanas",
        web_url="facebook.com/golata007", direccion="Ruta demo 123", maps_url="maps.google.com/demo",
        subgrupo="", subtipo="Cabaña", descripcion_corta="Vista al río", descripcion="Demo", horarios="",
        precio_desde="", capacidad="", habitaciones="", banos="", video_url="", menu_url="", promocion="",
        rating_promedio=None, rating_cantidad=None, reviews_destacadas="", guardia="", fecha="",
        organizador="", lugar_encuentro="",
    )
    html = template.render(
        request=SimpleNamespace(url_for=UrlForStub()), url_for=UrlForStub(), empresa=empresa, kind="alojamiento",
        quick_facts=[], public_reviews=[], maps_url="https://maps.google.com/demo",
        instagram_contact={"label": "@cabanas_demo", "url": "https://instagram.com/cabanas_demo"},
        facebook_url="https://facebook.com/cabanas", web_url="https://facebook.com/golata007",
        whatsapp_url="https://wa.me/5493510000000", empresa_logo_url="", empresa_banner_url="", galeria_urls=[],
        gallery_tiles=[], main_photo_url="/static/img/no-image.jpg", has_real_photos=False,
        theme_display_label=lambda value: "Alojamientos", actividad_subgrupos={},
    )

    assert 'href="https://facebook.com/golata007"' in html
    assert 'href="https://facebook.com/cabanas"' in html
    assert 'href="https://instagram.com/cabanas_demo"' in html
    assert 'href="/prestador/facebook.com/golata007"' not in html
