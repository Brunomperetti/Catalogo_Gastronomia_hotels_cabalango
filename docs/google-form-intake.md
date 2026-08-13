# Ingreso privado desde Google Forms

## Diagnóstico y arquitectura reutilizada

Antes de implementar esta etapa se auditó el almacenamiento y el flujo vigente. La
aplicación usa `MEDIA_ROOT` (o `STORAGE_DIR`, con fallback `app/storage`) como raíz
del disco persistente, `empresas/<slug>/...` para logo, portada, galería y productos,
filenames generados con UUID, normalización con `Path.name` y comprobaciones con
`resolve()` antes de eliminar archivos. El mount histórico `/media` sirve esa raíz.
Las subidas publicadas validaban principalmente extensión; para el staging se
reutilizan la raíz persistente y las convenciones de nombres, pero se agrega
inspección del contenido con Pillow para imágenes y firmas de contenedor para video.

Los archivos provisionales usan el modelo independiente
`SolicitudPrestadorArchivo` y se guardan en:

```text
<STORAGE_DIR>/intake/<solicitud_id>/<kind>/<nombre-uuid.ext>
```

La ruta `/media/intake` está bloqueada incluso aunque exista el mount histórico. El
único acceso de lectura es la ruta admin autenticada, que busca por IDs y comprueba
pertenencia y confinamiento del path. No se usa `/tmp`, el repositorio Git ni Google
Drive desde el backend.

## Flujo JSON existente

Definir `FORM_INTAKE_SECRET` con un valor confidencial aleatorio de al menos 32
caracteres. No hay valor por defecto. El emisor hace
`POST /api/internal/intake/google-form`, envía JSON (máximo 256 KiB) y usa:

```text
Authorization: Bearer <FORM_INTAKE_SECRET>
```

El payload original se conserva sin alteraciones en `SolicitudPrestador.raw_payload`.
`external_id` es único; un reintento responde `200 already_received`.

## Contrato de importación de media para Apps Script

Apps Script, que sí tiene permiso para leer el archivo de Forms, debe enviar cada
binario por separado:

```text
POST /api/internal/intake/google-form/{external_id}/media
Authorization: Bearer <FORM_INTAKE_SECRET>
Content-Type: multipart/form-data; boundary=...

kind=cover
drive_file_id=<id estable de Google Drive>
file=<binario>
```

Los tres campos son obligatorios. `kind` admite `logo`, `cover`, `gallery` o
`video`. Logo, cover y cada imagen de galería aceptan JPEG, PNG o WebP; video
acepta MP4, WebM u Ogg. El formato se detecta desde el contenido y no se confía en
el filename o Content-Type del cliente. Todos tienen un máximo de 10 MiB por
archivo. Los máximos por solicitud son 1 logo, 1 cover, 5 imágenes de galería y 1
video. Los nombres originales se reducen a un basename seguro y el nombre físico
lo genera el servidor.

Respuestas relevantes:

- `201 {"status":"received", ...}`: almacenado y registrado.
- `200 {"status":"already_received", ...}`: ya existía la combinación solicitud,
  kind y `drive_file_id`; no se escribió una copia.
- `401`: secreto ausente, corto en la configuración o incorrecto (mensaje genérico).
- `404`: `external_id` no corresponde a una solicitud existente.
- `409`: se alcanzó la cantidad permitida para ese kind.
- `413`: supera 10 MiB.
- `415`: el contenido no es una imagen/video permitido.
- `422`: campos multipart inválidos.

La restricción única en base de datos hace persistente la idempotencia y también
protege frente a reintentos concurrentes.

## Administración, privacidad y siguiente etapa

El detalle admin muestra previews protegidas, estado **Importado** o **Pendiente de
importar**, nombre, tamaño y MIME detectado. La metadata y el payload íntegro quedan
en disclosures técnicos. Los datos específicos se presentan como etiqueta/valor
con Unicode normal.

Importar no cambia el estado de la solicitud ni crea `Empresa` o
`ActividadAgenda`; tampoco publica contenido. La aprobación/conversión explícita
será una etapa posterior. El rechazo no borra staging en esta etapa: una política
futura deberá definir retención, auditoría y una limpieza segura y transaccional
antes de habilitar cualquier borrado automático.
