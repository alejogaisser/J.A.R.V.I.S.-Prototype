# JARVIS — Mark XLVIII

Asistente personal de escritorio con conversación por voz en tiempo real, control del sistema, memoria persistente, visión, automatizaciones e integraciones con servicios externos. Esta versión parte de **Mark XLVIII**, de [FatihMakes](https://github.com/FatihMakes/Mark-XLVIII), y contiene adaptaciones y mejoras propias orientadas principalmente a Windows.

> El proyecto puede controlar aplicaciones, archivos y servicios conectados. Revisá las confirmaciones antes de autorizar acciones sensibles y nunca publiques tus claves o configuraciones privadas.

## Funciones principales

- Conversación de voz de baja latencia mediante Gemini Live.
- Inicio directo o activación local por palabra clave con Vosk.
- Interrupción inmediata de la respuesta mediante `Esc` o desde la interfaz.
- Captura de pantalla y cámara para análisis visual.
- Control de aplicaciones, ventanas, teclado, mouse, volumen, brillo y archivos.
- Búsqueda web, noticias, clima, vuelos, YouTube y recordatorios.
- Memoria persistente y memoria de scripts reutilizables.
- Cálculo matemático seguro y simbólico con SymPy.
- Integración con un vault de Obsidian.
- Conectores OAuth para Gmail, Google Calendar, Google Drive y Outlook.
- Dashboard local para usar JARVIS desde el teléfono, enviar comandos, audio y archivos.
- Sistema central de herramientas con permisos y confirmaciones según el nivel de riesgo.
- Agente de desarrollo, procesamiento de archivos y ayuda con código.

## Requisitos

| Componente | Requisito |
| --- | --- |
| Sistema operativo | Windows 10/11 recomendado; algunas funciones también contemplan macOS y Linux |
| Python | 3.11 o 3.12 recomendado |
| Hardware | Micrófono; cámara opcional |
| Servicio de IA | Clave de Gemini API |
| Palabra de activación | Modelo Vosk local, solo si se usa el modo `wake` |

## Instalación

Cloná el repositorio y entrá a la carpeta:

```powershell
git clone https://github.com/TU-USUARIO/TU-REPOSITORIO.git
cd TU-REPOSITORIO
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

Descargá un modelo compatible de Vosk y descomprimilo dentro de `models/`. La ruta predeterminada es:

```text
models/vosk-model-small-en-us-0.15
```

Después ejecutá:

```powershell
python jarvis_launcher.py --mode wake
```

Para configurar frases, modelo y sensibilidad:

```powershell
python jarvis_launcher.py --configure --phrases "hey jarvis,jarvis,oye jarvis" --model "models/vosk-model-small-en-us-0.15" --sensitivity 180
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

Para Gmail, Google Calendar y Google Drive, creá credenciales OAuth de aplicación de escritorio y guardalas con la estructura indicada en:

```text
config/google_oauth_client.example.json
```

El archivo real debe llamarse `config/google_oauth_client.json`.

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

```powershell
python -m pytest
```

Para comprobar rápidamente la sintaxis del proyecto:

```powershell
python -m compileall -q .
```

## Estructura del proyecto

```text
.
├── main.py                    # Sesión principal, audio y despacho de herramientas
├── jarvis_launcher.py         # Inicio directo o por palabra de activación
├── wake_word.py               # Escucha local con Vosk
├── ui.py                      # Interfaz gráfica PyQt6
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
├── config/                    # Ejemplos y configuración local ignorada
├── tests/                     # Pruebas automatizadas
└── utils/                     # Rutas y archivos temporales
```

## Créditos y licencia

Proyecto original **Mark XLVIII** creado por [FatihMakes](https://www.youtube.com/@FatihMakes).

El proyecto original se distribuye para uso personal y no comercial bajo [Creative Commons BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). Conservá la atribución y verificá las condiciones de la licencia antes de redistribuir modificaciones.
