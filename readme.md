# JARVIS — Mark LI

**Versión actual: 2.0.0 — Mark LI**

Asistente personal de escritorio para Windows con conversación por voz en tiempo real, activación local, interfaz holográfica, memoria controlable, visión, herramientas científicas, automatizaciones e integraciones con servicios externos.

Mark LI es una evolución amplia del proyecto anterior: reorganiza la interfaz, el ciclo de audio, la memoria, los permisos y el registro de herramientas, pero conserva la atribución a **Mark XLVIII**, de [FatihMakes](https://github.com/FatihMakes/Mark-XLVIII).

La versión anterior publicada permanece preservada mediante el tag `v1.5-legacy`. Los cambios principales de cada versión están documentados en [CHANGELOG.md](CHANGELOG.md).

> El proyecto puede controlar aplicaciones, archivos y servicios conectados. Revisá las confirmaciones antes de autorizar acciones sensibles y nunca publiques tus claves o configuraciones privadas.

## Funciones principales

- Conversación de voz de baja latencia mediante Gemini Live.
- Inicio directo o activación local “Hey Jarvis” mediante OpenWakeWord, con Vosk como respaldo.
- Recuperación automática del micrófono después de mute, silencio o bloqueo del driver.
- Interrupción inmediata de la respuesta mediante `Esc` o desde la interfaz.
- Interfaz Mark LI con Core, Pet Mode y workspaces especializados.
- Captura de pantalla y cámara continua dentro de la sesión principal.
- Control de aplicaciones, ventanas, teclado, mouse, volumen, brillo y archivos.
- Búsqueda web, noticias, clima, vuelos, YouTube y recordatorios.
- Memoria persistente controlable y grafo formado exclusivamente por recuerdos reales.
- Study para matemática, gráficos 2D/3D, matrices, física, química y anatomía educativa.
- GEO con mapas, geocodificación, rutas y clima mediante servicios abiertos.
- Integración con un vault de Obsidian.
- Conectores OAuth para Gmail, Google Calendar, Google Drive y Outlook.
- Dashboard local para usar JARVIS desde el teléfono, enviar comandos, audio y archivos.
- Sistema central de herramientas con permisos y confirmaciones según el nivel de riesgo.
- Agente de desarrollo, procesamiento de archivos y ayuda con código.

## Requisitos

| Componente | Requisito |
| --- | --- |
| Sistema operativo | Windows 10/11 recomendado; algunas funciones también contemplan macOS y Linux |
| Python | 3.12 a 3.14, 64 bits |
| Hardware | Micrófono; cámara opcional |
| Servicio de IA | Clave de Gemini API |
| Palabra de activación | Modelos OpenWakeWord incluidos; Vosk es el respaldo configurable |

## Instalación

Cloná el repositorio y entrá a la carpeta:

```powershell
git clone https://github.com/alejogaisser/J.A.R.V.I.S.-Prototype.git
cd J.A.R.V.I.S.-Prototype
```

Creá un entorno virtual e instalá las dependencias:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

También se puede ejecutar el instalador incluido:

```powershell
python setup.py
```

## Configuración inicial

Copiá el archivo de ejemplo y completá tu clave de Gemini:

```powershell
Copy-Item config\api_keys.example.json config\api_keys.json
```

Ejemplo mínimo:

```json
{
  "vision_model": "gemini-3.5-flash",
  "vision_fallback_model": "gemini-3.1-flash-lite",
  "gemini_api_key": "TU_CLAVE",
  "os_system": "windows",
  "camera_index": 0
}
```

`config/api_keys.json` está ignorado por Git. No lo agregues manualmente al repositorio.

## Ejecución

### Inicio directo

```powershell
python jarvis_launcher.py --mode direct
```

### Activación por voz

Los tres modelos ONNX necesarios para “Hey Jarvis” están incluidos en `models/openwakeword/`. Ejecutá:

```powershell
python jarvis_launcher.py --mode wake
```

OpenWakeWord comienza a escuchar apenas carga el detector dedicado; Vosk se
prepara en segundo plano y se adjunta después como respaldo. Al detectar la
frase, JARVIS restaura y abre la aplicación base en pantalla completa. La UI
muestra su primer frame antes de cargar el SDK de Gemini; el saludo inicial se
reintenta si la primera sesión se interrumpe. Pet Mode se activa únicamente
desde la propia interfaz o mediante una orden explícita durante la sesión.

Para ejecutar temporalmente el detector con diagnóstico visible:

```powershell
python jarvis_launcher.py --mode wake --console
```

Las frases personalizadas usan Vosk como respaldo. Descargá un modelo compatible dentro de `models/` y configurá su ruta:

```powershell
python jarvis_launcher.py --configure --phrases "oye jarvis" --model "models/vosk-model-small-en-us-0.15" --sensitivity 180
```

La configuración generada se guarda en `config/wake_word.json` y no se publica en Git.

## Integraciones opcionales

### Obsidian

Copiá el ejemplo y configurá la ruta de tu vault:

```powershell
Copy-Item config\obsidian.example.json config\obsidian.json
```

Las escrituras y modificaciones requieren confirmación por seguridad.

### Google

Para Gmail, Google Calendar y Google Drive, incluidos Google Docs, Sheets y
Presentations, creá credenciales OAuth de aplicación de escritorio y guardalas
con la estructura indicada en:

```text
config/google_oauth_client.example.json
```

El archivo real debe llamarse `config/google_oauth_client.json`.

En el mismo proyecto de Google Cloud habilitá **Google Drive API**, **Google
Docs API**, **Google Sheets API** y **Google Slides API**. JARVIS reutiliza el
owner OAuth y el token protegido del conector de Drive; no abre una ruta de
automatización visual paralela. Las búsquedas, lecturas y exportaciones son
directas después de autorizar la cuenta. Crear o editar archivos remotos pasa
por la confirmación central y verifica el efecto mediante la API.

### Microsoft Outlook

Registrá una aplicación en Microsoft Entra y creá:

```text
config/microsoft_oauth_client.json
```

Usá `config/microsoft_oauth_client.example.json` como referencia. Los tokens OAuth se almacenan en el gestor de credenciales del sistema mediante `keyring`, no en el repositorio.

## Permisos y seguridad

Las herramientas se clasifican por riesgo. Las acciones destructivas o sensibles —por ejemplo, borrar o mover archivos, enviar mensajes, modificar Obsidian o ejecutar tareas de desarrollo— solicitan confirmación.

La política local se puede personalizar a partir de:

```powershell
Copy-Item config\permissions.example.json config\permissions.json
```

No desactives confirmaciones para herramientas sensibles sin revisar previamente su alcance.

## Archivos privados y respaldo

El `.gitignore` excluye, entre otros:

- claves API y archivos `.env`;
- clientes OAuth y certificados locales;
- configuración personal y auditoría de conectores;
- memoria personal de JARVIS;
- modelos Vosk;
- entornos virtuales, cachés y logs.

Estos archivos **no se recuperan al clonar el repositorio**. Guardalos en una copia privada y cifrada antes de reinstalar el sistema. Nunca los publiques en GitHub, aunque el repositorio sea privado.

## Pruebas

Instalá las dependencias de desarrollo (incluyen el runtime y pytest):

```powershell
python -m pip install -r requirements-dev.txt
```

```powershell
python -m pytest
```

La línea base completa y reproducible (dependencias, launcher, imports, tool
inventory, sintaxis, tests y diff) se ejecuta con:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\validate_baseline.ps1 `
  -Python .\.venv\Scripts\python.exe
```

Consultá [docs/baseline.md](docs/baseline.md) para el alcance, limitaciones y
procedimiento de instalación limpia, y
[docs/tool_migration_matrix.md](docs/tool_migration_matrix.md) para el
inventario contractual de las 37 herramientas.

Para comprobar únicamente la sintaxis del proyecto:

```powershell
python -m compileall -q .
```

## Estructura del proyecto

```text
.
├── main.py                    # Sesión principal, audio y despacho de herramientas
├── jarvis_launcher.py         # Inicio directo o por palabra de activación
├── wake_word.py               # OpenWakeWord, fallback Vosk y diagnóstico acústico
├── ui.py                      # Interfaz gráfica PyQt6
├── ui_mk2/                    # Core, Pet y workspaces visuales Mark LI
├── actions/                   # Acciones disponibles para JARVIS
├── connectors/                # Gmail, Calendar, Drive y Outlook
├── core/
│   ├── permissions/           # Política, niveles de riesgo y confirmaciones
│   ├── tools/                 # Registro y ejecución central de herramientas
│   ├── installer.py           # Instalación de componentes opcionales
│   ├── security.py            # Reglas adicionales de seguridad
│   └── prompt.txt             # Personalidad e instrucciones del asistente
├── dashboard/                 # Panel web local y conexión con el teléfono
├── memory/                    # Gestores de memoria persistente y scripts
├── models/openwakeword/       # Modelos ONNX mínimos para “Hey Jarvis”
├── config/                    # Ejemplos y configuración local ignorada
├── tests/                     # Pruebas automatizadas
└── utils/                     # Rutas y archivos temporales
```

## Créditos y licencia

JARVIS Mark LI deriva de **Mark XLVIII**, creado por
[FatihMakes](https://github.com/FatihMakes). La versión original de referencia
es el [commit `d178f6b`](https://github.com/FatihMakes/Mark-L/commit/d178f6b).
Esta adaptación conserva el uso personal y no comercial establecido por el
autor original e identifica sus modificaciones en [NOTICE.md](NOTICE.md).

Las contribuciones y modificaciones de Mark LI corresponden a
[Alejo Gaisser (`@alejogaisser`)](https://github.com/alejogaisser),
anteriormente `@AlejoGaisser07`.

Las modificaciones originales de Mark LI se publican, en la medida en que sus
derechos correspondan al mantenedor, bajo
[Creative Commons BY-NC 4.0](LICENSE.md). Es código fuente público para uso
personal y no comercial; no se presenta como un proyecto open source conforme
a la definición OSI.

Los modelos de wake word y demás componentes externos mantienen licencias
propias. Consultá [los avisos de terceros](THIRD_PARTY_NOTICES.md) y la
[política de seguridad](SECURITY.md) antes de publicar un fork.

Este proyecto es independiente y no está afiliado, patrocinado ni aprobado por
Marvel Entertainment, Marvel Studios, The Walt Disney Company ni por los
titulares de las marcas asociadas a JARVIS o Iron Man.
