# Almacenamiento de imágenes del destino

## Cadena de entrega

La variable `MEDIA_ROOT` define `STORAGE_DIR`; si no existe, se usa `STORAGE_DIR` y,
como último fallback local, `app/storage`. `StaticFiles` publica esa raíz completa en
`MEDIA_URL` (por defecto `/media`). Por lo tanto la correspondencia es directa:

```text
MEDIA_ROOT=/var/data
URL /media/destino/fotos/<archivo>
archivo /var/data/destino/fotos/<archivo>
```

`save_destino_image()` usa exactamente `STORAGE_DIR/destino/fotos`, genera
`cabalango-<uuid>.<ext>` y retorna `/media/destino/fotos/<archivo>`. Los lugares se
guardan en `STORAGE_DIR/lugares/<slug>` y los prestadores (logos, portadas, galerías
y productos) en `STORAGE_DIR/empresas/<slug>/...`; todos comparten la misma raíz y
el mismo mount público.

## Causa raíz auditada en Render

La configuración anterior de `render.yaml` no declaraba disco ni `MEDIA_ROOT`. En
producción esto activaba el fallback relativo `app/storage`, dentro del filesystem
efímero del servicio. La escritura y el mount `/media` sí coincidían durante una
misma instancia, pero un deploy/reinicio podía descartar los archivos mientras los
registros `DestinoMedia.image_path` sobrevivían en la base de datos. El resultado
era un registro válido que generaba un `<img src="/media/...">` y luego obtenía 404.

El Blueprint ahora monta el disco `catalogo-media` en `/var/data` y define
`MEDIA_ROOT=/var/data`. Las URL almacenadas no cambian. Un disco persistente de
Render requiere un plan compatible; por eso el servicio se declara `starter`.

## Diagnóstico y recuperación

Ejecutar, con las variables de producción configuradas:

```bash
PYTHONPATH=. python scripts/audit_destino_media.py
```

El script es de solo lectura respecto de los registros y lista únicamente `id`,
`tipo`, `uso_portal`, `visible`, `image_path`, ruta física derivada y existencia
para `home_hero`. No imprime secretos. El admin conserva los registros huérfanos y
los marca **Archivo no disponible**.

Este cambio no inventa ni mueve archivos perdidos. Los registros cuyo archivo ya
se perdió deben recuperarse desde un backup o reemplazarse manualmente desde el
admin después de montar el disco. No se deben borrar registros ni migrar rutas a
ciegas.
