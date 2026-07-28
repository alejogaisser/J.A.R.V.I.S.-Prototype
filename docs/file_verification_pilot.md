# Piloto de verificación de archivos

## Alcance

`file_controller` produce `ToolResult` v2 para tres operaciones sobre archivos
regulares:

- `create_file`;
- `copy`;
- `move`.

Las operaciones de directorios y el resto del controlador mantienen el retorno
legacy. Esto permite desactivar el piloto volviendo el dispatch a los handlers
existentes, sin cambiar sus firmas.

## Evidencia y estados

El verifier vuelve a abrir el destino después de la operación y captura:

- ruta absoluta resuelta;
- tamaño en bytes;
- SHA-256 leído desde el filesystem.

Crear compara el hash observado con el contenido solicitado. Copiar y mover
comparan tamaño y hash del origen con el destino; mover también exige ausencia
del origen. Sólo entonces el resultado declara
`succeeded/applied/verified`.

Un conflicto de destino se rechaza antes de escribir y queda
`rejected/not_applied`. Si la operación termina pero la evidencia no puede
observarse o no coincide, el resultado queda `succeeded` con verificación
fallida y nunca comunica el efecto como verificado.

## Rollback declarado

El resultado incluye una receta explícita y marca el rollback como disponible:

- crear/copiar: enviar el destino a la papelera;
- mover: mover el destino nuevamente a la ruta de origen.

La ejecución automática de esas recetas no forma parte de este piloto. Queda
pendiente incorporarla detrás de policy y verificar también su resultado.

## Límites

- No hay verificación recursiva de árboles de directorios.
- No se garantiza una instantánea atómica si otro proceso modifica un archivo
  entre la operación y la lectura de evidencia.
- SHA-256 prueba igualdad de contenido observada, no identidad ni procedencia.
- El timeout del executor aún no cancela un handler síncrono en ejecución.
