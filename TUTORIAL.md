# Tutorial de instalación de JARVIS Mark LI

Esta guía explica cómo preparar una instalación nueva en Windows 10 u 11,
configurar Gemini y ejecutar JARVIS por primera vez. El proyecto está pensado
para Python de 64 bits; Python 3.12 es la versión recomendada.

> JARVIS puede usar el micrófono, la cámara, archivos, aplicaciones y servicios
> conectados. Revisá cada confirmación antes de permitir una acción sensible y
> nunca publiques claves, tokens ni archivos de configuración personales.

## 1. Requisitos previos

Instalá lo siguiente antes de continuar:

- [Git para Windows](https://git-scm.com/download/win);
- [Python 3.12 de 64 bits](https://www.python.org/downloads/windows/);
- una clave de la API de Gemini;
- un micrófono; la cámara es opcional.

Durante la instalación de Python, activá la opción **Add Python to PATH**. Para
comprobar que Git y Python están disponibles, abrí PowerShell y ejecutá:

```powershell
git --version
py -3.12 --version
```

## 2. Descargar el repositorio

En PowerShell, elegí una carpeta de trabajo y ejecutá:

```powershell
git clone https://github.com/alejogaisser/J.A.R.V.I.S.-Prototype.git
Set-Location J.A.R.V.I.S.-Prototype
```

## 3. Crear el entorno e instalar dependencias

Creá un entorno virtual aislado, activalo e instalá las dependencias:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Si PowerShell bloquea la activación del entorno, habilitala sólo para la sesión
actual y volvé a intentarlo:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Cuando el entorno está activo, el prompt suele mostrar `(.venv)`. Para futuras
sesiones, entrá nuevamente en la carpeta del proyecto y ejecutá solamente el
comando de activación.

## 4. Configurar Gemini

Creá la configuración local a partir del ejemplo:

```powershell
Copy-Item config\api_keys.example.json config\api_keys.json
notepad config\api_keys.json
```

Completá únicamente el valor de `gemini_api_key` con tu clave:

```json
{
  "vision_model": "gemini-3.5-flash",
  "vision_fallback_model": "gemini-3.1-flash-lite",
  "gemini_api_key": "TU_CLAVE",
  "os_system": "windows",
  "camera_index": 0
}
```

Guardá el archivo y cerrá el editor. `config/api_keys.json` está ignorado por
Git: no lo agregues manualmente ni compartas su contenido.

## 5. Verificar la instalación sin iniciar dispositivos

Primero comprobá que el launcher responde sin abrir Gemini, el micrófono ni la
cámara:

```powershell
python jarvis_launcher.py --help
python -m pip check
```

Quienes quieran ejecutar la validación de desarrollo completa deben instalar
`requirements-dev.txt` y usar el script reproducible descrito en
[`docs/baseline.md`](docs/baseline.md). Las pruebas automatizadas usan mocks y
no demuestran que el hardware local funcione.

## 6. Primer inicio

Para abrir JARVIS directamente:

```powershell
python jarvis_launcher.py --mode direct
```

Windows puede pedir permiso para acceder al micrófono o a la cámara. Concedé
solamente los permisos que quieras usar. El primer arranque puede tardar más
mientras se cargan la interfaz y los componentes de IA.

Para iniciar el detector local de la frase **Hey Jarvis**:

```powershell
python jarvis_launcher.py --mode wake
```

Para ver diagnósticos temporales del detector:

```powershell
python jarvis_launcher.py --mode wake --console
```

No ejecutes simultáneamente los modos `direct` y `wake`.

## 7. Solución de problemas frecuentes

### `py -3.12` no se reconoce

Reinstalá Python 3.12 de 64 bits con el launcher para Windows y habilitá su
integración con PATH. Cerrá y volvé a abrir PowerShell antes de probar otra vez.

### Falta un módulo de Python

Confirmá que `(.venv)` aparece en el prompt y repetí:

```powershell
python -m pip install -r requirements.txt
python -m pip check
```

### Playwright no encuentra Chromium

Con el entorno activo, ejecutá:

```powershell
python -m playwright install chromium
```

### Gemini rechaza la conexión

Revisá que `gemini_api_key` tenga una clave válida, sin espacios agregados, y
que la conexión a Internet esté disponible. No pegues la clave en un issue,
captura de pantalla o registro público.

### No se escucha el micrófono

Comprobá en **Configuración de Windows > Privacidad y seguridad > Micrófono**
que las aplicaciones de escritorio tengan acceso. Después cerrá JARVIS y
volvelo a abrir; no pruebes varios modos al mismo tiempo.

## 8. Actualizar una instalación existente

Antes de actualizar, conservá una copia privada y cifrada de tus configuraciones
locales. Desde la carpeta del repositorio:

```powershell
git pull
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Los archivos privados excluidos por `.gitignore` —claves, credenciales OAuth,
memoria y configuración personal— no se recuperan desde GitHub.

## Próximos pasos

- Consultá las integraciones opcionales en el [`readme.md`](readme.md#optional-integrations).
- Revisá las reglas de seguridad en [`SECURITY.md`](SECURITY.md).
- Para contribuir, seguí [`CONTRIBUTING.md`](CONTRIBUTING.md).
- Para la arquitectura y validación técnica, abrí [`docs/README.md`](docs/README.md).
