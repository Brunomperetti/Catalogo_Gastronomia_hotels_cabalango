from pathlib import Path
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
        alojamiento_modalidad=None,
        alojamiento_detalle_unidades=None,
    )
    identity_overrides = identity_overrides or {}
    for field, value in identity_overrides.items():
        if hasattr(empresa, field):
            setattr(empresa, field, value)
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
        is_alojamiento_complejo=lambda empresa: (
            empresa.theme == "alojamiento" and empresa.alojamiento_modalidad == "complejo"
        ),
        get_alojamiento_card_type=lambda empresa: "COMPLEJO" if empresa.alojamiento_modalidad == "complejo" else empresa.subtipo,
        build_alojamiento_key_facts=lambda empresa: (
            [empresa.alojamiento_detalle_unidades]
            if empresa.alojamiento_detalle_unidades
            else ([f"Hasta {re.search(r'\d+', empresa.capacidad).group()} personas por unidad"] if empresa.capacidad else [])
        ),
        actividad_subgrupos={},
    )


def test_provider_stylesheet_uses_promo_lightbox_cache_key():
    template = Path("app/templates/prestador.html").read_text(encoding="utf-8")

    assert "?v=20260831-provider-promo-cascade-fix-2" in template
    assert "?v=20260814-provider-promo-lightbox-1" not in template
    assert "?v=20260814-provider-opening-1" not in template
    assert "?v=20260810-commerce-services-1" not in template


def test_prestador_template_is_tourism_first_for_alojamiento():
    html = render_prestador("alojamiento", ["/media/empresas/demo/galeria/foto-1.webp"])

    assert "Consultar por WhatsApp" in html
    assert "Ver todas las fotos" in html
    assert "Opiniones de huéspedes" in html
    assert "Información práctica" not in html
    assert "Descargar lista de precios" not in html
    assert "Productos / platos publicados" not in html


def test_prestador_template_empty_gallery_does_not_break():
    html = render_prestador("alojamiento", [])

    assert "Todavía no hay fotos cargadas" not in html
    assert "Todavía no hay fotos disponibles." in html
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
    assert 'class="provider-identity__main provider-identity__main--no-logo"' in html
    assert 'class="provider-identity__brand"' not in html
    assert 'class="provider-logo"' not in html
    assert "Cabalango</span>" not in html
    assert "Cabañas Demo" in html
    assert "Alojamientos · Cabaña" in html
    assert 'aria-label="Acciones principales"' in html
    assert 'class="provider-identity__aside"' not in html
    assert 'class="provider-metadata"' not in html


def test_provider_identity_integrates_logo_title_and_metadata():
    html = render_prestador(identity_overrides={
        "empresa_logo_url": "/logo.webp", "direccion": "Ruta demo 123", "horarios": "", "whatsapp": ""
    })

    assert 'class="tourism-heading-card provider-identity"' in html
    opening = re.search(r'<div class="provider-identity__main">(.*?)</div>\s*<aside', html, re.DOTALL).group(1)
    assert 'class="provider-identity__brand"' in opening
    assert 'class="provider-logo"' in opening
    assert "provider-identity__main--no-logo" not in html
    assert 'class="provider-identity__content"' in opening
    assert "Cabañas Demo" in opening
    assert 'aria-label="Acciones principales"' in opening
    assert 'class="provider-key-summary"' in html
    assert "Resumen del lugar" in html
    assert 'class="provider-identity__aside"' not in html


def test_provider_identity_no_logo_css_never_reserves_a_brand_column():
    css = Path("app/static/css/portal.css").read_text(encoding="utf-8")
    no_logo_rules = re.findall(
        r"\.provider-identity__main--no-logo \{([^}]*)\}", css
    )

    assert len(no_logo_rules) == 4
    assert all("grid-template-columns: 1fr" in rule for rule in no_logo_rules)


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

    assert html.count("Alojamientos · Cabaña") == 2
    assert html.count('class="provider-category"') == 1
    assert "tourism-heading-meta" not in html


