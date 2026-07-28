# Línea base reproducible

## Alcance

Esta línea base cubre instalación, imports, sintaxis, arranque no interactivo y
suite automatizada. No abre Gemini Live ni usa micrófono, cámara, navegador,
cuentas, dashboard LAN o herramientas con efectos reales.

Entorno de referencia auditado el 2026-07-28:

- Windows 10/11, 64 bits;
- Python 3.14.6;
- 37 declaraciones de herramientas;
- 213 tests y 65 subtests aprobados desde un worktree y entorno virtual
  limpios después de esta etapa;
- una advertencia externa de `google-genai` sobre Python 3.17.

Python 3.12 es la versión recomendada para una instalación nueva. Python
3.13-3.14 se admite cuando todas las ruedas de las dependencias estén
disponibles para Windows.

## Instalación limpia

Desde PowerShell, en la raíz del repositorio:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
Copy-Item config\api_keys.example.json config\api_keys.json
```

La copia de configuración sirve sólo como plantilla. El chequeo de línea base
no necesita una clave real y nunca debe versionarse `config/api_keys.json`.

## Validación reproducible

Con el entorno virtual activo:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\validate_baseline.ps1
```

También se puede indicar un intérprete explícito:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\validate_baseline.ps1 `
  -Python .\.venv\Scripts\python.exe
```

Para una iteración rápida que conserva todos los chequeos salvo la suite
completa:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\validate_baseline.ps1 `
  -Python .\.venv\Scripts\python.exe -SkipFullTests
```

El comando ejecuta, en orden:

1. `python -m pip check`;
2. `python jarvis_launcher.py --help`;
3. imports del núcleo, launcher, memoria y wake word;
4. import de `main.py` con Qt offscreen y comprobación de 37 tools;
5. `compileall` sobre el código y los tests;
6. contrato de inventario de herramientas;
7. suite completa, salvo uso de `-SkipFullTests`;
8. `git diff --check`.

## Capacidades y dependencias

`requirements.txt` representa el runtime principal publicado.
`requirements-dev.txt` lo incluye y agrega `pytest`, necesario para ejecutar la
suite y el comando de validación. Algunas rutas
de procesamiento avanzado cargan dependencias opcionales sólo cuando se usan.
La auditoría detectó imports opcionales de `python-docx`, `pandas`, `openpyxl`,
`PyPDF2`/`pdfplumber`, `pydub`, `faster-whisper`, `kokoro`, `miniaudio` y
`torch`. No se agregan al conjunto principal hasta verificar por capacidad:

- que la ruta sea alcanzable desde una tool registrada;
- que exista una rueda compatible con Python soportado;
- que el costo de instalación sea proporcional;
- que la ausencia produzca un error claro y no un fallo de arranque.

`beautifulsoup4` permanece declarado aunque no se observó uso de runtime. Su
retiro queda pendiente hasta confirmar que no sea una dependencia prevista de
una capacidad opcional.

## Baseline de comportamiento

| Frontera | Comprobación automatizada | Limitación |
| --- | --- | --- |
| Launcher | `--help` termina correctamente | No inicia procesos hijos |
| Imports | núcleo, wake, memoria y `main.py` importan | No valida hardware |
| UI | `main.py` importa con `QT_QPA_PLATFORM=offscreen` | No verifica interacción visual |
| Tools | 37 declaraciones coinciden con la matriz | No ejecuta efectos reales |
| Sintaxis | `compileall` del árbol Python | No reemplaza lint o type checking |
| Dependencias | `pip check` | Verificación de instalación limpia se registra por ejecución |
| Regresiones | suite completa | Red, Gemini, cuentas y SO se mockean |

Las métricas de wake, interrupción, reconexión y shutdown requieren hardware o
fault injection específico y siguen pendientes en `ROADMAP.md`.

## Resultado de la ejecución de referencia

Se creó un entorno virtual nuevo con Python 3.14.6 y se instalaron
`requirements-dev.txt` y Chromium para Playwright. La validación completa
terminó con:

- `pip check`: sin dependencias rotas;
- launcher `--help`: correcto;
- smoke imports: correcto;
- `main.py` offscreen: correcto, 37 tools;
- `compileall`: correcto;
- inventario: 1 test y 37 subtests aprobados;
- suite: 213 tests y 65 subtests aprobados;
- `git diff --check`: sin errores.

La primera ejecución limpia expuso que
`tests/test_script_memory.py` dependía de `memory/scripts.json`, un archivo
personal ignorado. El test ahora crea su rutina en `TemporaryDirectory`, por
lo que no lee ni modifica memoria real.

## Rollback

Esta etapa no modifica el runtime. Puede revertirse eliminando este documento,
la matriz, el test de sincronización y el script de validación.
