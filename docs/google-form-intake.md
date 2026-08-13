# Ingreso privado desde Google Forms

## Arquitectura reutilizada

La implementación usa el `Base`, el motor y las sesiones SQLAlchemy existentes,
la creación aditiva e idempotente de tablas durante el mantenimiento de inicio,
las rutas FastAPI del módulo principal, la sesión de administrador existente y
templates Jinja con autoescape. `SolicitudPrestador` es una bandeja de entrada
independiente: no tiene relación ni automatización hacia `Empresa` o
`ActividadAgenda`.

## Configuración

Definir `FORM_INTAKE_SECRET` con un valor largo, aleatorio y confidencial en el
entorno de la aplicación. No existe valor por defecto. Si falta, el endpoint
responde `401` de forma segura.

El emisor debe hacer `POST /api/internal/intake/google-form`, enviar JSON y usar:

```text
Authorization: Bearer <FORM_INTAKE_SECRET>
```

El cuerpo máximo aceptado es 256 KiB. El payload original se conserva como
texto JSON en SQLite; no se descarga metadata de archivos ni se contacta a
Google Drive. `external_id` es único y hace que reintentos respondan
`already_received` sin insertar otra fila.

## Alcance y siguiente etapa

El admin solo permite marcar una solicitud como `revisando`, agregar notas o
rechazarla. No existe aún una acción de aprobación/conversión. Una etapa futura
deberá definir el mapeo explícito por rubro y crear `Empresa` o
`ActividadAgenda` únicamente mediante una decisión administrativa.
