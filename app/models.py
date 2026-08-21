from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from .database import Base


class Empresa(Base):
    __tablename__ = "empresas"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True)
    whatsapp = Column(String, nullable=True)
    telefono = Column(String, nullable=True)
    instagram = Column(String, nullable=True)
    direccion = Column(String, nullable=True)
    maps_url = Column(String, nullable=True)
    subgrupo = Column(String, nullable=True)
    subtipo = Column(String, nullable=True)
    descripcion_corta = Column(String, nullable=True)
    facebook = Column(String, nullable=True)
    web_url = Column(String, nullable=True)
    destacado = Column(Boolean, nullable=True)
    activo = Column(Boolean, nullable=True)
    logo_url = Column(String, nullable=True)
    banner_url = Column(String, nullable=True)
    politica_precio_catalogo = Column(String, nullable=False, default="automatico")
    politica_stock_catalogo = Column(String, nullable=False, default="mostrar")
    theme = Column(String, nullable=False, default="default")
    descripcion = Column(Text, nullable=True)
    horarios = Column(String, nullable=True)
    precio_desde = Column(String, nullable=True)
    capacidad = Column(String, nullable=True)
    habitaciones = Column(String, nullable=True)
    banos = Column(String, nullable=True)
    video_url = Column(String, nullable=True)
    menu_url = Column(String, nullable=True)
    promocion = Column(String, nullable=True)
    guardia = Column(String, nullable=True)
    fecha = Column(String, nullable=True)
    organizador = Column(String, nullable=True)
    lugar_encuentro = Column(String, nullable=True)
    delivery = Column(Boolean, nullable=True)
    take_away = Column(Boolean, nullable=True)
    comer_en_lugar = Column(Boolean, nullable=True)
    pileta = Column(Boolean, nullable=True)
    rio = Column(Boolean, nullable=True)
    mascotas = Column(Boolean, nullable=True)
    cochera = Column(Boolean, nullable=True)
    wifi = Column(Boolean, nullable=True)
    parrilla = Column(Boolean, nullable=True)
    aire_acondicionado = Column(Boolean, nullable=True)
    calefaccion = Column(Boolean, nullable=True)
    galeria_urls = Column(Text, nullable=True)
    menu_fotos_urls = Column(Text, nullable=True)
    rating_promedio = Column(Float, nullable=True)
    rating_cantidad = Column(Integer, nullable=True)
    reviews_destacadas = Column(Text, nullable=True)

    productos = relationship(
        "Producto",
        back_populates="empresa",
        cascade="all, delete-orphan"
    )
    usuarios = relationship("Usuario", back_populates="empresa")
    leads = relationship("CatalogLead", back_populates="empresa_rel", cascade="all, delete-orphan")
    lead_events = relationship("CatalogLeadEvent", back_populates="empresa", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="prestador", cascade="all, delete-orphan")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    prestador_id = Column(Integer, ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = Column(String, nullable=False)
    contacto = Column(String, nullable=True)
    rating = Column(Integer, nullable=False)
    comentario = Column(Text, nullable=False)
    tipo_visitante = Column(String, nullable=True)
    fecha = Column(String, nullable=True)
    estado = Column(String, nullable=False, default="pendiente", index=True)
    visible = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    prestador = relationship("Empresa", back_populates="reviews")


class Producto(Base):
    __tablename__ = "productos"

    id = Column(Integer, primary_key=True, index=True)

    empresa_id = Column(
        Integer,
        ForeignKey("empresas.id", ondelete="CASCADE"),
        nullable=False
    )

    codigo = Column(String, nullable=False)
    descripcion = Column(String, nullable=False)

    categoria = Column(String, nullable=True)
    marca = Column(String, nullable=True)

    precio = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
    activo = Column(Boolean, default=True)

    # Imagen del producto (para edición individual futura)
    imagen_url = Column(String, nullable=True)

    empresa = relationship("Empresa", back_populates="productos")


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    rol = Column(String, nullable=False, default="cliente")  # admin | cliente
    activo = Column(Boolean, nullable=False, default=True)

    empresa_id = Column(
        Integer,
        ForeignKey("empresas.id", ondelete="SET NULL"),
        nullable=True
    )

    empresa = relationship("Empresa", back_populates="usuarios")


class CatalogLead(Base):
    __tablename__ = "catalog_leads"

    id = Column(Integer, primary_key=True, index=True)
    empresa_catalogo_id = Column(
        Integer,
        ForeignKey("empresas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nombre = Column(String, nullable=False)
    empresa = Column(String, nullable=False)
    email = Column(String, nullable=False, index=True)
    telefono = Column(String, nullable=True)
    fecha_ingreso = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    ultima_actividad = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    session_token = Column(String, nullable=True, index=True)
    estado = Column(String, nullable=False, default="nuevo", index=True)
    notas_internas = Column(Text, nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    empresa_rel = relationship("Empresa", back_populates="leads")
    eventos = relationship("CatalogLeadEvent", back_populates="lead", cascade="all, delete-orphan")


class CatalogLeadEvent(Base):
    __tablename__ = "catalog_lead_events"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(
        Integer,
        ForeignKey("catalog_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    empresa_catalogo_id = Column(
        Integer,
        ForeignKey("empresas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = Column(String, nullable=False, index=True)
    product_code = Column(String, nullable=True)
    search_term = Column(String, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    lead = relationship("CatalogLead", back_populates="eventos")
    empresa = relationship("Empresa", back_populates="lead_events")


class DestinoMedia(Base):
    __tablename__ = "destino_media"

    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(String, nullable=False, default="foto", index=True)
    categoria = Column(String, nullable=False, default="rio_naturaleza", index=True)
    titulo = Column(String, nullable=True)
    descripcion = Column(Text, nullable=True)
    image_path = Column(String, nullable=True)
    video_url = Column(String, nullable=True)
    destacado = Column(Boolean, nullable=False, default=False, index=True)
    orden = Column(Integer, nullable=False, default=0, index=True)
    visible = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class LugarDescubrir(Base):
    __tablename__ = "lugares_descubrir"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True, index=True)
    categoria = Column(String, nullable=False, index=True)
    descripcion_corta = Column(String(180), nullable=False, default="")
    descripcion = Column(Text, nullable=True)
    imagen_principal_url = Column(String, nullable=True)
    maps_url = Column(String, nullable=True)
    como_llegar = Column(Text, nullable=True)
    servicios = Column(Text, nullable=True)
    recomendaciones = Column(Text, nullable=True)
    visible = Column(Boolean, nullable=False, default=False, index=True)
    destacado = Column(Boolean, nullable=False, default=False, index=True)
    orden = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    fotos = relationship("LugarDescubrirFoto", back_populates="lugar", cascade="all, delete-orphan", order_by="LugarDescubrirFoto.orden, LugarDescubrirFoto.id")


class LugarDescubrirFoto(Base):
    __tablename__ = "lugares_descubrir_fotos"

    id = Column(Integer, primary_key=True, index=True)
    lugar_id = Column(Integer, ForeignKey("lugares_descubrir.id", ondelete="CASCADE"), nullable=False, index=True)
    image_url = Column(String, nullable=False)
    orden = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    lugar = relationship("LugarDescubrir", back_populates="fotos")


class DestinoContenido(Base):
    __tablename__ = "destino_contenido"

    id = Column(Integer, primary_key=True, index=True)
    introduccion = Column(Text, nullable=True)
    historia = Column(Text, nullable=True)
    ubicacion = Column(Text, nullable=True)
    naturaleza = Column(Text, nullable=True)
    recomendaciones = Column(Text, nullable=True)
    vida_local = Column(Text, nullable=True)
    video_url = Column(String, nullable=True)
    visible = Column(Boolean, nullable=False, default=True, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class ActividadAgenda(Base):
    """Editorial activity/event content, deliberately separate from providers."""
    __tablename__ = "actividades_agenda"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('borrador','programado','reprogramado','cancelado','realizado')",
            name="ck_actividades_agenda_estado",
        ),
        CheckConstraint(
            "prioridad_home BETWEEN 0 AND 100",
            name="ck_actividades_agenda_prioridad_home",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(String, nullable=False, index=True)
    titulo = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True, index=True)
    descripcion_corta = Column(String, nullable=True)
    descripcion = Column(Text, nullable=True)
    categoria = Column(String, nullable=False, default="otros", index=True)
    momento = Column(String, nullable=False, default="todo_el_dia", index=True)
    fecha_inicio = Column(DateTime(timezone=True), nullable=True, index=True)
    fecha_fin = Column(DateTime(timezone=True), nullable=True, index=True)
    horarios = Column(String, nullable=True)
    lugar = Column(String, nullable=True)
    direccion = Column(String, nullable=True)
    maps_url = Column(String, nullable=True)
    whatsapp = Column(String, nullable=True)
    instagram = Column(String, nullable=True)
    url_externa = Column(String, nullable=True)
    imagen_url = Column(String, nullable=True)
    publicado = Column(Boolean, nullable=False, default=False, index=True)
    oficial = Column(Boolean, nullable=False, default=False, index=True)
    estado = Column(String, nullable=False, default="programado", index=True)
    publicar_desde = Column(DateTime(timezone=True), nullable=True, index=True)
    destacar_home_desde = Column(DateTime(timezone=True), nullable=True, index=True)
    ocultar_desde = Column(DateTime(timezone=True), nullable=True, index=True)
    mostrar_en_home = Column(Boolean, nullable=False, default=False, index=True)
    prioridad_home = Column(Integer, nullable=False, default=0, index=True)
    destacado = Column(Boolean, nullable=False, default=False, index=True)
    orden = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class SolicitudPrestador(Base):
    """Untrusted provider intake, kept separate from publishable content."""
    __tablename__ = "solicitudes_prestadores"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pendiente','revisando','aprobada','rechazada','procesada')",
            name="ck_solicitudes_prestadores_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), nullable=False, unique=True, index=True)
    source = Column(String(50), nullable=False, default="google_form")
    received_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    status = Column(String(20), nullable=False, default="pendiente", index=True)
    business_type = Column(String(100), nullable=True, index=True)
    business_name = Column(String(255), nullable=True)
    contact_name = Column(String(255), nullable=True)
    phone = Column(String(100), nullable=True)
    public_whatsapp = Column(String(100), nullable=True)
    email = Column(String(320), nullable=True)
    instagram = Column(String(500), nullable=True)
    facebook = Column(String(500), nullable=True)
    website = Column(String(500), nullable=True)
    address = Column(String(500), nullable=True)
    directions = Column(Text, nullable=True)
    maps_url = Column(String(1000), nullable=True)
    description = Column(Text, nullable=True)
    opening_hours = Column(Text, nullable=True)
    payment_methods = Column(Text, nullable=True)
    highlights = Column(Text, nullable=True)
    raw_payload = Column(Text, nullable=False)
    review_notes = Column(Text, nullable=True)
    converted_entity_type = Column(String(30), nullable=True, index=True)
    converted_entity_id = Column(Integer, nullable=True, index=True)
    processed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    archivos = relationship("SolicitudPrestadorArchivo", back_populates="solicitud", cascade="all, delete-orphan")


class SolicitudPrestadorArchivo(Base):
    """Private, provisional media received for an intake request."""
    __tablename__ = "solicitudes_prestadores_archivos"
    __table_args__ = (
        UniqueConstraint("solicitud_id", "kind", "drive_file_id", name="uq_intake_file_external_kind"),
        CheckConstraint("kind IN ('logo','cover','gallery','video')", name="ck_intake_file_kind"),
    )

    id = Column(Integer, primary_key=True, index=True)
    solicitud_id = Column(Integer, ForeignKey("solicitudes_prestadores.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False, index=True)
    drive_file_id = Column(String(255), nullable=False)
    original_name = Column(String(500), nullable=False)
    stored_name = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=False)
    size = Column(Integer, nullable=False)
    relative_path = Column(String(1000), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    solicitud = relationship("SolicitudPrestador", back_populates="archivos")
