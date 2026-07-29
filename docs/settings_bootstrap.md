# Bootstrap de settings

## Alcance

Este incremento inicia la Fase 10 sin mezclar logging ni CI.
`config.settings.AppSettings` es el contrato de configuración del proceso para
el composition root. No reemplaza todavía los lectores heredados de todas las
actions.

## Invariantes

- El documento debe ser JSON y su raíz debe ser un objeto.
- `gemini_api_key` y `os_system` deben ser strings.
- El OS normalizado sólo puede ser `windows`, `mac` o `linux`.
- La ausencia del archivo permite arrancar UI/configuración sin inventar una
  credencial.
- Un consumidor que necesita Gemini llama
  `require_gemini_api_key()` y recibe `SettingsError` si falta.
- La clave se excluye del `repr` del dataclass.
- Cada ruta se lee una vez y queda cacheada hasta una recarga explícita.

Los campos no migrados se preservan en un mapping de extras y
`config.get_config()` mantiene una vista dict para compatibilidad.

## Reconfiguración

La UI sigue siendo el escritor actual de `api_keys.json`. Después de publicar
el documento llama `refresh_settings(API_FILE)`. El loop Live reutiliza el
snapshot para reconectar y reconstruye el adaptador de búsqueda cuando una
clave inválida fue reemplazada.

No se usa un event bus para configuración, de acuerdo con el documento rector.

## Riesgos pendientes

Actions, dashboard y `memory/config_manager.py` todavía leen el archivo por su
cuenta. Migrarlos junto con sus interfaces de proveedor evita un refactor
masivo y permite probar equivalencia por familia. Logging estructurado,
rotación, lint, type checking, secret scanning automatizado y CI siguen fuera
de este incremento.

## Rollback

`config.get_config()` conserva su firma. Para revertir el bootstrap, `main.py`
puede volver temporalmente a esa vista compatible y la llamada de refresh en
UI puede retirarse; el formato físico de `api_keys.json` no cambió.

## Verificación

`tests/test_settings.py` cubre archivo ausente, JSON corrupto, tipos inválidos,
cache, refresh explícito, error por clave faltante y redacción en `repr`.