def test_complex_accommodation_identifies_type_and_shows_stored_units_in_summary():
    detail = "Cabañas hasta 6 personas · Monoambientes para 2–3 personas"
    html = render_prestador(identity_overrides={
        "alojamiento_modalidad": "complejo",
        "alojamiento_detalle_unidades": detail,
        "capacidad": "6",
    })
    summary = re.search(r'<aside class="provider-key-summary".*?</aside>', html, re.DOTALL).group(0)

    assert html.count("Alojamientos · COMPLEJO") == 2
    assert "Alojamientos · Cabaña" not in html
    assert "Unidades" in summary
    assert detail in summary
    assert summary.index("Propuesta") < summary.index("Unidades") < summary.index("Horarios")
    assert summary.index("Horarios") < summary.index("Ubicación") < summary.index("Contacto directo")


def test_complex_accommodation_units_fall_back_to_capacity_per_unit():
    html = render_prestador(identity_overrides={
        "alojamiento_modalidad": "complejo",
        "alojamiento_detalle_unidades": "",
        "capacidad": "6",
    })

    assert "Unidades" in html
    assert "Hasta 6 personas por unidad" in html


def test_individual_accommodation_keeps_subtype_without_units_row():
    html = render_prestador(identity_overrides={
        "alojamiento_modalidad": "individual",
        "capacidad": "4",
    })

    assert html.count("Alojamientos · Cabaña") == 2
    assert "Unidades" not in html


def test_non_accommodation_summary_does_not_gain_units_row():
    html = render_prestador("servicios", identity_overrides={
        "alojamiento_modalidad": "complejo",
        "alojamiento_detalle_unidades": "Locales para 2 personas",
    }, subtipo="Almacén")

    assert html.count("Almacenes y kioscos · Almacén") == 2
    assert "Unidades" not in html


def test_service_category_does_not_append_subtype_twice():
    html = render_prestador("servicios", subtipo="Almacén")

    assert html.count("Almacenes y kioscos · Almacén") == 2
    assert "Almacenes y kioscos · Almacén · Almacén" not in html


def test_identity_is_first_content_section_and_keeps_complete_summary():
    html = render_prestador(
        "servicios",
        ["/media/empresas/demo/galeria/foto-1.webp"],
        identity_overrides={"horarios": "Días: Lunes a domingo | Horarios: 9:00 a 13:00"},
        subtipo="Almacén",
    )
    main_content = html.split("</nav>", 1)[-1]
    first_section = re.search(r'<section class="([^"]+)">', main_content).group(1)
    identity = re.search(r'<section class="tourism-heading-card provider-identity">(.*?)</section>', html, re.DOTALL).group(1)

    assert first_section == "tourism-heading-card provider-identity"
    assert "tourism-gallery" not in html
    assert "tourism-gallery-main" not in html
    assert "tourism-gallery-side" not in html
    assert "Resumen del lugar" in identity
    assert "Propuesta" in identity
    assert "Horarios" in identity
    assert "Ubicación" in identity
    assert "Contacto directo" in identity
    assert "Ruta demo 123" in identity
    assert "5493510000000" in identity


def test_schedules_are_plain_text_without_pill_nesting():
    html = render_prestador(identity_overrides={"horarios": "Días: Lunes a domingo | Horarios: 9:00 a 13:00 | Todo el año: Sí"})

    assert "Lunes a domingo" not in html
    assert html.count("Todos los días") == 1
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
    assert "provider-identity__intro" not in html
    assert "provider-identity__body" not in html


