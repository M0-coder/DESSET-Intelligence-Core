# ADR-008 — Optimización adaptativa de flotas (INT-009)

**Estado:** implementación experimental propuesta, sin adopción productiva ni merge. **Dominio geográfico objetivo:** todo el Perú; los benchmarks son artificiales y sin coordenadas.

**Gobierno:** [ASI v3.3 — doctrina universal 00](https://app.notion.com/p/3b3eb559c05c81b5b971ee384164aa10) (`ASI-NORM-TESTING-001`, `ASI-NORM-CHANGE-001`, `ASI-NORM-REPRO-001`, `ASI-NORM-PROOF-001`) y [Notion DESSET Intelligence Core](https://app.notion.com/p/421eb559c05c81b0b4d7d4ac13253dda). La doctrina universal no se modifica aquí.

## Objetivo / contrato

Resolver lotes que superan los límites del exacto INT-008 (4 vehículos y 6 pedidos) mediante un **heurístico de inserción factible** con selección determinista y prioridad a pedidos que disponen de menos vehículos factibles. Cada pedido tiene dos paradas: recogida y entrega. Las matrices son dirigidas, en segundos **estimados suministrados por otro sistema**, nunca tiempos de tráfico observados.

- Límite defensivo inicial: **24 vehículos / 80 pedidos** por llamada; **20 pedidos por vehículo**. No son umbrales de rendimiento validado. Las mediciones comparativas actuales llegan a **32 pedidos / 10 vehículos**; existen pruebas locales exploratorias individuales hasta **64 pedidos / 16 vehículos** (aproximadamente 2,97 s), sin concurrencia ni percentiles.
- El orden de recogida→entrega es obligatorio. Capacidad máxima se aplica en **cada parada** y las duraciones por vehículo respetan el límite opcional del llamador.
- Arcos de ruta ausentes = imposibilidad, no imputación. Todo pedido está servido una sola vez o aparece no asignado.
- El resultado y los desempates no dependen del orden de las listas/diccionario suministrados.
- El heurístico **NO garantiza** máxima cantidad servida ni costo de recorrido mínimo global. Se preserva `algorithm_version="fleet-insertion-v0.1"` para trazabilidad.
- `optimize_fleet_adaptive` selecciona automáticamente `optimize_fleet` **exacto** solo cuando los límites de ese módulo lo permiten; de lo contrario usa la inserción. No captura ni oculta errores de entrada para cambiar de estrategia silenciosamente.

## Algoritmo

1. Validación estricta de vehículo, pedido, nodos únicos, matrices y tamaños. Sin red, archivos, dependencias externas ni datos de clientes.
2. Para cada vehículo/pedido se buscan posiciones de inserción de pickup y delivery, preservando la secuencia de paradas previas. Una inserción es elegible solo si todos los arcos existen y cumple restricciones.
3. Se elige pedido con **menor número de vehículos actualmente elegibles** y luego **menor incremento de segundos**. Se itera hasta que no queden inserciones factibles.
4. Cache de candidatos por pareja pedido/vehículo: al cambiar un vehículo se invalidan **solo sus candidatos**. Evaluación de costo *ligera* para cada intento; los `RouteVisit` completos se construyen únicamente para el plan resultante.
5. El `FleetPlan` resultante comparte tipos con el motor exacto, pero su `algorithm_version` diferencia inequívocamente la estrategia.

## Hallazgo adversarial que impide declararlo óptimo

Caso sintético mínimo de dos vehículos/dos pedidos: el vehículo V2 puede recoger J0 con costo 2, pero la solución exacta usa V1 con recogidas intercaladas para servir **J0 y J1** con costo 4. La inserción greedy compromete J0 con V2 y solo sirve **1 de 2** pedidos. Un test de regresión conserva este **contraejemplo real del algoritmo**, en vez de eliminarlo o declarar optimalidad inexistente. `optimize_fleet_adaptive` envía el escenario pequeño al motor exacto y sirve ambos. Para lotes grandes, el problema sigue siendo **riesgo material de calidad de solución**: evaluar heurísticas de reparación, búsqueda local/relocation, PyVRP/VROOM/OR-Tools con las mismas restricciones y datos.

## Evidencia / alcance

- Pruebas unitarias: ausencia de rutas, tamaño y datos inválidos, capacidad, precedencia, presupuesto, inputs permutados, comparación del heurístico contra exacto para casos pequeños, contraejemplo y selección adaptativa.
- Benchmark reproducible **sintético**: `PYTHONPATH=src python benchmarks/bench_fleet_insertion.py`. Compara mismo código de elección con evaluador completo lento versus evaluador ligero; comprueba equivalencia completa de `FleetPlan` antes de reportar tiempos. Resultados guardados en `evidence/INT-009-local-benchmark.json`. La latencia no incluye obtención de matrices OSRM, comunicación, colas, tráfico ni carga concurrente.
- Limites 80/24 **no** equivalen a pruebas de rendimiento a ese tamaño. No declarar algoritmos listos para dispatch de tiempo real sin medir p95/p99, errores y calidad por lote.
- Pendiente: ejecución con grafo OSRM real y extracto OSM peruano trazable/ODbL, tiempos observados, costos comerciales, seguridad de producción, pruebas de múltiples servicios, análisis de propiedades ampliado y mutation testing sistemático.

## Gate/autoridad

Los tests y GitHub Actions deben evaluarse en SHA exacto del PR. `candidate_decision=BLOCKED` para explotación operativa: `required_control_not_verified`, `missing_required_capability`, `unmitigated_material_risk`. Sin auto-merge, despliegue, datos reales, releases o alteraciones de DNS. El hecho de que GitHub CI esté verde **no** transforma la heurística en un algoritmo óptimo ni demuestra cobertura nacional.
