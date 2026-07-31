# Historial de versiones

## Preparación de publicación pública — 2026-07-31

- se agregó `NOTICE.md` con la procedencia exacta de Mark XLVIII, su autor,
  licencia y commit de referencia;
- se aclaró que Mark LI publica código fuente para uso personal y no comercial,
  sin reclamar derechos sobre material original o de terceros;
- se incorporó un aviso de no afiliación con Marvel/Disney;
- la plantilla OAuth de Google ahora usa placeholders inequívocos;
- `output/` quedó excluido para evitar publicar artefactos generados;
- se añadieron pruebas de regresión para créditos, placeholders, modelos y
  metadatos de publicación.
- los cambios de Google Workspace, wake, arranque y publicación se portaron al
  `main` moderno preservando sus contratos de policy, providers y trazabilidad.

## Publicación segura — 2026-07-23

- se incorporaron la licencia del proyecto, los avisos de terceros y la
  política de seguridad;
- se excluyeron del versionado las instrucciones locales de desarrollo;
- se preparó la eliminación de rutas personales de todos los commits y tags
  públicos sin alterar el código de las versiones.

## 2.0.0 — Mark LI — 2026-07-23

Mark LI consolida la evolución actual de JARVIS como una actualización mayor:

- nueva interfaz holográfica con Core, Pet Mode y workspaces;
- activación local “Hey Jarvis” con OpenWakeWord y fallback Vosk;
- corrección del desfase entre voz y score neuronal, sin reducir los umbrales contra falsos positivos;
- recuperación automática del stream de audio después de mute, silencio o bloqueo del driver;
- memoria controlable, vencimientos y grafo exclusivo de recuerdos reales;
- registro central de herramientas, permisos por riesgo y confirmaciones de voz;
- Study para matemática, física, química, anatomía y visualizaciones 2D/3D;
- GEO con mapas abiertos, geocodificación, rutas y clima;
- sesión principal compartida para voz y cámara;
- conectores reforzados para Google y Outlook;
- diagnóstico sanitizado, supervisión del detector y ciclo de cierre recuperable;
- 211 pruebas automatizadas, 28 subpruebas aprobadas y una prueba opcional omitida en el entorno validado.

Esta versión reemplaza a la anterior como contenido predeterminado de `main`. Los archivos privados, credenciales, memoria personal, logs, workspaces locales y modelos Vosk no forman parte del repositorio.

## 1.5 — Legacy

Última versión anterior a la migración Mark LI. Permanece congelada en el tag `v1.5-legacy`, desde donde puede consultarse o descargarse sin mantener una copia duplicada dentro de `main`.

## Origen

JARVIS Mark LI deriva de Mark XLVIII, creado por FatihMakes, y conserva su atribución y licencia no comercial.
