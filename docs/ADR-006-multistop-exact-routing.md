# ADR-006 — Secuenciación exacta multi-recogida/multi-entrega (INT-007)

**Estado:** candidato experimental para revisión. **Ámbito:** todo Perú como arquitectura objetivo; ninguna ruta peruana está verificada aquí. [Notion Intelligence Core](https://app.notion.com/p/421eb559c05c81b0b4d7d4ac13253dda) · [Doctrina ASI v3.3, documento 00](https://app.notion.com/p/3b3eb559c05c81b5b971ee384164aa10).

## Objetivo y diferencia respecto de Dispatch V0.1

Dispatch V0.1 asigna a lo sumo un pedido por repartidor en una ola. En cambio,
este algoritmo **ordena múltiples recogidas y entregas ya asignadas a un solo
vehículo** mediante un problema de precedencia/capacidad con tiempos de viaje
dirigidos. Es una capacidad nueva, no un refactor del matching ni un sistema
nacional de optimización de flotas.

## Contrato de entrada/salida

- `DeliveryJob(id, pickup_node, delivery_node, load_units)`: dos nodos distintos por trabajo; todos los nodos, incluido el origen, son globalmente únicos para evitar doble identidad cartográfica.
- `start_node`, `vehicle_capacity_units` entero positivo, lista de hasta `MAX_JOBS=7` trabajos obligatorios.
- `travel_seconds[(origin_node,destination_node)]`: **matriz dirigida** de enteros no negativos, en segundos, hasta 2 147 483 647 por arco. Un par omitido **no tiene ruta**; no rellenar con distancia aérea.
- `max_total_seconds` opcional: límite de tiempo de viaje sumado, no de tiempo de servicio; rechazado si excede el límite técnico de entero por contrato.
- `MultiStopPlan`: secuencia auditable de visitas con tipo (pickup/delivery), duración del tramo entrante, carga a bordo tras cada parada y suma de tiempo de viaje estimado.
- `RouteInputError` para entrada inválida; `NoFeasibleRouteError` cuando no hay una secuencia que sirva **todos** los trabajos, cumpla capacidad y exista en el grafo dirigido.
- No se retorna a base; no hay ventanas temporales, descanso, turnos, tiempo de carga/descarga, tráfico, SLA, precio ni coste monetario. No prometer uso con una flota entera o carga arbitraria.

## Método y complejidad

Programación dinámica memoizada exacta por máscaras de pedidos recogidos,
entregados y última ubicación, con precedencia obligatoria y restricción de
carga a bordo. Igualdad de coste: prioridad estable por ID de trabajo y acción.
El número de estados crece combinatoriamente; se aplica un límite explícito de
siete trabajos para evitar uso imprudente. No extrapolar tiempo de los tests
sintéticos a millones de pedidos.

## Frontera OSRM y cobertura nacional

Para pocos puntos de una ruta, puede obtenerse una matriz cuadrada desde el
cliente existente `fetch_local_osrm_table(points, points, ...)`: cada punto debe
estar geocodificado y validado en su jurisdicción y el servidor local debe
estar construido desde PBF nacional por perfil/digest verificables. Duplicar
los puntos en el protocolo OSRM es viable sólo para este prototipo pequeño.
Los tests de integración usan un servidor HTTP **simulado**. No existen en esta
entrega datos de tráfico real, rutas observadas ni ejecución nacional certificada.

## Garantías y verificación

1. Caso sintético en que recoger dos pedidos antes de repartirlos reduce el
   tiempo total, pero no se admite si sobrepasa la capacidad.
2. Pruebas de entrada hostil: IDs duplicados, nodos mal formados, booleanos,
   duraciones inválidas, direcciones incompletas y trabajos inviables.
3. Comparación de coste exacto contra un **oráculo independiente por enumeración**
   para baterías aleatorias reproducibles de hasta tres pedidos.
4. Control determinista ante orden de input; stress sintético con siete pedidos.
5. Prueba de integración HTTP simulado → tabla OSRM → secuencia multientrega.
6. Evaluar Ruff, compilación, cobertura, CI y SHA sobre el commit publicado;
   registrar prueba adversarial y no declarar `PASS` antes de evidencia.

## Exclusiones y riesgo residual

- OSRM con cartografía real de **todo Perú: NOT_VERIFIED**.
- Rutas con perfiles de moto/camión y vías permitidas: NOT_VERIFIED.
- Rendimiento bajo carga, escalado multi-vehículo, batching/demanda real: NOT_VERIFIED.
- Seguridad operacional, calidad de datos, auditoría independiente y
  protección de `main`: pendientes. `candidate_decision=BLOCKED` para producción.

## Gobierno del cambio

Mantener en PR draft apilado, sin merge ni despliegue. No cambiar silenciosamente
contratos del motor anterior; trazabilidad a documento 00, issue, PR y SHA.

7. Benchmark sintético repetible: `PYTHONPATH=src python benchmarks/bench_multistop.py`; los tiempos de pared dependen de hardware y carga, **no** equivalen a SLA ni a mejora comercial medida.
