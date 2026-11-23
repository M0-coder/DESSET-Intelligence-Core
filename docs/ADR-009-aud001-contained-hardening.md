# ADR-009 — INT-009.1: Contención de hallazgos AUD-001

**Estado:** candidato experimental en PR borrador; no autorizado para merge ni producción. **Normativa:** [ASI v3.3, documento 00](https://app.notion.com/p/3b3eb559c05c81b5b971ee384164aa10); **auditoría:** [AUD-001, issue #19](https://github.com/M0-coder/DESSET-Intelligence-Core/issues/19). **Ámbito:** todo el Perú; ningún OSRM con mapas reales fue ejecutado en este cambio.

## Riesgos y límites de la corrección

### AUD-001-F01 (alta): preparación de OSRM sobre un archivo existente

El antiguo control `*.osrm.*` omitía el archivo `*.osrm` desnudo y el manifiesto. Ahora se rechaza cualquier grafo `.osrm`, artefactos `.osrm.*`, manifiesto previo y enlaces simbólicos (incluidos colgantes) **antes de invocar Docker**. El procesamiento, una vez autorizado manualmente, se realiza en un directorio privado **nuevo** (`mktemp -d`) y utiliza una copia local del PBF cuyo SHA-256 vuelve a verificarse. No se vincula el directorio original como volumen de escritura; el origen permanece intacto. El manifiesto de salida queda dentro del directorio de construcción junto a los artefactos. Fallos de construcción dejan su directorio parcial, sin borrado automático para facilitar inspección.

**Limitaciones:** solo se probó con ejecutable Docker simulado, PBF sintético y archivos temporales; no constituye prueba de Docker/OSRM real, seguridad frente a usuarios hostiles concurrentes, calidad de datos o reproducibilidad del backend. La copia consume espacio; exigir revisión de RAM/disco, imagen por digest y permiso antes de un trabajo real. No usar este script para orquestación productiva. El perfil `car.lua` sigue siendo una declaración no certificada para motocicletas o camiones.

### AUD-001-F02 (media-alta): identidad geográfica ambigua

La respuesta OSRM Table devuelve coordenadas de snapping y distancia, pero **no devuelve IDs de negocio autenticados**. Si el waypoint recibido está dentro del umbral de otro punto de **la misma lista** (sources o destinations), la vinculación de fila/columna no es distinguible solo por proximidad: el cliente ahora falla cerrado con `MatrixInputError`. La comprobación no se hace cruzando sources contra destinations, ya que una tabla cuadrada legítima repite ubicaciones a ambos lados.

**Trade-off explícito:** en zonas densas puede rechazar solicitudes válidas entre puntos cercanos. No se han determinado tolerancias por ciudad/perfil; la medida protege contra aceptación silenciosa, pero **no prueba autenticidad del servidor, camino ni identidad de todos los escenarios posibles**. El adaptador debe etiquetar y desagrupar puntos con precaución; cualquier mecanismo de binding garantizado necesitará otro contrato técnico.

### AUD-001-F05 (media): interpretación de viajes interprovinciales

`kind=interprovincial` se limita ahora a **una misma jurisdicción regional**. Interregional requiere exactamente dos jurisdicciones. Esto es un contrato estructural y **no prueba** que los dos puntos estén en provincias distintas. Las coordenadas del catálogo de pruebas siguen declaradas aproximadas/no verificadas.

## Método de verificación

1. Tests RED antes del cambio: cinco fallos nuevos reproducidos sobre el candidato INT-009 sin tocar el repositorio remoto.
2. Tests GREEN tras parche: simulación HTTP para dos orígenes próximos intercambiados, clasificación territorial, archivo `.osrm` simple, manifiesto previo y construcción en directorio aislado; casos positivos previos permanecen válidos.
3. Adversarial de archivos incompletos y enlace simbólico, sin Docker/OSRM real ni sobrescrituras externas.
4. `python -m compileall`, `bash -n`, suite Python, cobertura de sentencias y análisis estático/CI verificados sobre el SHA que se publique. **CI pendiente hasta ejecución oficial**.
5. Cada hallazgo enlazado a [GitHub AUD-001](https://github.com/M0-coder/DESSET-Intelligence-Core/issues/19); preservar fallos y SHA, no auto-merge.

## Decisión

`control_result=PASS` únicamente para las pruebas ejecutadas y citadas. El valor `candidate_decision=BLOCKED` sigue vigente para merge, rutas viales reales/Perú y producción por falta de dataset PBF autenticado, OSRM real, mediciones y revisión independiente; `main` permanece sin protección administrativa. La prioridad posterior será validar y auditar OSRM con cartografía nacional y comparar optimizadores para grandes flotas, sin confundir CI verde con cobertura del país.
