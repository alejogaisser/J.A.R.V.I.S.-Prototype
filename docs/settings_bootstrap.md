# Bootstrap de settings

## Alcance

`config.settings.AppSettings` es el contrato de configuración de todo el
proceso. El bootstrap se amplió durante la Fase 10 hasta reemplazar los lectores
y escritores directos de UI, actions, dashboard, memoria y clientes locales.

## Invariantes

- El documento debe ser JSON y su raíz debe ser un objeto.
- `gemini_api_key` y `os_system` deben ser strings.
- El OS normalizado sólo puede ser `windows`, `mac` o `linux`.
- La ausencia del archivo permite arrancar UI/configuración sin inventar una
  credencial.
- Un consumidor que necesita Gemini llama
  `require_gemini_api_key()` y recibe `SettingsError` si falta.
- La clave se excluye del `repr` del dataclass.
- Cada ruta se lee una vez y queda cacheada hasta una recarga o actualización
  explícita.

Los campos no migrados se preservan en un mapping de extras y
`config.get_config()` mantiene una vista dict para compatibilidad.

## Reconfiguración

`update_settings()` es el único escritor productivo. Fusiona cambios con la
vista existente, valida el documento completo y recién entonces publica un
temporal del mismo directorio mediante `fsync` + `os.replace`. El cache se
actualiza bajo el mismo lock. UI, visión y memoria usan esa operación; el loop
Live reutiliza el snapshot para reconectar y reconstruye el adaptador de
búsqueda cuando una clave inválida fue reemplazada.

No se usa un event bus para configuración, de acuerdo con el documento rector.

## Riesgos pendientes

La cache es local a cada proceso: una edición externa manual no se observa
hasta `refresh_settings()` o un nuevo proceso. No hay lock interproceso para
dos escritores simultáneos. Los adaptadores heredados conservan sus funciones
auxiliares, pero delegan al owner central.

## Rollback

`config.get_config()` y las funciones auxiliares heredadas conservan sus
firmas. El rollback puede redirigir consumidores a esa vista sin cambiar el
formato físico del documento.

## Verificación

`tests/test_settings.py` cubre archivo ausente, JSON corrupto, tipos inválidos,
cache, refresh explícito, actualización atómica, preservación de extras,
rechazo sin reemplazo, error por clave faltante, redacción en `repr` y
ownership único de lectura/escritura.
