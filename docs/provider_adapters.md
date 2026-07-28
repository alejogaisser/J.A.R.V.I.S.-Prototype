# Adaptadores de proveedores

## Límite

Los casos de uso no deben importar SDKs de modelos, leer credenciales ni elegir
modelos. `core.providers` declara cuatro puertos:

- `LiveConversationProvider`;
- `TextGenerationProvider`;
- `VisionAnalysisProvider`;
- `GroundedSearchProvider`.

La Fase 9 migra productivamente sólo `web_search`. Los otros tres contratos
permiten migraciones posteriores sin cambiar de una vez audio, cámara o las
acciones que generan texto.

## Piloto de búsqueda

`JarvisLive` construye `GoogleGroundedSearchProvider` después de que la
configuración local está disponible y lo inyecta en ambos caminos de
`web_search`. La acción sólo llama `provider.search(query)` y conserva
DuckDuckGo como backend independiente.

El adaptador es dueño de:

- modelos primario y fallback;
- timeout HTTP en milisegundos;
- configuración de Google grounded search;
- extracción y validación de la respuesta;
- clasificación de timeout, cuota, fallo transitorio y fallo permanente.

Un 5xx transitorio puede probar el siguiente modelo. Un 429 no hace model
hopping: se convierte en `ProviderQuotaError` para que el caso de uso cambie de
backend. Un 403 u otro error permanente tampoco reintenta otro modelo.

## Seguridad

La credencial sólo entra en `from_api_key()` y no se guarda en errores,
resultados o logs. Los tests usan clientes falsos; no leen `api_keys.json`, no
abren red y no registran prompts ni respuestas reales.

## Rollback

La firma pública de `web_search` conserva sus argumentos previos y añade un
provider opcional. Retirar el piloto requiere reinyectar un adaptador de
compatibilidad; DDG sigue funcionando cuando no hay provider.

## Verificación

`tests/test_provider_adapters.py` cubre contratos, inyección, fallback de
backend, fallback de modelo, timeout, cuota, errores permanentes y respuestas
vacías. `tests/test_clock.py` usa un provider falso para verificar la fecha de
las noticias sin SDK ni red.
