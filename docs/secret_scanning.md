# Control automático de secretos

## Objetivo

`scripts/check_secrets.py` impide que el ciclo normal de validación publique
archivos privados conocidos o credenciales con formatos de alta confianza. No
lee archivos ignorados ni imprime el texto que produjo una coincidencia.

## Fuentes inspeccionadas

- Cada ruta devuelta por `git ls-files`.
- El contenido del working tree para archivos sin cambios staged.
- El blob exacto del índice para archivos agregados o modificados en staging.

Usar el blob staged evita que una credencial preparada para commit quede
oculta por una copia posterior y segura en el working tree. Los symlinks que
resuelven fuera del repositorio hacen fallar el chequeo.

## Políticas

El gate rechaza archivos `.env*`, configuración real de API/OAuth,
certificados, auditorías reales, memoria personal y logs. También detecta
formas de alta confianza de claves Google, GitHub, OpenAI, AWS y Slack, además
de encabezados de claves privadas.

Cada hallazgo contiene únicamente:

- ruta versionada;
- línea, cuando corresponde;
- identificador de regla;
- fuente `working-tree` o `staged`.

El valor coincidente nunca forma parte del resultado.

## Ejecución

```powershell
python scripts/check_secrets.py --repo-root .
```

`scripts/validate_baseline.ps1` ejecuta este comando después de `compileall` y
antes de los tests.

## Límites

- Los archivos no versionados no se inspeccionan: `.gitignore` y la revisión
  local siguen siendo obligatorios.
- Se priorizan formatos de alta confianza para evitar falsos positivos; no es
  un análisis genérico de entropía.
- El gate no limpia el historial ni revoca credenciales.
- Una credencial que alcanzó un commit o remoto debe rotarse aunque después se
  elimine.

## Rollback

La integración es independiente del runtime. Ante un falso positivo, ajustar
una regla y conservar una prueba de regresión. Retirar temporalmente la llamada
del baseline no modifica JARVIS, pero elimina una barrera preventiva y debe
quedar documentado.