def test_upper_hero_and_practical_information_are_completely_removed():
    html = render_prestador("alojamiento", ["/media/empresas/demo/galeria/foto-1.webp"])
    identity_position = html.index('class="tourism-heading-card provider-identity"')

    assert "tourism-hero" not in html
    assert "tourism-gallery" not in html[:identity_position]
    assert "Ver todas las fotos" not in html[:identity_position]
    assert "Datos útiles" not in html
    assert "Información práctica" not in html
    assert "quick-facts-card" not in html
    assert "quick-facts-grid" not in html


def test_lower_gallery_remains_the_only_gallery_with_one_lightbox():
    html = render_prestador("alojamiento", ["/one.webp", "/two.webp"])
    photos_section = re.search(
        r'<section class="portal-card photos-summary-card" id="fotos">(.*?)</section>',
        html,
        re.DOTALL,
    ).group(1)

    assert 'class="public-gallery__grid"' in photos_section
    assert "data-public-gallery" in photos_section
    assert "data-gallery-open" in photos_section
    assert "Ver todas las fotos" in photos_section
    assert html.count('class="public-gallery-lightbox"') == 1
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


def test_remaining_provider_sections_are_preserved():
    html = render_prestador("alojamiento", ["/one.webp"], identity_overrides={"empresa_logo_url": "/logo.webp", "promocion": "10% de descuento"})

    assert 'id="descripcion"' in html
    assert "Contacto" in html
    assert "PROMO VIGENTE" in html
    assert "10% de descuento" in html
    assert 'id="fotos"' in html
    assert 'id="opiniones"' in html
    assert 'id="ubicacion"' in html
    assert "Video" in html


def test_gallery_uses_uniform_grid_and_contain_lightbox():
    html = render_prestador("alojamiento", ["/one.webp", "/two.webp"])
    css = open("app/static/css/portal.css", encoding="utf-8").read()

    assert 'class="public-gallery__grid"' in html
    assert "public-gallery__mosaic" not in html
    image_rule = re.search(
        r"\.portal-body \.prestador-page \.public-gallery-lightbox__image \{([^}]*)\}", css
    ).group(1)
    stage_rule = re.search(
        r"\.portal-body \.prestador-page \.public-gallery-lightbox__stage \{([^}]*)\}", css
    ).group(1)

    assert "object-fit: contain" in image_rule
    assert "object-position: center" in image_rule
    assert "max-height: 100%" in image_rule and "max-width: 100%" in image_rule
    assert "width: auto" in image_rule and "height: auto" in image_rule
    assert "object-fit: cover" not in image_rule
    assert "flex: 1 1 0" in stage_rule
    assert "grid-template-rows: minmax(0, 1fr)" in stage_rule
    assert "min-height: 0" in stage_rule
    assert "height: 100%" not in stage_rule
    assert "overflow: hidden" in stage_rule and "place-items: center" in stage_rule


def test_provider_promotion_uses_the_high_contrast_editorial_treatment():
    html = render_prestador(identity_overrides={"promocion": "10% de descuento"})
    css = Path("app/static/css/portal.css").read_text(encoding="utf-8")

    assert 'class="promo-highlight" aria-label="Promoción vigente"' in html
    promo_rule = re.search(
        r"\.portal-body \.prestador-page \.promo-highlight \{([^}]*)\}", css
    ).group(1)
    title_rule = re.search(
        r"\.portal-body \.prestador-page \.promo-highlight > div > strong \{([^}]*)\}", css
    ).group(1)

    assert "linear-gradient(135deg, #5A392B 0%, #4A2F25 55%, #3F281F 100%)" in promo_rule
    assert "color: #FFF7EE" in title_rule


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
        is_alojamiento_complejo=lambda empresa: False,
        get_alojamiento_card_type=lambda empresa: empresa.subtipo,
        build_alojamiento_key_facts=lambda empresa: [],
    )

    assert 'href="https://facebook.com/golata007"' in html
    assert 'href="https://facebook.com/cabanas"' in html
    assert 'href="https://instagram.com/cabanas_demo"' in html
    assert 'href="/prestador/facebook.com/golata007"' not in html
