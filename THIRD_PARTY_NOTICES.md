# Avisos de terceros

JARVIS Mark LI incluye o utiliza componentes cuyos derechos pertenecen a sus
respectivos autores.

## Mark XLVIII

Este proyecto deriva de **Mark XLVIII**, creado por
[FatihMakes](https://github.com/FatihMakes), a partir del
[commit `d178f6b`](https://github.com/FatihMakes/Mark-L/commit/d178f6b) del
repositorio público `FatihMakes/Mark-L`.

El autor original declara uso personal y no comercial bajo Creative Commons
Attribution-NonCommercial 4.0 International (CC BY-NC 4.0). La atribución se
conserva en el README, `LICENSE.md` y `NOTICE.md`. Las condiciones publicadas
por el autor original prevalecen sobre cualquier resumen incluido aquí.

Entre los archivos inicialmente conservados sin cambios se encontraba
`config/jarvis.ico`; por lo tanto, no se reclama autoría propia sobre ese
recurso.

## openWakeWord

El detector de palabra de activación utiliza
[openWakeWord](https://github.com/dscripka/openWakeWord).

- El código de openWakeWord está publicado bajo Apache License 2.0.
- Los modelos preentrenados incluidos por openWakeWord están publicados bajo
  Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International
  (CC BY-NC-SA 4.0).
- Los archivos distribuidos en `models/openwakeword/` son
  `embedding_model.onnx`, `melspectrogram.onnx` y `hey_jarvis_v0.1.onnx`.

Consultá el repositorio y la documentación del modelo
[hey_jarvis](https://github.com/dscripka/openWakeWord/blob/main/docs/models/hey_jarvis.md)
para conocer la procedencia y las condiciones completas.

## CryptoJS

`dashboard/static/crypto-js.min.js` contiene
[CryptoJS](https://github.com/brix/crypto-js), distribuido bajo la licencia
MIT:

Copyright (c) 2009-2013 Jeff Mott

Copyright (c) 2013-2016 Evan Vosberg

Se permite, sin cargo, a cualquier persona que obtenga una copia de este
software y de los archivos de documentación asociados (el “Software”), usar
el Software sin restricciones, incluidos los derechos de usar, copiar,
modificar, fusionar, publicar, distribuir, sublicenciar y/o vender copias, y
permitir que las personas a quienes se proporcione el Software hagan lo mismo,
sujeto a la inclusión del aviso de copyright y este aviso de permiso en todas
las copias o partes sustanciales.

EL SOFTWARE SE PROPORCIONA “TAL CUAL”, SIN GARANTÍA DE NINGÚN TIPO, EXPRESA O
IMPLÍCITA, INCLUIDAS, ENTRE OTRAS, LAS GARANTÍAS DE COMERCIABILIDAD, IDONEIDAD
PARA UN FIN PARTICULAR Y NO INFRACCIÓN. EN NINGÚN CASO LOS AUTORES O TITULARES
DEL COPYRIGHT SERÁN RESPONSABLES POR RECLAMOS, DAÑOS U OTRAS
RESPONSABILIDADES, YA SEA EN UNA ACCIÓN CONTRACTUAL, EXTRACONTRACTUAL O DE
OTRO TIPO, QUE SURJA DEL SOFTWARE, SU USO U OTRAS OPERACIONES CON ÉL.

## Dependencias instalables

Las bibliotecas declaradas en los archivos de requisitos no se redistribuyen
como código fuente dentro de este repositorio. Cada una conserva la licencia
publicada por su propio mantenedor.

PyQt6 y PyQt6-WebEngine se instalan como dependencias externas y se ofrecen por
sus mantenedores bajo GPLv3 o licencias comerciales. Este aviso documenta esa
dependencia, pero no modifica ni sustituye sus condiciones.
