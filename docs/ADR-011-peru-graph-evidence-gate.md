# ADR-011 — Verificación de archivos OSRM nacionales antes de consultas

**Estado:** experimento controlado INT-011. **Alcance geográfico objetivo:** todo el Perú; este control NO demuestra cobertura real. **Doctrina:** [ASI v3.3, fuente 00](https://app.notion.com/p/3b3eb559c05c81b5b971ee384164aa10). **Base:** PR #23 INT-010, SHA `51275287954407767923e423a241ed4dbb197a33`. **Registro:** [Notion DESSET Intelligence Core](https://app.notion.com/p/421eb559c05c81b0b4d7d4ac13253dda).

## Riesgo y propósito

El constructor `scripts/build_peru_osrm.sh` prepara un grafo MLD en un directorio nuevo y emite un inventario de archivos con hashes. Hasta ahora, el lector de probes validaba el PBF y su hash pero **no comprobaba** que los archivos OSRM enumerados en el manifiesto estuvieran presentes, completos, inalterados y vinculados al mismo PBF declarado. Un reporte de consultas no debe presentarse como evidencia de una construcción local reproducible si esa verificación falta.

## Contrato implementado

`verify_staged_peru_graph()` comprueba en **solo lectura** un directorio aislado: existencia de un PBF Perú fechado, igualdad de bytes frente al SHA-256 aportado por el operador, cabecera OSMHeader preliminar, manifiesto sin enlaces simbólicos y con identidad coincidente (PBF, imagen por digest, MLD, `/opt/car.lua`, estados no productivos), hashes SHA-256 y tamaños exactos de los archivos `.osrm`/`.osrm.*`, ausencia de archivos adicionales o entradas no inventariadas, nombres locales únicos y rechazo de rutas transversales. Bloquea si hay diferencias, antes de emitir consultas a OSRM.

El script existente `scripts/probe_peru_osrm.py` conserva el modo anterior. Si se entregan **juntos** `--graph-dir` y `--image-reference`, ejecuta ese gate y anota el resultado en JSON. Las respuestas HTTP siguen recibiéndose solo desde `127.0.0.1` por el cliente preexistente. Los fallos de integridad retornan error sin producir reporte de éxito.

**Fundamental:** igualdad de hashes contra un SHA indicado por la persona que opera **NO autentica origen de Geofabrik**, legalidad o completitud del PBF, veracidad de la imagen Docker, perfil de vehículo, ni que **el daemon HTTP esté cargando efectivamente esos archivos**. Un servidor simulado puede responder aun con archivos sintéticos. Por tanto:

- `graph_artifact_integrity_control_result=PASS` solo significa bytes e inventario correctos.
- `daemon_graph_binding_control_result=NOT_VERIFIED` y `dataset_source_authenticity_control_result=NOT_VERIFIED` incluso cuando todos los controles pasan.
- `nationwide_coverage_control_result=NOT_VERIFIED` y `candidate_decision=BLOCKED` siempre en este experimento.
- Los diez probes anteriores usan coordenadas aproximadas no verificadas y no bastan para certificar 25 jurisdicciones.

## Ejecución futura sobre datos auténticos (no ejecutada aquí)

1. Obtener el PBF nacional de [Geofabrik](https://download.geofabrik.de/south-america/peru/), registrar URL, instante UTC, fecha de corte, términos ODbL, tamaño, MD5 publicado y SHA-256 obtenido de los bytes; contrastar de forma independiente los metadatos del proveedor.
2. Obtener y verificar un digest real de imagen del backend [Project OSRM](https://github.com/Project-OSRM/osrm-backend). No utilizar `latest`.
3. Ejecutar el preprocesado MLD con los scripts ya existentes sobre disco suficiente, sin sobrescribir mapas; confirmar hash del PBF copiado en `--graph-dir`.
4. Iniciar un daemon OSRM local ligado a **ese** grafo mediante control del proceso/container y registrar la evidencia; esta verificación de daemon **no está automatizada por esta ADR**.
5. Ejecutar el script de probes con directorio de grafo, digest de imagen y archivo PBF, y revisar respuesta/latencia/ausencia de rutas para rutas urbanas, interprovinciales e interregionales de múltiples zonas. No inferir modo motocicleta de `/opt/car.lua`.
6. En una etapa posterior, observar ETAs, validar sentido de vías, densidad, vehículos y conectividad del país con datos geocodificados y revisión externa. Ninguna muestra limitada prueba cobertura nacional.

## Evidencia y riesgos de integración

- Pruebas sintéticas con archivos `OSMHeader` falsos y servidor HTTP falso: **solo contrato**, no OSM válido ni OSRM auténtico. Pruebas negativas para corrupción, inventario incompleto, rutas relativas, PBF/imagen distintos, manifiesto contradictorio y enlaces simbólicos.
- Mutation testing puntual: alterar el hash de un archivo o su manifiesto debe llevar a `NationalProbeError`. No puntuación integral de mutaciones.
- No se modifica despacho, flota, heurísticas, seguridad de CI, secretos, DNS, ramas previas ni producción.
- El test independiente del algoritmo INT-010 con 160 casos sintéticos mantiene invariantes y recupera pedidos en 24; **es revisión interna con método distinto**, no firma de auditor externo, ni se mezcla con este cambio.

**Dictamen:** candidate_decision `BLOCKED` para claims de OSRM real, Perú nacional y producción. GO exclusivamente para ejecutar tests y revisar el PR en borrador cuando CI sea satisfactoria.
