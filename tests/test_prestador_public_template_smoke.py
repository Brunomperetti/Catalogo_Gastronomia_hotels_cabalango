from types import SimpleNamespace
import re

from jinja2 import Environment, FileSystemLoader


class UrlForStub:
    def __call__(self, endpoint, **kwargs):
        if endpoint == "static":
            return f"/static/{kwargs.get('path', '')}"
        return "/"


def render_prestador(theme="alojamiento", galeria_urls=None, identity_overrides=None, subtipo="Cabaña"):
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
        subtipo=subtipo,
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
    identity_overrides = identity_overrides or {}
    for field in ("direccion", "horarios", "whatsapp"):
        if field in identity_overrides:
            setattr(empresa, field, identity_overrides[field])
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
        empresa_logo_url=identity_overrides.get("empresa_logo_url", "/static/images/logo.png"),
        empresa_banner_url="/static/images/banner.jpg",
        galeria_urls=galeria_urls,
        gallery_tiles=galeria_urls[1:5] or ["/static/images/banner.jpg"],
        main_photo_url=galeria_urls[0] if galeria_urls else "/static/images/banner.jpg",
        has_real_photos=bool(galeria_urls),
        theme_display_label=lambda value: "Alojamientos" if value == "alojamiento" else "Gastronomía",
        service_card_kicker=lambda empresa: "Almacenes y kioscos · Almacén",
        actividad_subgrupos={},
    )


def test_prestador_template_is_tourism_first_for_alojamiento():
    html = render_prestador("alojamiento", ["/media/empresas/demo/galeria/foto-1.webp"])

    assert "Consultar por WhatsApp" in html
    assert "Ver todas las fotos" in html
    assert "Opiniones de huéspedes" in html
    assert "Información práctica" in html
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
    assert html.count('class="public-gallery__item"') == 1
    assert f'src="{photo}"' in html
    assert 'data-gallery-open="0"' in html
    assert "Cabañas Demo" in html


def test_public_gallery_single_photo_css_uses_the_full_available_width():
    css = open("app/static/css/portal.css", encoding="utf-8").read()

    grid_rule = re.findall(
        r"\.public-gallery--count-1 \.public-gallery__grid \{([^}]*)\}", css
    )[0]
    item_rule = re.findall(r"\.public-gallery__item \{([^}]*)\}", css)[-1]

    assert "grid-template-columns: 1fr" in grid_rule
    assert "aspect-ratio: 4 / 3" in item_rule


def test_provider_identity_has_no_legacy_aside_when_metadata_is_empty():
    html = render_prestador(identity_overrides={
        "empresa_logo_url": "", "direccion": "", "horarios": "", "whatsapp": ""
    })

    assert 'class="tourism-heading-card provider-identity"' in html
    assert 'class="provider-identity__aside"' not in html
    assert 'class="provider-metadata"' not in html


def test_provider_identity_integrates_logo_title_and_metadata():
    html = render_prestador(identity_overrides={
        "empresa_logo_url": "/logo.webp", "direccion": "Ruta demo 123", "horarios": "", "whatsapp": ""
    })

    assert 'class="tourism-heading-card provider-identity"' in html
    intro = re.search(r'<div class="provider-identity__intro">(.*?)</div>\s*</div>', html, re.DOTALL).group(1)
    assert 'class="provider-logo"' in intro
    assert "Cabañas Demo" in intro
    assert 'class="provider-key-summary"' in html
    assert "Resumen del lugar" in html
    assert 'class="provider-identity__aside"' not in html


def test_provider_navigation_is_not_sticky():
    css = open("app/static/css/portal.css", encoding="utf-8").read()
    provider_css = css.split("/* PUBLIC PROVIDER PAGE", 1)[1]

    assert ".portal-topnav { margin-bottom: 24px; position: static; }" in provider_css
    assert "position: sticky" not in provider_css


def test_single_photo_grid_stays_full_width_between_481_and_700px():
    css = open("app/static/css/portal.css", encoding="utf-8").read()
    tablet_css = css.split("@media (max-width: 700px)", 1)[1].split("@media (max-width: 480px)", 1)[0]

    single_rule = re.search(
        r"\.public-gallery--count-1 \.public-gallery__grid \{([^}]*)\}", tablet_css
    ).group(1)
    assert "grid-template-columns: 1fr" in single_rule
    assert "repeat(2" not in single_rule


def test_two_photo_grid_keeps_two_columns_between_481_and_700px():
    css = open("app/static/css/portal.css", encoding="utf-8").read()
    tablet_css = css.split("@media (max-width: 700px)", 1)[1].split("@media (max-width: 480px)", 1)[0]

    two_photo_rule = re.search(
        r"\.public-gallery--count-2 \.public-gallery__grid \{([^}]*)\}", tablet_css
    ).group(1)
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in two_photo_rule


def test_category_is_rendered_once_without_a_duplicate_chip():
    html = render_prestador("alojamiento")

    assert html.count("Alojamientos · Cabaña") == 3
    assert html.count('class="provider-category"') == 1
    assert "tourism-heading-meta" not in html


def test_service_category_does_not_append_subtype_twice():
    html = render_prestador("servicios", subtipo="Almacén")

    assert html.count("Almacenes y kioscos · Almacén") == 2
    assert "Almacenes y kioscos · Almacén · Almacén" not in html


def test_service_practical_fact_uses_specific_subtype_only():
    html = render_prestador("servicios", subtipo="Almacén")
    identity = re.search(
        r'<div class="tourism-heading-card provider-identity">(.*?)</div>\s*</section>',
        html,
        re.DOTALL,
    ).group(1)
    practical = re.search(
        r'<section class="portal-card quick-facts-card">(.*?)</section>',
        html,
        re.DOTALL,
    ).group(1)

    assert identity.count("Almacenes y kioscos · Almacén") == 2
    assert "Resumen del lugar" in identity
    assert "Tipo de servicio" in practical
    assert "Almacén" in practical
    assert "Almacenes y kioscos · Almacén" not in practical


def test_schedules_are_plain_text_without_pill_nesting():
    html = render_prestador(identity_overrides={"horarios": "Días: Lunes a domingo | Horarios: 9:00 a 13:00 | Todo el año: Sí"})

    assert "Lunes a domingo" not in html
    assert html.count("Todos los días") == 2
    assert "9:00 a 13:00" in html
    assert "Abierto todo el año" in html
    assert 'class="provider-schedule-text"' in html
    assert "schedule-line" not in html


def test_empty_gallery_is_compact_and_has_no_mosaic():
    html = render_prestador("alojamiento", [])
    section = re.search(r'<section class="portal-card photos-summary-card photos-summary-card--empty" id="fotos">(.*?)</section>', html, re.DOTALL).group(1)

    assert "Fotos del lugar" in section
    assert "Todavía no hay fotos disponibles." in section
    assert "public-gallery__mosaic" not in section


def test_legacy_nested_identity_and_fact_classes_are_absent():
    html = render_prestador("alojamiento")

    assert "provider-identity__aside" not in html
    assert "prestador-contact-lines" not in html
    assert "provider-meta-icon" not in html
    assert "schedule-line" not in html


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
    assert "tourism-gallery--single" in hero
    assert 'class="tourism-gallery-side"' not in hero
    assert "public-gallery" not in hero
    assert "Fotos del lugar" in photos_section
    assert 'class="public-gallery public-gallery--count-1"' in photos_section
    assert html.count('class="public-gallery ') == 1
    assert html.count('id="fotos"') == 1


def test_public_gallery_exposes_every_thumbnail_and_lightbox_url():
    photos = [f"/media/empresas/demo/galeria/foto-{number}.webp" for number in range(1, 7)]
    html = render_prestador("alojamiento", photos)

    assert 'class="public-gallery public-gallery--count-4"' in html
    assert html.count('class="public-gallery__item"') == 6
    assert "Ver todas las fotos" in html
    assert html.count("/media/empresas/demo/galeria/foto-6.webp") == 2
    for photo in photos:
        assert photo in html


def test_provider_practical_grid_has_consistent_icons_and_existing_data():
    html = render_prestador(identity_overrides={"horarios": "Días: Lunes a domingo | Horarios: 9:00 a 13:00 | Todo el año: Sí"})
    section = re.search(r'<section class="portal-card quick-facts-card">(.*?)</section>', html, re.DOTALL).group(1)

    assert "Tipo de servicio" in section
    assert "Todos los días" in section
    assert "9:00 a 13:00" in section
    assert "Abierto todo el año" in section
    assert "Dirección" in section
    assert "Teléfono / WhatsApp" in section
    assert section.count('class="provider-icon"') == 4


def test_gallery_uses_uniform_grid_and_contain_lightbox():
    html = render_prestador("alojamiento", ["/one.webp", "/two.webp"])
    css = open("app/static/css/portal.css", encoding="utf-8").read()

    assert 'class="public-gallery__grid"' in html
    assert "public-gallery__mosaic" not in html
    assert "object-fit: cover" in css
    assert "object-fit: contain" in css


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
